"""Optional collection artwork. Never called by mint preparation or the signer."""
import time
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from app.api.deps import get_current_user, get_db
from app.models import MintPlan, MintTask, Wallet, Drop, CopyEvent, OpenSeaRequestWaiter, CollectionArtwork
from app.database import AsyncSessionLocal
from app.services.mint_plans import aware
from app.config import settings
from app.services.opensea import OpenSeaClient, OpenSeaUnavailable, collection_slug, singleflight, CHAINS

router = APIRouter(prefix='/artwork', tags=['artwork'])
_cache = {}


def image_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        url = urlsplit(value)
        # OpenSea's image CDN; no arbitrary image proxy, redirects, or key in the client.
        host = url.hostname or ''
        if (url.scheme == 'https' and (host == 'seadn.io' or host.endswith('.seadn.io')
                or host == 'openseauserdata.com' or host.endswith('.openseauserdata.com'))
                and not url.username and not url.password and url.port in (None, 443)):
            return value
    except ValueError:
        pass
    return None


def artwork_key(slug, chain_id, contract):
    return f'contract:{chain_id}:{contract.lower()}' if chain_id and contract else f'slug:{slug}'


async def collection_image(slug=None, *, chain_id=None, contract=None, allow_fetch=True, db=None):
    cache_key = artwork_key(slug, chain_id, contract)
    persisted = await db.get(CollectionArtwork, cache_key) if db else None
    now = datetime.now(timezone.utc)
    old = image_url(persisted.image_url) if persisted and aware(persisted.stale_until) > now else None
    if persisted and aware(persisted.refresh_after) > now:
        return old
    if not allow_fetch and old:
        return old
    if db:
        await db.commit()  # No transaction or execution lock during provider IO.
    async def fetch():
        cached = _cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        if not allow_fetch:
            return old
        result = old
        ttl = 60
        resolved = slug or (persisted.collection_slug if persisted else None)
        try:
            client = OpenSeaClient()
            key = await client._key()
            if resolved is None:
                chain = next((name for name, spec in CHAINS.items() if spec[0] == chain_id), None)
                if not chain or not re.fullmatch(r'0x[a-fA-F0-9]{40}', contract or ''):
                    return None
                status, data = await client._request('GET', f'/chain/{chain}/contract/{contract}', key=key)
                if status != 200 or str(data.get('address', '')).lower() != contract.lower() or data.get('chain') != chain:
                    raise OpenSeaUnavailable('Collection artwork unavailable.')
                resolved = data.get('collection')
            if not isinstance(resolved, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', resolved):
                return None
            status, data = await client._request('GET', f'/collections/{resolved}', key=key)
            if status == 200 and data.get('collection') == resolved:
                supplied = image_url(data.get('image_url'))
                result = supplied or old
                ttl = 86400 if supplied else 600
        except OpenSeaUnavailable:
            pass
        _cache[cache_key] = (time.monotonic() + ttl, result)
        if db:
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            insert = pg_insert if db.bind.dialect.name == 'postgresql' else sqlite_insert
            checked = datetime.now(timezone.utc)
            values = dict(key=cache_key, collection_slug=resolved, image_url=result, refresh_after=checked+timedelta(seconds=ttl),
                stale_until=checked+timedelta(days=7) if ttl==86400 else
                    (persisted.stale_until if persisted else checked+timedelta(seconds=ttl)),
                created_at=checked, updated_at=checked)
            await db.execute(insert(CollectionArtwork).values(**values).on_conflict_do_update(
                index_elements=['key'], set_={k:v for k,v in values.items() if k not in ('key','created_at')}))
            await db.commit()
        while len(_cache) > 512:
            _cache.pop(next(iter(_cache)))
        return result
    return await singleflight(('artwork', cache_key), fetch)


async def refresh_image(slug, chain_id, contract):
    # Background work uses its own session; it never inherits a request session.
    async with AsyncSessionLocal() as db:
        try:
            await collection_image(slug, chain_id=chain_id, contract=contract,
                allow_fetch=not await minting_busy(db), db=db)
        except Exception:
            await db.rollback()  # Optional artwork cannot fail a screen request.


async def minting_busy(db):
    """Artwork yields to due preparation without taking the execution lock."""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(seconds=max(1, settings.OPENSEA_GLOBAL_REQUEST_SECONDS))
    if await db.scalar(select(OpenSeaRequestWaiter.id).where(
            OpenSeaRequestWaiter.priority == 0, OpenSeaRequestWaiter.expires_at > now).limit(1)):
        return True
    if await db.scalar(select(MintTask.id).where(MintTask.status.in_(['armed', 'preparing']),
            MintTask.scheduled_for_utc <= horizon, MintTask.expires_at_utc > now).limit(1)):
        return True
    return bool(await db.scalar(select(CopyEvent.id).where(CopyEvent.status == 'detected',
        CopyEvent.task_id.is_(None), CopyEvent.observation['start'].as_integer() <= int(horizon.timestamp()),
        CopyEvent.observation['end'].as_integer() > int(now.timestamp())).limit(1)))


@router.get('')
async def artwork(background_tasks: BackgroundTasks, reference: str = Query(min_length=3, max_length=150),
                  user=Depends(get_current_user), db=Depends(get_db)):
    kind, _, record_id = reference.partition(':')
    slug = None
    chain_id = contract = None
    if kind == 'plan':
        plan = await db.get(MintPlan, record_id)
        if not plan or plan.user_id != user.id:
            raise HTTPException(404, 'Collection not found.')
        slug = plan.collection_slug
        chain_id, contract = plan.chain_id, plan.contract_address
    elif kind == 'copy':
        event = await db.get(CopyEvent, record_id)
        if not event or event.user_id != user.id:
            raise HTTPException(404, 'Collection not found.')
        chain_id, contract = event.observation.get('chain_id'), event.observation.get('contract')
    elif kind == 'drop':
        own_task = await db.scalar(select(MintTask.id).join(Wallet, Wallet.id == MintTask.wallet_id)
            .where(MintTask.drop_id == record_id, Wallet.user_id == user.id).limit(1))
        if own_task:
            drop = await db.get(Drop, record_id)
        else:
            from app.api.drops import get_drop_detail
            drop = await get_drop_detail(record_id, db)
        if not drop:
            raise HTTPException(404, 'Collection not found.')
        chain_id, contract = drop.chain_id, drop.contract_address
        try:
            slug = collection_slug(drop.mint_page_url)
        except OpenSeaUnavailable:
            chain_id, contract = drop.chain_id, drop.contract_address
    else:
        raise HTTPException(422, 'Invalid collection reference.')
    cached = await db.get(CollectionArtwork, artwork_key(slug, chain_id, contract))
    now = datetime.now(timezone.utc)
    if cached and cached.image_url and aware(cached.stale_until)>now:
        if aware(cached.refresh_after)<=now:
            background_tasks.add_task(refresh_image, slug, chain_id, contract)
        return {'image_url': image_url(cached.image_url)}
    return {'image_url': await collection_image(slug, chain_id=chain_id, contract=contract,
        allow_fetch=not await minting_busy(db), db=db)}
