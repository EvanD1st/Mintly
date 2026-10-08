"""Owner-only alerts, emitted on actionable state changes outside mint execution."""
import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, update
from app.database import AsyncSessionLocal
from app.models import Wallet, User, AutomaticGrant, MintTask, MintAuthorization, CopyRule, WalletAlert, ActivityEvent
from app.models.activity import NotificationDevice
from app.services import automatic
from app.services.mint_plans import aware
from app.services.notifier import NotificationService

NETWORKS={1:'Ethereum',8453:'Base',4663:'Robinhood',31337:'Local test',11155111:'Sepolia'}


async def read_balance(address,chain):
    web3=await automatic.provider_for(chain)
    try:
        return await web3.eth.get_balance(address,'pending')
    finally:
        await web3.provider.disconnect()


async def poll(session_factory=AsyncSessionLocal,balance=read_balance,*,now=None):
    now=now or datetime.now(timezone.utc)
    async with session_factory() as db:
        wallets=(await db.execute(select(Wallet,User).join(User,User.id==Wallet.user_id).where(Wallet.archived_at.is_(None),
            User.is_active.is_(True),User.deleted_at.is_(None)))).all()
        grants=(await db.scalars(select(AutomaticGrant).where(AutomaticGrant.status=='enabled'))).all()
        tasks=(await db.execute(select(MintTask,MintAuthorization).join(MintAuthorization,MintAuthorization.id==MintTask.authorization_id)
            .where(MintTask.status.in_(['armed','preparing','prepared']),MintTask.expires_at_utc>now,
                MintTask.scheduled_for_utc<=now+timedelta(minutes=30)))).all()
        rules=(await db.scalars(select(CopyRule).where(CopyRule.status=='active',CopyRule.expires_at>now))).all()
        targets=[]
        for wallet,user in wallets:
            for chain in sorted({g.chain_id for g in grants if g.wallet_id==wallet.id and g.user_id==user.id}):
                own=[g for g in grants if g.wallet_id==wallet.id and g.chain_id==chain and g.user_id==user.id]
                upcoming=[(t,a) for t,a in tasks if t.wallet_id==wallet.id and a.snapshot['chain_id']==chain]
                copying=[r for r in rules if r.chain_id==chain and r.user_id==user.id and r.grant_id in {g.id for g in own}]
                relevant={a.grant_id for _,a in upcoming}|{r.grant_id for r in copying}
                policy=min((g for g in own if g.id in relevant),key=lambda g:aware(g.expires_at),default=None)
                policy=policy or max(own,key=lambda g:aware(g.expires_at))
                targets.append((wallet.id,user.id,wallet.address,chain,user.automation_paused,
                    policy.id,aware(policy.expires_at),sum(a.total_spend_cap_wei for _,a in upcoming),
                    min((aware(r.expires_at) for r in copying),default=None),bool(copying)))
    slots=asyncio.Semaphore(3)
    async def check(target):
        wid,uid,address,chain,paused,gid,expiry,required,copy_expiry,has_copy=target
        network=NETWORKS.get(chain,'this network')
        conditions={
            'approval_expiry':(expiry<=now+timedelta(hours=24),automatic.digest([gid,expiry.isoformat()]),
                'Approval ends soon' if expiry>now else 'Approval expired',
                f'Renew your automatic approval on {network}.'),
            'copy_expiry':(copy_expiry is not None and copy_expiry<=now+timedelta(hours=24),
                automatic.digest([wid,chain,str(copy_expiry)]),'Copy approval ends soon',f'Renew copying on {network} in Copy settings.')}
        # No guessed gas balance: zero cannot pay gas; upcoming caps are explicitly maxima.
        if not paused and (required or has_copy):
            try:
                async with slots:
                    amount=await asyncio.wait_for(balance(address,chain),timeout=8)
                low=amount<required if required else amount==0
                conditions['low_funds']=(low,'low_funds',f'Check ETH on {network}',
                    f'Balance is below your upcoming mint maximum on {network}. Check Wallets.' if required else f'Add ETH on {network} for copy mint gas.')
            except Exception:
                pass  # RPC outage never becomes a false low-balance transition.
        else:
            conditions['low_funds']=(False,'low_funds','','')
        return wid,uid,chain,gid,expiry,conditions
    observed=await asyncio.gather(*(check(t) for t in targets))
    async with session_factory() as db:
        await automatic.lock_execution(db)
        current_pairs=set()
        for wid,uid,chain,gid,expiry,conditions in observed:
            wallet=await db.get(Wallet,wid,populate_existing=True)
            user=await db.get(User,uid,populate_existing=True)
            if not wallet or wallet.archived_at or wallet.user_id!=uid or not user or not user.is_active or user.deleted_at:
                continue
            grant=await db.get(AutomaticGrant,gid,populate_existing=True)
            if not grant or grant.status!='enabled' or aware(grant.expires_at)!=expiry:
                continue
            current_pairs.add((wid,uid,chain))
            live_task=await db.scalar(select(MintTask.id).join(MintAuthorization,MintAuthorization.id==MintTask.authorization_id).where(
                MintTask.wallet_id==wid,MintTask.status.in_(['armed','preparing','prepared']),MintTask.expires_at_utc>now,
                MintTask.scheduled_for_utc<=now+timedelta(minutes=30),MintAuthorization.snapshot['chain_id'].as_integer()==chain).limit(1))
            live_copy=await db.scalar(select(CopyRule.id).join(AutomaticGrant,AutomaticGrant.id==CopyRule.grant_id).where(
                AutomaticGrant.wallet_id==wid,CopyRule.user_id==uid,CopyRule.chain_id==chain,CopyRule.status=='active',CopyRule.expires_at>now).limit(1))
            if user.automation_paused or not (live_task or live_copy):
                conditions['low_funds']=(False,'low_funds','','')
            if not live_copy:
                conditions['copy_expiry']=(False,'none','','')
            for kind,(active,fingerprint,title,detail) in conditions.items():
                key=automatic.digest([uid,wid,chain,kind])
                alert=await db.get(WalletAlert,key)
                if not alert:
                    alert=WalletAlert(id=key,user_id=uid,wallet_id=wid,chain_id=chain,kind=kind,
                        active=False,fingerprint='',version=0,pending=False,title='',detail='')
                    db.add(alert)
                if active and (not alert.active or alert.fingerprint!=fingerprint):
                    alert.version+=1
                    alert.pending,alert.next_attempt_at=True,now
                    db.add(ActivityEvent(user_id=uid,event_type='wallet_alert',label=title,detail=detail,is_demo=False,icon_name='wallet'))
                if not active:
                    alert.pending=False
                alert.active,alert.fingerprint,alert.title,alert.detail=active,fingerprint,title,detail
        # Clear retired wallet/policy alerts, but retain a balance alert during an RPC outage.
        for alert in (await db.scalars(select(WalletAlert).where(WalletAlert.active.is_(True)))).all():
            if (alert.wallet_id,alert.user_id,alert.chain_id) not in current_pairs:
                alert.active,alert.pending=False,False
        await db.commit()


