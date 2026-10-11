"""Optional collection artwork. Never called by mint preparation or the signer."""
import time
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from app.api.deps import get_current_user, get_db
from app.models import MintPlan, MintTask, Wallet, Drop, CopyEvent, OpenSeaRequestWaiter
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


async def collection_image(slug=None, *, chain_id=None, contract=None, allow_fetch=True):
    cache_key = slug or (chain_id, contract)
    async def fetch():
        cached = _cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        if not allow_fetch:
            return None
        result = None
        ttl = 60
        try:
            client = OpenSeaClient()
            key = await client._key()
            resolved = slug
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
                result = image_url(data.get('image_url'))
                ttl = 86400 if result else 600
        except OpenSeaUnavailable:
            pass
        _cache[cache_key] = (time.monotonic() + ttl, result)
        while len(_cache) > 512:
            _cache.pop(next(iter(_cache)))
        return result
    return await singleflight(('artwork', cache_key), fetch)


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
async def artwork(reference: str = Query(min_length=3, max_length=150),
                  user=Depends(get_current_user), db=Depends(get_db)):
    kind, _, record_id = reference.partition(':')
    slug = None
    chain_id = contract = None
    if kind == 'plan':
        plan = await db.get(MintPlan, record_id)
        if not plan or plan.user_id != user.id:
            raise HTTPException(404, 'Collection not found.')
        slug = plan.collection_slug
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
        try:
            slug = collection_slug(drop.mint_page_url)
        except OpenSeaUnavailable:
            chain_id, contract = drop.chain_id, drop.contract_address
    else:
        raise HTTPException(422, 'Invalid collection reference.')
    return {'image_url': await collection_image(slug, chain_id=chain_id, contract=contract,
        allow_fetch=not await minting_busy(db))}
