"""Explicit operator maintenance of expiry only; never imported by an HTTP route.

Run inside the custody-import boundary, which already owns writable policy files.
All original spending limits, ledgers, task snapshots and paused states stay intact.
"""
import argparse
import asyncio
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import uuid
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.config import settings
from app.models import AutomaticGrant, CopyRule, OpenSeaAccess, Wallet, User, ActivityEvent
from app.services import automatic, opensea_identity
from app.services.custody import CustodyVault, private_read, private_write
from app.services.mint_plans import aware


def replace_private(path, value):
    path=Path(path)
    if path.is_symlink():raise ValueError('Unsafe policy path')
    temporary=path.with_name(path.name+'.'+str(uuid.uuid4())+'.tmp')
    try:
        private_write(temporary,value)
        os.replace(temporary,path)
        if os.name!='nt':
            fd=os.open(str(path.parent),os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
    finally:
        if temporary.exists():temporary.unlink()


async def plan(db,vault,journal,until,now):
    owners={u.id:u for u in (await db.scalars(select(User).where(User.is_active.is_(True),User.deleted_at.is_(None)))).all()}
    wallets={w.id:w for w in (await db.scalars(select(Wallet).where(Wallet.archived_at.is_(None),Wallet.signing_capability=='custodial'))).all()}
    grants=[];rules=[];access=[]
    for grant in (await db.scalars(select(AutomaticGrant).where(AutomaticGrant.status=='enabled',AutomaticGrant.expires_at>now))).all():
        wallet=wallets.get(grant.wallet_id)
        if grant.user_id not in owners or not wallet or wallet.user_id!=grant.user_id:continue
        policy=vault.policy(grant)
        # Confirm that the encrypted key still exists; never decrypt or export it.
        key=json.loads(private_read(vault.root/(str(uuid.UUID(policy['key_id']))+'.keystore.json')))
        if str(key.get('address','')).removeprefix('0x').lower()!=grant.account.removeprefix('0x').lower():
            raise ValueError('Encrypted key identity differs')
        expiry=max(aware(grant.expires_at),until)
        new=copy.deepcopy(policy);new['expires_at']=int(expiry.timestamp())
        grants.append((grant,policy,new,expiry))
    by_id={g.id:expiry for g,_,_,expiry in grants}
    for rule in (await db.scalars(select(CopyRule).where(CopyRule.status=='active',CopyRule.expires_at>now))).all():
        if rule.grant_id not in by_id:continue
        pin=journal.execute('SELECT * FROM copy_rules WHERE id=?',(rule.id,)).fetchone()
        if (not pin or pin['intent']!=rule.context_hash or automatic.digest(rule.snapshot)!=rule.context_hash
                or automatic.digest(json.loads(pin['snapshot']))!=rule.context_hash):
            raise ValueError('Copy approval pin differs; maintenance aborted')
        expiry=min(by_id[rule.grant_id],max(aware(rule.expires_at),until))
        new=copy.deepcopy(rule.snapshot);new['expiry']=int(expiry.timestamp())
        rules.append((rule,copy.deepcopy(rule.snapshot),new,expiry))
    approved_wallets={g.wallet_id for g,_,_,_ in grants}
    for row in (await db.scalars(select(OpenSeaAccess).where(OpenSeaAccess.enabled.is_(True),
            OpenSeaAccess.status=='active',OpenSeaAccess.expires_at>now))).all():
        if row.wallet_id not in approved_wallets:continue
        wallet=wallets[row.wallet_id]
        old=opensea_identity.configuration(row,wallet)
        pin=journal.execute('SELECT * FROM opensea_identity WHERE wallet=?',(row.wallet_id,)).fetchone()
        if not pin or pin['blocked'] or pin['intent']!=automatic.digest(old) or json.loads(pin['configuration'])!=old:
            raise ValueError('Eligibility consent pin differs; maintenance aborted')
        new={**old,'revision':row.revision+1,'expires_at':int(max(aware(row.expires_at),until).timestamp())}
        access.append((row,old,new))
    return grants,rules,access,owners


async def extend(db,vault,journal,*,until,operation_id,reference,apply=False,now=None,failpoint=None):
    now=now or datetime.now(timezone.utc)
    until=aware(until).replace(microsecond=0)
    operation_id=str(uuid.UUID(operation_id))
    if not reference.strip() or not now<until<=now+timedelta(days=60,minutes=1):
        raise ValueError('An explicit operator reference and expiry within 60 days are required')
    await automatic.lock_execution(db)
    grants,rules,access,owners=await plan(db,vault,journal,until,now)
    affected={g.user_id for g,_,_,_ in grants}
    summary={'operation_id':operation_id,'expires_at':until.isoformat(),'signing_policies':len(grants),
        'active_copy_rules':len(rules),'opensea_consents':len(access),
        'users':sorted(owners[uid].username for uid in affected),'applied':False}
    if not apply:
        await db.rollback();return summary
    directory=vault.root/'maintenance'/operation_id
    if directory.exists():
        # Never silently extend a second time or resume an interrupted operation.
        raise ValueError('Operation already has a backup; inspect its manifest before retrying')
    directory.mkdir(mode=0o700,parents=True)
    snapshots={'operation_id':operation_id,'reference':reference,'status':'prepared','summary':summary,
        'grants':{g.id:{'expires_at':aware(g.expires_at).isoformat(),'context_hash':g.context_hash} for g,_,_,_ in grants},
        'rules':{r.id:{'expires_at':aware(r.expires_at).isoformat(),'context_hash':r.context_hash,'snapshot':old} for r,old,_,_ in rules},
        'access':{r.wallet_id:old for r,old,_ in access}}
    manifest=directory/'manifest.json'
    private_write(manifest,json.dumps(snapshots,sort_keys=True))
    for grant,old,_,_ in grants:
        private_write(directory/(grant.id+'.policy.json'),json.dumps(old,sort_keys=True))
    backup=directory/'journal.sqlite'
    fd=os.open(str(backup),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    with sqlite3.connect(backup) as dest:journal.backup(dest)
    journal.execute('BEGIN IMMEDIATE')
    committed=False
    try:
        for grant,old,new,expiry in grants:
            replace_private(vault.root/(grant.id+'.policy.json'),json.dumps(new,sort_keys=True))
            grant.expires_at=expiry;grant.context_hash=automatic.digest(new)
        if failpoint:failpoint('policies_written')
        for rule,_,new,expiry in rules:
            rule.expires_at=expiry;rule.snapshot=new;rule.context_hash=automatic.digest(new)
            journal.execute('UPDATE copy_rules SET intent=?,snapshot=? WHERE id=?',
                (rule.context_hash,json.dumps(new,sort_keys=True),rule.id))
        for row,old,new in access:
            pin=journal.execute('SELECT * FROM opensea_identity WHERE wallet=?',(row.wallet_id,)).fetchone()
            if pin['intent']!=automatic.digest(old):raise ValueError('Eligibility consent changed during maintenance')
            # Preserve encrypted token state, re-encrypting its associated-data
            # binding inside the isolated boundary. No wallet key is decrypted.
            state=opensea_identity.unseal(pin)
            intent=automatic.digest(new)
            sealed=opensea_identity.seal(state,{'intent':intent}) if state else None
            journal.execute('UPDATE opensea_identity SET revision=?,intent=?,configuration=?,state=? WHERE wallet=?',
                (new['revision'],intent,json.dumps(new,sort_keys=True),sealed,row.wallet_id))
            row.revision=new['revision'];row.expires_at=datetime.fromtimestamp(new['expires_at'],timezone.utc)
            # consented_at is deliberately unchanged: this is operator maintenance,
            # not a fabricated new acceptance by the wallet owner.
        for uid in affected:
            db.add(ActivityEvent(user_id=uid,event_type='permission_expiry_extended',
                label='Permission expiry extended by operator',icon_name='wallet',is_demo=False,
                detail=f'Expiry extended to {until.isoformat()}; limits, spending history and pause states unchanged. Reference: {reference}'))
        if failpoint:failpoint('before_commit')
        await db.commit();committed=True
        journal.commit()
        summary['applied']=True;snapshots['status']='applied';snapshots['summary']=summary
        replace_private(manifest,json.dumps(snapshots,sort_keys=True))
        return summary
    except Exception:
        journal.rollback()
        if not committed:
            for grant,old,_,_ in grants:
                replace_private(vault.root/(grant.id+'.policy.json'),json.dumps(old,sort_keys=True))
            await db.rollback()
            snapshots['status']='rolled_back'
        else:
            # Cross-store/power-loss failures cannot be made transactionally
            # atomic. Pins fail closed; the protected backup is the recovery source.
            snapshots['status']='recovery_required'
        replace_private(manifest,json.dumps(snapshots,sort_keys=True))
        raise


async def main(args):
    vault=CustodyVault()
    path=Path(settings.CUSTODY_JOURNAL_FILE)
    if path.is_symlink() or not path.is_file():raise ValueError('Existing signer journal required')
    journal=sqlite3.connect(f'file:{path}?mode=rw' if args.apply else f'file:{path}?mode=ro',uri=True)
    journal.row_factory=sqlite3.Row
    try:
        async with AsyncSessionLocal() as db:
            result=await extend(db,vault,journal,until=datetime.fromisoformat(args.until.replace('Z','+00:00')),
                operation_id=args.operation_id,reference=args.reference,apply=args.apply)
            print(json.dumps(result))
    finally:journal.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--until',required=True)
    parser.add_argument('--operation-id',required=True)
    parser.add_argument('--reference',required=True)
    parser.add_argument('--apply',action='store_true',help='Explicit operator authorization; default is dry run')
    asyncio.run(main(parser.parse_args()))
