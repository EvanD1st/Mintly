"""Expiry maintenance preserves independently enforced spending and ownership."""
import copy,json,uuid
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
from sqlalchemy import select,func
from app.config import settings
from app.models import User,Wallet,AutomaticGrant,CopyWatch,CopyRule,OpenSeaAccess,ActivityEvent
from app.services import automatic,opensea_identity
from app.services.custody import CustodyVault,private_write,private_read
from app.extend_custody_permissions import extend


@pytest.fixture
async def extension(test_db,tmp_path,monkeypatch):
    root=tmp_path/'vault';root.mkdir()
    password=tmp_path/'password';private_write(password,'disposable-test-password-'*3)
    monkeypatch.setattr(settings,'CUSTODY_VAULT_DIR',str(root))
    monkeypatch.setattr(settings,'CUSTODY_PASSWORD_FILE',str(password))
    monkeypatch.setattr(settings,'CUSTODY_JOURNAL_FILE',str(tmp_path/'journal.sqlite'))
    owner=await test_db.scalar(select(User).where(User.username=='member'))
    now=datetime.now(timezone.utc).replace(microsecond=0);old=now+timedelta(days=2)
    wallet=Wallet(id=str(uuid.uuid4()),user_id=owner.id,label='Receiving wallet',address='0x'+'1'*40,
        signing_capability='custodial',is_demo=False,is_default=True)
    test_db.add(wallet);await test_db.flush()
    grant_id=str(uuid.uuid4());key_id=str(uuid.uuid4())
    policy={'grant_id':grant_id,'key_id':key_id,'user_id':owner.id,'wallet_id':wallet.id,'account':wallet.address,
        'chain_id':1,'budget_wei':1000000,'max_task_wei':100000,'expires_at':int(old.timestamp()),
        'contracts':[],'mint_kinds':['public'],'collection_scope':'reviewed_mints'}
    private_write(root/(grant_id+'.policy.json'),json.dumps(policy))
    private_write(root/(key_id+'.keystore.json'),json.dumps({'address':wallet.address[2:],'crypto':{'ciphertext':'test-only'}}))
    grant=AutomaticGrant(id=grant_id,user_id=owner.id,wallet_id=wallet.id,chain_id=1,account=wallet.address,
        context_hash=automatic.digest(policy),scope={'max_task_wei':100000,'contracts':[],'mint_kinds':['public']},
        expires_at=old,status='enabled',budget_wei=1000000,spent_wei=123,reserved_wei=456)
    test_db.add(grant)
    watch=CopyWatch(id=str(uuid.uuid4()),user_id=owner.id,address='0x'+'2'*40,label='Watched wallet',chains=[1],cursors={})
    test_db.add(watch);await test_db.flush()
    snapshot={'user_id':owner.id,'wallet_id':wallet.id,'grant_id':grant.id,'chain_id':1,'expiry':int(old.timestamp()),
        'budget_wei':10000,'fee_cap_wei':1000,'quantity':1,'approved_at':int(now.timestamp())-100}
    rule=CopyRule(id=str(uuid.uuid4()),watch_id=watch.id,user_id=owner.id,grant_id=grant.id,chain_id=1,
        snapshot=snapshot,context_hash=automatic.digest(snapshot),status='active',expires_at=old,
        resume_after_block=100,budget_wei=10000,reserved_wei=456,spent_wei=123)
    test_db.add(rule)
    consent=OpenSeaAccess(wallet_id=wallet.id,user_id=owner.id,enabled=True,status='active',revision=3,
        expires_at=old,consented_at=now-timedelta(days=3),terms_version=opensea_identity.TERMS_VERSION)
    test_db.add(consent);await test_db.commit()
    vault=CustodyVault();journal=vault.journal();opensea_identity.tables(journal)
    journal.execute('INSERT INTO copy_rules VALUES (?,?,?)',(rule.id,rule.context_hash,json.dumps(snapshot)))
    config=opensea_identity.configuration(consent,wallet);intent=automatic.digest(config)
    state={'access_token':'disposable-not-a-real-token','pat_expires_at':int(old.timestamp())}
    encrypted=opensea_identity.seal(state,{'intent':intent})
    journal.execute('INSERT INTO opensea_identity VALUES (?,?,?,?,?,0)',(wallet.id,3,intent,json.dumps(config),encrypted))
    journal.commit()
    monkeypatch.setattr(vault,'account',lambda *_:pytest.fail('Maintenance must never decrypt a wallet key'))
    yield SimpleNamespace(db=test_db,vault=vault,journal=journal,now=now,until=now+timedelta(days=60),
        owner=owner,wallet=wallet,grant=grant,rule=rule,consent=consent,policy=policy,snapshot=copy.deepcopy(snapshot),state=state,old=old)
    journal.close()


