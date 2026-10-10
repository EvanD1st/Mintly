"""Database-coordinated OpenSea requests, independent of mint execution locks."""
from datetime import datetime,timezone,timedelta
from math import ceil
from sqlalchemy import select,delete
from app.database import AsyncSessionLocal
from app.models import OpenSeaRequestGate,OpenSeaRequestWaiter
from app.config import settings
from app.services.mint_plans import aware
from app.services.mint_diagnostics import retry_seconds

EPOCH=datetime(1970,1,1,tzinfo=timezone.utc)

def group(path):
    if path.endswith('/auth/keys') or path=='/auth/keys':return 'key_creation'
    if '/drops/' in path and path.endswith('/mint'):return 'mint'
    return 'read'

async def rows(db,names):
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    insert=pg_insert if db.bind.dialect.name=='postgresql' else sqlite_insert
    for name in names:
        await db.execute(insert(OpenSeaRequestGate).values(name=name,next_request_at=EPOCH,blocked_until=EPOCH).on_conflict_do_nothing(index_elements=['name']))
    return (await db.scalars(select(OpenSeaRequestGate).where(OpenSeaRequestGate.name.in_(names)).order_by(OpenSeaRequestGate.name).with_for_update())).all()

async def acquire(path,*,factory=None,now=None,request_id=None):
    if not settings.OPENSEA_COORDINATE_REQUESTS:return 0,None
    now=now or datetime.now(timezone.utc);name=group(path)
    async with (factory or AsyncSessionLocal)() as db:
        from app.services.mint_diagnostics import current_phase
        if name=='mint' and current_phase()=='preflight':
            from app.models import CopyEvent,CopyRule,CopyWatch,CopyCheck,MintTask,Wallet,User
            from app.services.automatic import MODE
            from sqlalchemy import or_
            pending_copy=await db.scalar(select(CopyEvent.id).join(CopyWatch,CopyWatch.id==CopyEvent.watch_id)
                .join(CopyRule,CopyRule.watch_id==CopyEvent.watch_id).join(User,User.id==CopyEvent.user_id)
                .outerjoin(CopyCheck,CopyCheck.watch_id==CopyEvent.watch_id).where(CopyEvent.status=='detected',CopyEvent.task_id.is_(None),
                CopyWatch.archived_at.is_(None),CopyRule.status=='active',CopyRule.expires_at>now,
                CopyRule.chain_id==CopyEvent.observation['chain_id'].as_integer(),
                CopyRule.resume_after_block<CopyEvent.observation['block_number'].as_integer(),
                User.automation_paused.is_(False),User.is_active.is_(True),User.deleted_at.is_(None),
                or_(CopyCheck.watch_id.is_(None),CopyCheck.active.is_(False)),
                CopyEvent.observation['start'].as_integer()<=int(now.timestamp()),
                CopyEvent.observation['end'].as_integer()>int(now.timestamp()),
                or_(CopyEvent.next_attempt_at.is_(None),CopyEvent.next_attempt_at<=now)).limit(1))
            pending_task=await db.scalar(select(MintTask.id).join(Wallet,Wallet.id==MintTask.wallet_id).join(User,User.id==Wallet.user_id)
                .where(MintTask.status=='armed',MintTask.execution_mode==MODE,User.automation_paused.is_(False),
                User.is_active.is_(True),User.deleted_at.is_(None),Wallet.archived_at.is_(None),
                MintTask.scheduled_for_utc<=now,MintTask.expires_at_utc>now).limit(1))
            if pending_copy or pending_task:
                await db.commit()
                return 30,'execution_priority'
        gates=await rows(db,['all',name])
        if request_id:
            await db.execute(delete(OpenSeaRequestWaiter).where(OpenSeaRequestWaiter.expires_at<=now))
            waiter=await db.get(OpenSeaRequestWaiter,request_id)
            if waiter is None:
                waiter=OpenSeaRequestWaiter(id=request_id,priority=0 if current_phase() in ('copy','preparation') else 1 if name=='mint' else 2,
                    expires_at=now+timedelta(seconds=max(1,min(10,settings.OPENSEA_QUEUE_WAIT_SECONDS))+1))
                db.add(waiter);await db.flush()
            first=await db.scalar(select(OpenSeaRequestWaiter.id).order_by(OpenSeaRequestWaiter.priority,OpenSeaRequestWaiter.created_at,OpenSeaRequestWaiter.id).limit(1))
            if first!=request_id:
                await db.commit();return 1,'queued'
        blocked=max(aware(g.blocked_until) for g in gates)
        due=max([blocked]+[aware(g.next_request_at) for g in gates])
        if due>now:
            await db.commit()
            return max(1,ceil((due-now).total_seconds())),'cooldown' if blocked>now else 'paced'
        global_gap=max(1.0,settings.OPENSEA_GLOBAL_REQUEST_SECONDS)
        gap=max(global_gap,settings.OPENSEA_MINT_REQUEST_SECONDS) if name=='mint' else max(global_gap,60) if name=='key_creation' else global_gap
        for g in gates:g.next_request_at=now+timedelta(seconds=global_gap if g.name=='all' else gap)
        if request_id:await db.delete(waiter)
        await db.commit()
    return 0,None

async def release_waiter(request_id):
    if not settings.OPENSEA_COORDINATE_REQUESTS:return
    async with AsyncSessionLocal() as db:
        await db.execute(delete(OpenSeaRequestWaiter).where(OpenSeaRequestWaiter.id==request_id));await db.commit()

async def permit(path):
    """Short shared queue; long cooldowns return to each task's durable retry schedule."""
    import asyncio,time,uuid
    request_id=str(uuid.uuid4());until=time.monotonic()+max(0,min(10,settings.OPENSEA_QUEUE_WAIT_SECONDS))
    try:
        while True:
            delay,reason=await acquire(path,request_id=request_id)
            if not delay or reason not in ('paced','queued') or time.monotonic()+delay>until:return delay,reason
            await asyncio.sleep(delay)
    finally:await release_waiter(request_id)

async def observe(path,status,headers,*,factory=None,now=None):
    if not settings.OPENSEA_COORDINATE_REQUESTS:return
    now=now or datetime.now(timezone.utc)
    wait=retry_seconds(headers.get('Retry-After'))
    reset=None
    try:
        seconds=int(headers.get('X-RateLimit-Reset',''))-int(now.timestamp())
        if 0<seconds<=86400:reset=now+timedelta(seconds=seconds)
    except (ValueError,TypeError):pass
    name=group(path);updates={}
    if status==429:
        # Reset may describe a different nonempty bucket (e.g. 599/600).
        # Retry-After is authoritative for this endpoint unless that bucket is exhausted.
        until=now+timedelta(seconds=wait if wait is not None else 60)
        if reset and headers.get('X-RateLimit-Remaining')=='0':until=max(until,reset)
        updates[name]=until
    if headers.get('X-RateLimit-Remaining')=='0' and reset:updates['all']=reset
    if not updates:return
    async with (factory or AsyncSessionLocal)() as db:
        for g in await rows(db,sorted(updates)):
            g.blocked_until=max(aware(g.blocked_until),updates[g.name])
        await db.commit()
