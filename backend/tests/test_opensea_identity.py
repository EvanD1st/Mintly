"""Real custody key -> fixed off-chain login -> encrypted read-only identity -> stage data."""
import json,uuid,time
from pathlib import Path
from datetime import datetime,timezone
from eth_account import Account
from eth_account.messages import encode_defunct
from sqlalchemy import select,func
import pytest
from fastapi import HTTPException
from app.config import settings
from app.models import Wallet,OpenSeaAccess,MintTask,AutomaticNonce,MintPlan,AutomaticGrant,User
from app.services import opensea_identity as identity,automatic
from app.services.custody import CustodyVault
from test_automatic_evm import lab,plan_context


@pytest.fixture
async def auth_lab(lab,monkeypatch):
    calls=[];faults={};counter=0
    class Transport:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def request(self,method,path,*,body=None,headers=None):
            nonlocal counter
            calls.append((method,path,body,headers))
            if path in faults:raise identity.IdentityUnavailable(faults[path])
            if path.endswith('/siwe/nonce'):
                counter+=1;return {'nonce':str(counter).zfill(12)},{}
            if path.endswith('/siwe/verify'):
                m=body['message']
                assert m['domain']=='opensea.io' and m['uri']=='https://opensea.io'
                assert m['accountType']=='Ethereum' and m['chainId']=='1'
                assert set(m)=={'domain','address','statement','uri','version','chainId','nonce','issuedAt','accountType'}
                text=f"opensea.io wants you to sign in with your Ethereum account:\n{m['address']}\n\n{m['statement']}\n\nURI: https://opensea.io\nVersion: 1\nChain ID: 1\nNonce: {m['nonce']}\nIssued At: {m['issuedAt']}"
                assert Account.recover_message(encode_defunct(text=text),signature=body['signature']).lower()==lab.owner.address.lower()
                return {},{'access_token':'cookie-access-disposable-123456','refresh_token':'cookie-refresh-disposable-123456'}
            if path=='/api/v2/auth/tokens':
                assert body['scopes']==['read:eligibility'] and 1<=body['expiresInDays']<=7
                return {'id':'test-pat','token':'pat-disposable-secret-123456','scopes':['read:eligibility']},{}
            if path.endswith('/tokens/exchange'):
                assert body=={'subjectToken':'pat-disposable-secret-123456','subjectTokenType':'ACCESS_TOKEN'}
                assert not headers  # Session cookies never accompany the scoped token exchange.
                return {'accessToken':'jwt-disposable-secret-123456','expiresIn':3600,'tokenScopes':['read:eligibility']},{}
            if path.endswith('/session/refresh'):
                return {},{'access_token':'cookie-rotated-disposable-123456','refresh_token':'cookie-refresh-disposable-123456'}
            if method=='DELETE':return {},{}
            if path.endswith('/eligibility'):
                assert headers['Authorization']=='Bearer jwt-disposable-secret-123456'
                assert 'Cookie' not in headers
                return {'wallet_address':lab.owner.address,'stages':[{'stage_uuid':'gtd','is_eligible':True,
                    'price':'5','max_total_mintable_by_wallet':'7'}],'accessToken':'must-not-leak'},{}
            raise AssertionError(path)
    monkeypatch.setattr(identity,'Transport',Transport)
    async def broker(wallet_id,operation,*,slug=None,key=None):
        path=f'/opensea/{wallet_id}/'+('register' if operation=='register' else 'stages/'+slug)
        response=await lab.signer_client.post(path,json={'api_key':key or 'api-key-disposable-1234'} if operation!='register' else None)
        if response.status_code!=200:raise HTTPException(response.status_code,'Broker unavailable')
        return response.json()
    monkeypatch.setattr('app.api.opensea_access.broker',broker)
    return lab,calls,faults


async def enable(lab):
    r=await lab.client.post(f'/api/wallets/{lab.wallet.id}/opensea-access',json={'enabled':True,'consent':True,'terms_accepted':True})
    assert r.status_code==200,r.text
    assert r.json()['status']=='active'
    return r


async def test_explicit_consent_signs_only_login_and_never_creates_mint_or_nonce(auth_lab):
    lab,calls,_=auth_lab
    denied=await lab.client.post(f'/api/wallets/{lab.wallet.id}/opensea-access',json={'enabled':True})
    assert denied.status_code==422 and calls==[]
    result=await enable(lab)
    assert result.json()['scopes']==['read:eligibility']
    for sensitive in ('pat-disposable','jwt-disposable','cookie-access','signature'):assert sensitive not in result.text
    async with lab.factory() as db:
        assert await db.scalar(select(func.count()).select_from(MintTask))==0
        assert await db.scalar(select(func.count()).select_from(AutomaticNonce))==0
    journal=CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0]==0
    pin=journal.execute('SELECT * FROM opensea_identity').fetchone()
    assert pin['state'] and b'pat-disposable' not in pin['state']
    journal.close()
    assert b'pat-disposable' not in Path(settings.CUSTODY_JOURNAL_FILE).read_bytes()