async def run(x,**kwargs):
    return await extend(x.db,x.vault,x.journal,until=x.until,operation_id=str(uuid.uuid4()),
        reference='Explicit operator request, expiry-only maintenance',now=x.now,**kwargs)


async def test_dry_run_does_not_change_policies_approvals_or_credentials(extension):
    x=extension
    result=await run(x)
    assert result['signing_policies']==result['active_copy_rules']==result['opensea_consents']==1
    assert not result['applied'] and not (x.vault.root/'maintenance').exists()
    await x.db.refresh(x.grant);await x.db.refresh(x.consent)
    assert x.grant.expires_at.replace(tzinfo=timezone.utc)==x.old
    assert x.consent.revision==3
    assert x.vault.policy(x.grant)==x.policy


async def test_extension_preserves_limits_counters_approvals_and_token_state(extension):
    x=extension
    consent_time=x.consent.consented_at
    result=await run(x,apply=True)
    assert result['applied'] and result['users']==['member']
    assert x.grant.expires_at==x.until and x.rule.expires_at==x.until and x.consent.expires_at==x.until
    assert (x.grant.budget_wei,x.grant.spent_wei,x.grant.reserved_wei)==(1000000,123,456)
    assert (x.rule.budget_wei,x.rule.spent_wei,x.rule.reserved_wei)==(10000,123,456)
    assert x.rule.status=='active' and x.rule.resume_after_block==100
    assert {k:v for k,v in x.rule.snapshot.items() if k!='expiry'}=={k:v for k,v in x.snapshot.items() if k!='expiry'}
    assert {k:v for k,v in x.vault.policy(x.grant).items() if k!='expires_at'}=={k:v for k,v in x.policy.items() if k!='expires_at'}
    pin=x.journal.execute('SELECT * FROM copy_rules WHERE id=?',(x.rule.id,)).fetchone()
    assert pin['intent']==x.rule.context_hash==automatic.digest(x.rule.snapshot)
    pin=x.journal.execute('SELECT * FROM opensea_identity WHERE wallet=?',(x.wallet.id,)).fetchone()
    assert opensea_identity.unseal(pin)==x.state
    assert x.consent.consented_at==consent_time and x.consent.revision==4
    assert await x.db.scalar(select(func.count()).select_from(ActivityEvent).where(ActivityEvent.event_type=='permission_expiry_extended'))==1
    assert list((x.vault.root/'maintenance').glob('*/journal.sqlite'))


@pytest.mark.parametrize('state',['paused','expired','pin_mismatch','policy_mismatch'])
async def test_inactive_and_mismatched_rules_are_never_reactivated(extension,state):
    x=extension
    if state=='paused':x.rule.status='paused'
    elif state=='expired':x.rule.expires_at=x.now-timedelta(seconds=1)
    elif state=='pin_mismatch':x.rule.context_hash='bad'
    else:x.grant.context_hash='bad'
    await x.db.commit()
    if 'mismatch' in state:
        with pytest.raises(ValueError):await run(x,apply=True)
        await x.db.rollback()
        assert not (x.vault.root/'maintenance').exists()
    else:
        result=await run(x,apply=True)
        assert result['active_copy_rules']==0
        assert x.rule.status==('paused' if state=='paused' else 'active')
        assert x.rule.expires_at!=x.until


async def test_file_write_failure_restores_original_policy_and_rolls_back_db(extension):
    x=extension
    def fail(_):raise RuntimeError('Injected maintenance failure')
    with pytest.raises(RuntimeError):await run(x,apply=True,failpoint=fail)
    await x.db.refresh(x.grant);await x.db.refresh(x.rule);await x.db.refresh(x.consent)
    assert x.vault.policy(x.grant)==x.policy
    assert x.rule.snapshot==x.snapshot and x.consent.revision==3
    assert x.grant.expires_at.replace(tzinfo=timezone.utc)==x.old
    pin=x.journal.execute('SELECT * FROM copy_rules WHERE id=?',(x.rule.id,)).fetchone()
    assert pin['intent']==automatic.digest(x.snapshot)
