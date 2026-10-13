"""Captured public lists and real owner-scoped cache/queue paths."""
import asyncio
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone, date
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker
from httpx import ASGITransport, AsyncClient
from app.models import User, Wallet, Drop, SourcePost, FeedWalletCheck, MintPlan, MintTask, MintPermission
from app.services.daily_list_parser import parse, daily_date, is_daily_list, network
from app.services import feed_checks, x_feed
from app.config import settings
from app.main import app
from app.api.deps import get_db

CAPTURED=json.loads((Path(__file__).parent/'fixtures/x-daily-lists-2026-10.json').read_text())

def test_provider_backoff_is_durable_and_session_not_logged(tmp_path):
    import sqlite3
    from app.services.twscrape_adapter import TwscrapeSourceAdapter
    path=tmp_path/'accounts.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE accounts(active INTEGER,locks TEXT)')
        db.execute('INSERT INTO accounts VALUES (1,?)',(json.dumps({'UserTweets':
            (datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat()}),))
    assert 895<TwscrapeSourceAdapter.provider_backoff(path)<=900

@pytest.mark.asyncio
async def test_adapter_accepts_only_original_target_daily_lists(monkeypatch):
    import sys
    from app.services.twscrape_adapter import TwscrapeSourceAdapter
    target=SimpleNamespace(id=123,username='lakzonevn')
    def tweet(pid,**kwargs):
        return SimpleNamespace(id=pid,user=target,rawContent=CAPTURED[0]['text'],links=[],
            date=datetime.now(timezone.utc),**kwargs)
    tweets=[tweet(1),tweet(2,inReplyToTweetId=1),tweet(3,retweetedTweet=True),tweet(4,isQuoteStatus=True)]
    tweets.append(SimpleNamespace(**{**vars(tweet(5)),'user':SimpleNamespace(id=456,username='other')}))
    tweets.append(SimpleNamespace(**{**vars(tweet(6)),'rawContent':'Some unrelated announcement'}))
    class API:
        def __init__(self,**kwargs):pass
        async def user_by_login(self,username):return target
        async def user_tweets(self,*args,**kwargs):
            for t in tweets:yield t
    monkeypatch.setitem(sys.modules,'twscrape',SimpleNamespace(API=API))
    rows=await TwscrapeSourceAdapter()._fetch('unused')
    assert [r['post_id'] for r in rows]==['1'] and rows[0]['raw_text']==CAPTURED[0]['text']

@pytest.mark.parametrize('index,count',[(0,8),(1,10),(2,7)])
def test_captured_real_lists(index,count):
    post=CAPTURED[index];rows=parse(post['text'],datetime.fromisoformat(post['posted_at']))
    assert is_daily_list(post['text']) and len(rows)==count
    assert all('Checker' not in r['name'] and 'Mint page' not in r['name'] for r in rows)
    assert daily_date(post['text'],datetime.fromisoformat(post['posted_at'])).day in (10,12,13)
    if index==0:
        assert rows[0]['stages']==[] and rows[-1]['stages']==[] and rows[5]['stages']==[]
        assert rows[1]['stages'][0]['start_time_utc'].hour==14
        assert rows[2]['chain_id']==0 and not rows[6]['mint_page_url']

@pytest.mark.parametrize('label,cid',[('HyperEVM',999),('APEchain',33139),('INK',57073),('Robinhood Chain',4663)])
def test_network_names(label,cid):assert network(label)[1]==cid

def test_explicit_date_year_and_wat_midnight():
    published=datetime(2026,12,31,23,30,tzinfo=timezone.utc)
    assert daily_date('Daily mint drops January 1st',published)==date(2027,1,1)
    assert daily_date('Daily mint drops December 31st',published)==date(2026,12,31)
    assert daily_date('Daily mint drops',published)==date(2027,1,1)
    row=parse('Daily mint drops January 1st\nCollection\nChain : Base\nTime : 12:30am WAT\nPrice : Free\nMint page : https://opensea.io/collection/test',published)[0]
    assert row['stages'][0]['start_time_utc']==datetime(2026,12,31,23,30,tzinfo=timezone.utc)
    assert not is_daily_list('Reply to daily mint drops\nNo collection here')

def stage(uid,eligibility='eligible',offset=0,remaining=2):
    now=datetime.now(timezone.utc)
    return dict(id=uid,name=uid,type='public_sale',eligibility=eligibility,remaining=remaining,
        wallet_total_limit=2,price_wei='0',starts_at=(now+timedelta(minutes=offset)).isoformat(),
        ends_at=(now+timedelta(hours=4)).isoformat(),timing='open')

def cached(stages,**kw):
    now=datetime.now(timezone.utc)
    return SimpleNamespace(status='complete',result={'stages':stages},checked_at=now,
        expires_at=kw.get('expires_at',now+timedelta(seconds=60)))

def test_recommend_open_then_upcoming_retain_rejected_whitelist():
    rows=[stage('gtd','not_eligible',-1),stage('public',offset=60),stage('later',offset=90)]
    result=feed_checks.presentation(cached(rows))
    assert result['recommended_stage']['id']=='public' and result['setup_enabled']
    assert result['stages'][0]['eligibility']=='not_eligible'
    rows.append(stage('open',offset=-2))
    assert feed_checks.presentation(cached(rows))['recommended_stage']['id']=='open'

@pytest.mark.parametrize('rows,status',[([stage('rejected','not_eligible')],'not_eligible'),
    ([stage('exhausted',remaining=0)],'not_eligible'),([stage('unknown','unverified')],'unverified')])
def test_exhaustion_missing_consent_unknown_are_distinct(rows,status):
    result=feed_checks.presentation(cached(rows));assert result['status']==status and not result['setup_enabled']

def test_stale_results_cannot_claim_ineligibility_or_enable_setup():
    result=feed_checks.presentation(cached([stage('bad','not_eligible')],expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
    assert result['status']=='unverified' and not result['setup_enabled']

async def fixtures(db,monkeypatch):
    monkeypatch.setattr(settings,'ENABLE_BASE_AUTOMATIC',True)
    users=(await db.scalars(select(User).order_by(User.username))).all()
    now=datetime.now(timezone.utc)
    wallets=[Wallet(id='w'+str(i),user_id=users[i//2].id,label='Wallet '+str(i),address='0x'+str(i+1)*40,
        is_default=i%2==0,is_demo=False) for i in range(4)]
    db.add_all(wallets);post=SourcePost(post_id='2109898502239105103',full_text='captured',posted_at=now,
        list_date=now.astimezone(x_feed.daily_date.__globals__['WAT']).date(),parser_version=1,author_username='lakzonevn')
    db.add(post);await db.flush()
    db.add(Drop(id='feed',source_post_id=post.id,name='Collection',chain='Base',chain_id=8453,
        mint_page_url='https://opensea.io/collection/test',is_demo=False))
    await db.commit();return users,wallets,await db.get(Drop,'feed')

@pytest.mark.asyncio
async def test_owned_queue_deduplicates_and_never_creates_plans(test_db,monkeypatch):
    users,wallets,drop=await fixtures(test_db,monkeypatch)
    factory=async_sessionmaker(test_db.bind,expire_on_commit=False)
    async def queue():
        async with factory() as db:await feed_checks.queue_checks(db,users[0],wallets[0],[drop])
    await asyncio.gather(queue(),queue())
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(FeedWalletCheck))==1
        for model in (MintPlan,MintTask,MintPermission):assert await db.scalar(select(func.count()).select_from(model))==0

@pytest.mark.asyncio
async def test_worker_progress_wallet_binding_and_provider_failure(test_db,monkeypatch):
    users,wallets,drop=await fixtures(test_db,monkeypatch)
    monkeypatch.setattr('app.services.feed_checks.OpenSeaClient.get_drop',AsyncMock(return_value={
        'chain':'base','contract_address':'0x'+'a'*40}))
    async def check(db,wallet,*args):
        return dict(wallet_id=wallet.id,address=wallet.address,stages=[stage('public',
            'eligible' if wallet.id=='w0' else 'not_eligible')]),[]
    monkeypatch.setattr('app.services.mint_stage_choice.wallet_stages',check)
    factory=async_sessionmaker(test_db.bind,expire_on_commit=False)
    for i in (0,2):await feed_checks.queue_checks(test_db,users[i//2],wallets[i],[drop])
    assert await feed_checks.step(factory) and await feed_checks.step(factory)
    for i,status in ((0,'eligible'),(2,'not_eligible')):
        row=await test_db.get(FeedWalletCheck,(users[i//2].id,wallets[i].id,drop.id),populate_existing=True)
        assert feed_checks.presentation(row)['status']==status and row.result['wallet_id']==wallets[i].id
    await feed_checks.queue_checks(test_db,users[0],wallets[1],[drop])
    from app.services.opensea import OpenSeaUnavailable
    monkeypatch.setattr('app.services.feed_checks.OpenSeaClient.get_drop',AsyncMock(side_effect=OpenSeaUnavailable('Provider down',retry_after_seconds=90)))
    assert await feed_checks.step(factory)
    row=await test_db.get(FeedWalletCheck,(users[0].id,wallets[1].id,drop.id),populate_existing=True)
    assert row.status=='queued' and feed_checks.presentation(row)['status']=='unverified'
    assert (row.next_attempt_at.replace(tzinfo=timezone.utc)-row.checked_at.replace(tzinfo=timezone.utc)).total_seconds()==90

@pytest.mark.asyncio
async def test_feed_owner_isolation_date_filters_and_bounded_queue(test_db,monkeypatch):
    users,wallets,drop=await fixtures(test_db,monkeypatch)
    async def dep():yield test_db
    app.dependency_overrides[get_db]=dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            login=await client.post('/api/auth/login',json={'username':'admin','password':'Admin test password 123'})
            client.headers['Authorization']='Bearer '+login.json()['token']
            feed=await client.get('/api/drops?daily_only=true')
            assert feed.status_code==200 and len(feed.json()['drops'])==1 and len(feed.json()['wallets'])==2
            assert feed.json()['drops'][0]['wallet_check']['status']=='unverified'
            assert (await client.get('/api/drops?daily_only=true&wallet_id=w2')).status_code==404
            assert (await client.post('/api/drops/wallet-checks',json={'wallet_id':'w2','drop_ids':['feed']})).status_code==404
            assert (await client.post('/api/drops/wallet-checks',json={'wallet_id':'w0','drop_ids':['feed']*21})).status_code==422
            assert (await client.post('/api/drops/wallet-checks',json={'wallet_id':'w0','drop_ids':['feed']})).status_code==202
            assert (await client.post('/api/drops/feed/prepare-plan',json={'wallet_id':'w0','stage_uuid':'public'})).status_code==409
            await client.get('/api/drops?daily_only=true&wallet_id=w1')
            assert (await client.get('/api/drops?daily_only=true')).json()['selected_wallet_id']=='w1'
            wallets[1].archived_at=datetime.now(timezone.utc);await test_db.commit()
            assert (await client.get('/api/drops?daily_only=true')).json()['selected_wallet_id']=='w0'
            post=await test_db.get(SourcePost,drop.source_post_id);post.list_date-=timedelta(days=1);await test_db.commit()
            assert (await client.get('/api/drops?daily_only=true')).json()['drops']==[]
    finally:app.dependency_overrides.pop(get_db,None)

@pytest.mark.asyncio
async def test_zero_drop_reprocessing_shortened_links_and_unsupported_records(test_db,monkeypatch):
    post=CAPTURED[0];when=datetime.fromisoformat(post['posted_at'])
    test_db.add(SourcePost(post_id=post['post_id'],full_text=post['text'],posted_at=when,parser_version=0))
    await test_db.commit()
    monkeypatch.setattr(x_feed,'validate_safe_url',lambda u:u)
    async def resolved(url):return 'https://opensea.io/collection/item-'+url.rsplit('/',1)[-1].lower()
    monkeypatch.setattr(x_feed,'resolve_safe_url',resolved)
    adapter=SimpleNamespace(fetch_posts=AsyncMock(return_value=[]))
    assert await x_feed.sync_x_drops(test_db,adapter)==7
    assert await x_feed.sync_x_drops(test_db,adapter)==0
    stored=await test_db.scalar(select(SourcePost))
    assert stored.full_text==post['text'] and stored.parser_version==1 and stored.list_date==date(2026,10,13)
    assert len((await test_db.scalars(select(Drop))).all())==7
    assert any(d.chain_id==0 for d in (await test_db.scalars(select(Drop))).all())