async def test_cached_lookup_refreshes_without_resigning_and_filters_credentials(auth_lab):
    lab,calls,_=auth_lab;await enable(lab)
    async with lab.factory() as db:
        data=await identity.connection(db,lab.wallet.id,'stages',slug='example',key='api-disposable-key-1234')
        assert data['stages'][0]['max_total_mintable_by_wallet']==7
        assert 'accessToken' not in data
    journal=CustodyVault().journal();pin=journal.execute('SELECT * FROM opensea_identity').fetchone()
    state=identity.unseal(pin);state['expires_at']=0
    journal.execute('UPDATE opensea_identity SET state=?',(identity.seal(state,pin),));journal.commit();journal.close()
    async with lab.factory() as db:await identity.connection(db,lab.wallet.id,'stages',slug='example',key='api-disposable-key-1234')
    assert len([c for c in calls if c[1].endswith('/siwe/verify')])==1
    assert len([c for c in calls if c[1].endswith('/tokens/exchange')])==2


async def test_foreign_user_and_address_only_wallet_cannot_authenticate(auth_lab):
    lab,calls,_=auth_lab
    token=(await lab.client.post('/api/auth/login',json={'username':'admin','password':'Admin test password 123'})).json()['token']
    r=await lab.client.post(f'/api/wallets/{lab.wallet.id}/opensea-access',headers={'Authorization':'Bearer '+token},
        json={'enabled':True,'consent':True,'terms_accepted':True})
    assert r.status_code==404
    watch=(await lab.client.post('/api/wallets/watch',json={'address':lab.w.eth.accounts[5],'label':'Read only'})).json()
    r=await lab.client.post('/api/wallets/'+watch['id']+'/opensea-access',json={'enabled':True,'consent':True,'terms_accepted':True})
    assert r.status_code==409 and calls==[]


async def test_pending_connection_retry_keeps_the_same_consent_revision(auth_lab):
    lab,calls,faults=auth_lab
    faults['/api/v2/auth/siwe/nonce']=503
    body={'enabled':True,'consent':True,'terms_accepted':True}
    first=await lab.client.post(f'/api/wallets/{lab.wallet.id}/opensea-access',json=body)
    assert first.status_code==503
    async with lab.factory() as db:
        row=await db.get(OpenSeaAccess,lab.wallet.id);revision=row.revision;expiry=row.expires_at
    faults.clear();await enable(lab)
    async with lab.factory() as db:
        row=await db.get(OpenSeaAccess,lab.wallet.id);assert row.revision==revision and row.expires_at==expiry


async def test_revoked_exchange_requires_new_consent_not_another_login_signature(auth_lab):
    lab,calls,faults=auth_lab;await enable(lab)
    journal=CustodyVault().journal();pin=journal.execute('SELECT * FROM opensea_identity').fetchone()
    state=identity.unseal(pin);state['expires_at']=0
    journal.execute('UPDATE opensea_identity SET state=?',(identity.seal(state,pin),));journal.commit();journal.close()
    faults['/api/v2/auth/tokens/exchange']=403
    async with lab.factory() as db:
        with pytest.raises(identity.IdentityUnavailable):await identity.connection(db,lab.wallet.id,'stages',slug='example',key='api-disposable-key-1234')
    faults.clear()
    async with lab.factory() as db:
        with pytest.raises(ValueError):await identity.connection(db,lab.wallet.id,'stages',slug='example',key='api-disposable-key-1234')
    assert len([c for c in calls if c[1].endswith('/siwe/verify')])==1


async def test_unlink_disables_and_revokes_without_touching_mint_history(auth_lab):
    lab,calls,_=auth_lab;await enable(lab)
    r=await lab.client.delete('/api/wallets/'+lab.wallet.id)
    assert r.status_code==200
    async with lab.factory() as db:assert not (await db.get(OpenSeaAccess,lab.wallet.id)).enabled
    journal=CustodyVault().journal();pin=journal.execute('SELECT * FROM opensea_identity').fetchone()
    assert pin['state'] is None
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0]==0
    journal.close();assert any(c[0]=='DELETE' for c in calls)