async def deliver(session_factory=AsyncSessionLocal,notify=NotificationService.send_notification,*,now=None):
    now=now or datetime.now(timezone.utc)
    async with session_factory() as db:
        alerts=(await db.scalars(select(WalletAlert).where(WalletAlert.active.is_(True),WalletAlert.pending.is_(True),
            WalletAlert.next_attempt_at<=now).order_by(WalletAlert.updated_at).limit(25))).all()
        messages=[]
        for alert in alerts:
            wallet=await db.get(Wallet,alert.wallet_id)
            user=await db.get(User,alert.user_id)
            if not wallet or wallet.archived_at or not user or not user.is_active or user.deleted_at:
                alert.active,alert.pending=False,False
                continue
            devices=(await db.scalars(select(NotificationDevice).where(NotificationDevice.user_id==alert.user_id,
                NotificationDevice.is_active.is_(True)))).all()
            opted=any((d.preferences or {}).get('wallet_alerts',(d.preferences or {}).get('mint_status',True)) for d in devices)
            if not opted:
                alert.pending=False
                continue
            messages.append((alert.id,alert.version,alert.user_id,alert.title,alert.detail))
        await db.commit()
    for aid,version,uid,title,detail in messages:
        try:
            sent=await notify(title,detail,category='wallet_alerts',deep_link='mintly://wallets',user_id=uid)
        except Exception:
            sent=False
        async with session_factory() as db:
            await db.execute(update(WalletAlert).where(WalletAlert.id==aid,WalletAlert.version==version,
                WalletAlert.active.is_(True),WalletAlert.pending.is_(True)).values(pending=not sent,
                    next_attempt_at=now+timedelta(minutes=5),sent_at=now if sent else None))
            await db.commit()
