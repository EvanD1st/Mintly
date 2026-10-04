"""Owner-scoped Copy mints API. Following never grants spending authority."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import uuid
import httpx
from eth_utils import is_address, to_checksum_address
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func
from app.api.deps import get_db, get_current_user
from app.config import settings
from app.models import CopyWatch, CopyRule, CopyEvent, MintTask, MintAuthorization, ActivityEvent
from app.services import automatic, copy_mints as copying
from app.services.mint_plans import aware
from app.schemas.drop import DropSchema

router = APIRouter(prefix='/copy-mints', tags=['copy-mints'])


class FollowRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    address: str = Field(min_length=42, max_length=42)
    label: str = Field(min_length=1, max_length=80)
    chains: list[int] = Field(min_length=1, max_length=3)


class RuleRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: uuid.UUID
    grant_id: uuid.UUID
    quantity: int = Field(ge=1, le=100, strict=True)
    price_cap_eth: str = Field(pattern=r'^[0-9]+(\.[0-9]+)?$', max_length=40)
    fee_cap_eth: str = Field(pattern=r'^[0-9]+(\.[0-9]+)?$', max_length=40)
    budget_eth: str = Field(pattern=r'^[0-9]+(\.[0-9]+)?$', max_length=40)
    free_only: bool = False
    expires_at: datetime
    consent: bool


class PauseRequest(BaseModel):
    paused: bool


async def own_watch(db, user, watch_id, *, archived=False):
    watch = await db.get(CopyWatch, watch_id)
    if not watch or watch.user_id != user.id or (watch.archived_at and not archived):
        raise HTTPException(404, 'Followed wallet not found.')
    return watch


async def own_event(db, user, event_id):
    event = await db.get(CopyEvent, event_id)
    if not event or event.user_id != user.id:
        raise HTTPException(404, 'Copy activity not found.')
    return event


def public_rule(rule):
    snapshot = dict(rule.snapshot)
    for key in ('price_cap_wei','fee_cap_wei','total_cap_wei','budget_wei'):
        snapshot[key] = str(snapshot[key])
    return {'id': rule.id, 'watch_id': rule.watch_id, 'chain_id': rule.chain_id,
        'status': 'expired' if aware(rule.expires_at) <= datetime.now(timezone.utc) else rule.status,
        'expires_at': rule.expires_at, 'snapshot': snapshot,
        'budget_wei': str(rule.budget_wei), 'spent_wei': str(rule.spent_wei), 'reserved_wei': str(rule.reserved_wei),
        'remaining_wei': str(max(0, rule.budget_wei - rule.spent_wei - rule.reserved_wei))}


def record(db, user_id, label, detail):
    db.add(ActivityEvent(user_id=user_id, event_type='copy_settings', label=label,
        detail=detail, icon_name='gem', is_demo=False))


async def register_rule(rule_id):
    try:
        token = Path(settings.AUTOMATIC_SIGNER_TOKEN_FILE).read_text().strip()
        if len(token) < 32:
            raise ValueError()
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.post(settings.AUTOMATIC_SIGNER_URL + f'/copy-rules/{rule_id}/register',
                headers={'Authorization': 'Bearer ' + token})
            response.raise_for_status()
    except Exception:
        raise HTTPException(503, 'Copy approval is saved but not active. Retry to confirm the isolated signer; no copy can sign yet.') from None


@router.get('')
async def overview(user=Depends(get_current_user), db=Depends(get_db)):
    watches = (await db.execute(select(CopyWatch).where(CopyWatch.user_id == user.id,
        CopyWatch.archived_at.is_(None)).order_by(CopyWatch.created_at.desc()))).scalars().all()
    cutoff = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp())
    counts = dict((await db.execute(select(CopyEvent.watch_id, func.count()).where(CopyEvent.user_id == user.id,
        CopyEvent.observation['timestamp'].as_integer() >= cutoff)
        .group_by(CopyEvent.watch_id))).all())
    rules = (await db.execute(select(CopyRule).where(CopyRule.user_id == user.id,
        CopyRule.status.in_(['active','paused','registering'])).order_by(CopyRule.created_at.desc()))).scalars().all()
    return {'enabled': settings.ENABLE_COPY_MINTS, 'networks': copying.networks(),
        'watches': [{'id': w.id, 'address': w.address, 'label': w.label, 'chains': w.chains,
            'cursors': w.cursors, 'recent_mints': counts.get(w.id, 0),
            'rules': [public_rule(r) for r in rules if r.watch_id == w.id]} for w in watches],
        'scope': 'Direct public SeaDrop NFT mints. Each collection’s public stage is copied once per receiving wallet.'}


@router.post('/watches')
async def follow(req: FollowRequest, user=Depends(get_current_user), db=Depends(get_db)):
    copying.enabled()
    if not is_address(req.address) or int(req.address, 16) == 0 or not req.label.strip():
        raise HTTPException(422, 'Enter a valid nonzero wallet address and a name.')
    allowed = {n['chain_id'] for n in copying.networks()}
    if not set(req.chains) <= allowed or len(set(req.chains)) != len(req.chains):
        raise HTTPException(422, 'Choose supported networks without duplicates.')
    await automatic.lock_execution(db)
    key = automatic.digest([user.id, req.address.lower()])
    old = await db.get(CopyWatch, key)
    if not old or old.archived_at:
        count = await db.scalar(select(func.count()).select_from(CopyWatch).where(CopyWatch.user_id == user.id,
            CopyWatch.archived_at.is_(None)))
        if count >= 20:
            raise HTTPException(409, 'Follow up to 20 wallets. Remove a wallet before adding another.')
    if not old:
        old = CopyWatch(id=key, user_id=user.id, address=to_checksum_address(req.address),
            label=req.label.strip(), chains=req.chains, cursors={})
        db.add(old)
    else:
        if old.archived_at:
            old.archived_at = None
        # Removing a network also stops its unsigned copies.
        for rule in (await db.execute(select(CopyRule).where(CopyRule.watch_id == key,
            CopyRule.status.in_(['active','registering'])))).scalars().all():
            if rule.chain_id not in req.chains:
                await copying.pause_rule(db, rule)
        old.label, old.chains = req.label.strip(), req.chains
    record(db, user.id, 'Wallet followed for public mints', f'{old.label}: {old.address}. Copying needs a separate approval.')
    await db.commit()
    return {'id': key}


@router.delete('/watches/{watch_id}')
async def remove(watch_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    await automatic.lock_execution(db)
    watch = await own_watch(db, user, watch_id, archived=True)
    for rule in (await db.execute(select(CopyRule).where(CopyRule.watch_id == watch.id))).scalars().all():
        await copying.pause_rule(db, rule)
        rule.status = 'revoked'
    watch.archived_at = datetime.now(timezone.utc)
    record(db, user.id, 'Followed wallet removed', f'{watch.label}: {watch.address}. Activity and approvals retained in History.')
    await db.commit()
    return {'history_retained': True, 'signed_transactions_still_tracked': True}


@router.post('/watches/{watch_id}/rules')
async def approve(watch_id: str, req: RuleRequest, user=Depends(get_current_user), db=Depends(get_db)):
    copying.enabled()
    await automatic.lock_execution(db)
    watch = await own_watch(db, user, watch_id)
    grant = await automatic.grant_for(db, str(req.grant_id), user.id)
    if grant.chain_id not in watch.chains or grant.account.lower() == watch.address.lower():
        raise HTTPException(409, 'Choose a policy on a monitored network for a different receiving wallet.')
    if 'public' not in grant.scope['mint_kinds']:
        raise HTTPException(409, 'This policy cannot mint public stages.')
    expiry = aware(req.expires_at)
    if req.expires_at.tzinfo is None or not req.consent or not datetime.now(timezone.utc) < expiry <= min(
            aware(grant.expires_at), datetime.now(timezone.utc) + timedelta(days=30)):
        raise HTTPException(422, 'Approve finite limits and an expiry within your wallet policy.')
    price, fee, budget = map(automatic.wei, (req.price_cap_eth, req.fee_cap_eth, req.budget_eth))
    total = price * req.quantity + fee
    if req.free_only and price != 0:
        raise HTTPException(422, 'Free mints only requires a zero mint-price cap.')
    key = str(req.request_id)
    old = await db.get(CopyRule, key)
    request = dict(watch_id=watch.id, user_id=user.id, grant_id=grant.id, wallet_id=grant.wallet_id,
        account=grant.account, source_address=watch.address, chain_id=grant.chain_id, quantity=req.quantity,
        price_cap_wei=price, fee_cap_wei=fee, total_cap_wei=total, budget_wei=budget,
        free_only=req.free_only, expiry=int(expiry.timestamp()))
    if old:
        if any(old.snapshot.get(k) != v for k, v in request.items()):
            raise HTTPException(409, 'Approval request changed. Open a new review.')
        if old.status != 'registering':
            return public_rule(old)  # Retry cannot reset spent money or resume a paused rule.
        rule = old
    else:
        if not 0 < fee <= total <= min(budget, int(grant.scope['max_task_wei'])) or budget > grant.budget_wei - grant.spent_wei - grant.reserved_wei:
            raise HTTPException(409, 'Copy limits exceed the wallet’s available budget or per-mint allowance.')
        web3 = await automatic.provider_for(grant.chain_id)
        try:
            head = await web3.eth.block_number
        finally:
            await web3.provider.disconnect()
        for prior in (await db.execute(select(CopyRule).where(CopyRule.watch_id == watch.id,
                CopyRule.chain_id == grant.chain_id, CopyRule.status.in_(['active','registering','paused'])))).scalars().all():
            await copying.pause_rule(db, prior)
            prior.status = 'revoked'
        request['approved_at'] = int(datetime.now(timezone.utc).timestamp())
        request['after_block'] = head
        rule = CopyRule(id=key, watch_id=watch.id, user_id=user.id, grant_id=grant.id, chain_id=grant.chain_id,
            snapshot=request, context_hash=automatic.digest(request), status='registering', expires_at=expiry,
            resume_after_block=head, budget_wei=budget, reserved_wei=0, spent_wei=0)
        db.add(rule)
        record(db, user.id, 'Copy mint limits approved', f'{watch.label}: rule {key}; chain {grant.chain_id}; expiry {expiry.isoformat()}')
    await db.commit()  # Registration reads the durable approval, never caller-supplied signing data.
    await register_rule(rule.id)
    await automatic.lock_execution(db)
    await db.refresh(rule)
    await db.refresh(watch)
    if rule.status == 'registering' and not watch.archived_at:
        rule.status = 'active'
    await db.commit()
    return public_rule(rule)


@router.post('/pause')
@router.post('/watches/{watch_id}/pause')
async def pause(req: PauseRequest, watch_id: str | None = None, user=Depends(get_current_user), db=Depends(get_db)):
    copying.enabled()
    await automatic.lock_execution(db)
    if watch_id:
        await own_watch(db, user, watch_id)
    rules = (await db.execute(select(CopyRule).where(CopyRule.user_id == user.id,
        CopyRule.status.in_(['active','paused','registering']),
        *([CopyRule.watch_id == watch_id] if watch_id else [])))).scalars().all()
    for rule in rules:
        if req.paused:
            await copying.pause_rule(db, rule)
        elif rule.status == 'paused' and aware(rule.expires_at) > datetime.now(timezone.utc):
            watch = await own_watch(db, user, rule.watch_id)
            await automatic.grant_for(db, rule.grant_id, user.id)
            if rule.chain_id not in watch.chains or rule.budget_wei <= rule.spent_wei + rule.reserved_wei:
                continue
            # Revalidate the independent pin. Paused intervals never create backlog spending.
            await register_rule(rule.id)
            web3 = await automatic.provider_for(rule.chain_id)
            try:
                rule.resume_after_block = await web3.eth.block_number
            finally:
                await web3.provider.disconnect()
            rule.status = 'active'
    record(db, user.id, 'Copying paused' if req.paused else 'Copying resumed',
        f'{watch_id or "All followed wallets"}. Signed transactions remain tracked; paused intervals are not copied.')
    await db.commit()
    return {'paused': req.paused}


@router.get('/activity')
async def activity(watch_id: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
                   user=Depends(get_current_user), db=Depends(get_db)):
    conditions = [CopyEvent.user_id == user.id]
    if watch_id:
        await own_watch(db, user, watch_id, archived=True)
        conditions.append(CopyEvent.watch_id == watch_id)
    events = (await db.execute(select(CopyEvent).where(*conditions).order_by(CopyEvent.created_at.desc(), CopyEvent.id)
        .offset(offset).limit(limit))).scalars().all()
    total = await db.scalar(select(func.count()).select_from(CopyEvent).where(*conditions))
    tasks = (await db.execute(select(MintTask).join(CopyEvent, CopyEvent.task_id == MintTask.id).where(*conditions))).scalars().all()
    entries = []
    for event in events:
        task = await db.get(MintTask, event.task_id) if event.task_id else None
        watch = await db.get(CopyWatch, event.watch_id)
        o = dict(event.observation)
        o['price_wei'] = str(o['price_wei'])
        entries.append({'id': event.id, 'watch_id': event.watch_id, 'wallet_label': watch.label,
            'observed_at': event.created_at, 'observation': o, 'status': task.status if task else event.status,
            'note': task.failure_reason if task else event.note, 'task_id': event.task_id,
            'transaction_hash': task.transaction_hash if task else None,
            'quantity': (await db.get(MintAuthorization,
                task.authorization_id)).quantity if task else None,
            'actual_cost_wei': str(task.actual_total_cost_wei) if task and task.actual_total_cost_wei is not None else None})
    return {'events': entries, 'total': total, 'next_offset': offset + len(events) if offset + len(events) < total else None,
        'copied_mints': sum(t.status == 'confirmed' for t in tasks),
        'spent_wei': str(sum(t.actual_total_cost_wei or 0 for t in tasks))}


@router.get('/events/{event_id}/context')
async def context(event_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    copying.enabled()
    event = await own_event(db, user, event_id)
    if event.task_id:
        raise HTTPException(409, 'This observed mint already has a copying task.')
    web3 = await automatic.provider_for(event.observation['chain_id'])
    try:
        await copying.verify_source(web3, event.observation)
        drop, stage = await copying.drop_for(db, web3, event.observation)
        await db.commit()
        await db.refresh(drop, ['stages'])
        return {'drop': DropSchema.model_validate(drop), 'copy_event_id': event.id}
    finally:
        await web3.provider.disconnect()