@pytest.mark.parametrize('fault',['owner','scope','expiry','cipher'])
async def test_api_database_or_cipher_tampering_cannot_expand_authentication(auth_lab,fault):
    lab,calls,_=auth_lab;await enable(lab)
    if fault=='cipher':
        journal=CustodyVault().journal();journal.execute("UPDATE opensea_identity SET state=x'0000'");journal.commit();journal.close()
    else:
        async with lab.factory() as db:
            row=await db.get(OpenSeaAccess,lab.wallet.id)
            if fault=='owner':row.user_id=await db.scalar(select(User.id).where(User.username=='admin'))
            elif fault=='scope':row.terms_version='other-terms'
            else:row.expires_at=datetime.fromtimestamp(1,timezone.utc)
            await db.commit()
    before=len(calls)
    async with lab.factory() as db:
        with pytest.raises(Exception):await identity.connection(db,lab.wallet.id,'stages',slug='example',key='api-disposable-key-1234')
    assert not any(c[1].endswith('/siwe/verify') for c in calls[before:])


def test_unknown_eligibility_is_not_invented_and_foreign_address_is_rejected():
    address='0x'+'11'*20
    assert identity.normalize({'stages':[{'stage_uuid':'x','is_eligible':'true','max_total_mintable_by_wallet':'unknown'}]},address)['stages'][0]['eligible'] is None
    with pytest.raises(identity.IdentityUnavailable):identity.normalize({'address':'0x'+'22'*20,'stages':[]},address)


async def test_phase_selection_pins_the_phase_and_tracks_actual_remaining_allowance(auth_lab,monkeypatch):
    lab,_,_=auth_lab
    plan,_=await plan_context(lab,monkeypatch)
    result=await lab.client.get('/api/mint-plans/'+plan['id']+'/stages')
    assert result.status_code==200,result.text
    item=result.json()['stages'][0]
    assert item['eligibility']=='eligible' and item['remaining']==20
    selected=await lab.client.post('/api/mint-plans/'+plan['id']+'/stage',json={'stage_uuid':item['id'],'quantity':3})
    assert selected.status_code==200,selected.text
    assert selected.json()['selected_stage_uuid']==item['id']
    async with lab.factory() as db:
        saved=await db.get(MintPlan,plan['id']);assert saved.selected_stage['uuid']==item['id'] and saved.quantity==3
        assert await db.scalar(select(func.count()).select_from(MintTask))==0


async def test_compact_schedule_uuid_matches_hyphenated_eligibility_uuid(auth_lab,monkeypatch):
    lab,_,_=auth_lab
    plan,_=await plan_context(lab,monkeypatch)
    await enable(lab)
    from app.services.opensea import OpenSeaClient
    uid='3130702aa76547c595b50fc33fcf35c1'
    async def detail(self,slug):
        return {'chain':'local-test','contract_address':lab.nft.address,'stages':[
            {'uuid':uid,'stage_type':'signed_presale','label':'GTD','start_time':datetime.fromtimestamp(lab.start,timezone.utc).isoformat(),
                'end_time':datetime.fromtimestamp(lab.end,timezone.utc).isoformat(),'price':'0','max_per_wallet':'1','price_currency_address':'0x'+'0'*40}]}
    async def key(self):return 'api-key-disposable-1234'
    async def result(*args,**kwargs):
        return {'address':lab.owner.address,'stages':[{'stage_uuid':str(uuid.UUID(uid)),'eligible':True,
            'max_total_mintable_by_wallet':1,'remaining':None,'price_wei':0}]}
    monkeypatch.setattr(OpenSeaClient,'get_drop',detail)
    monkeypatch.setattr(OpenSeaClient,'_key',key)
    monkeypatch.setattr('app.api.opensea_access.broker',result)
    response=await lab.client.get('/api/mint-plans/'+plan['id']+'/stages')
    assert response.status_code==200,response.text
    stage=response.json()['stages'][0]
    assert stage['id']==uid and stage['eligibility']=='eligible'
    assert stage['wallet_total_limit']==1 and stage['remaining']==1


def test_stage_uuid_matching_preserves_non_uuid_ids_and_distinct_phases():
    from app.services.mint_stage_choice import stage_key
    assert stage_key('3130702a-a765-47c5-95b5-0fc33fcf35c1')==stage_key('3130702aa76547c595b50fc33fcf35c1')
    assert stage_key('legacy-public')=='legacy-public'
    assert stage_key('3130702aa76547c595b50fc33fcf35c1')!=stage_key('39a3ea976e6d4ee8adcadda82243ef78')
