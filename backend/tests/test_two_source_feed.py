"""Two independent inboxes, one collection identity and durable per-list delivery."""
import asyncio,gzip,json
from datetime import datetime,timezone,timedelta
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.models import (User,Drop,SourcePost,SourceConnection,SourceRevision,FeedMention,
    FeedWalletCheck,NotificationDevice,MintTask,MintStage,SourceAlert)
from app.services import x_feed,feed_sources,feed_checks,daily_notices,source_archive,source_alerts
from app.api.drops import list_drops,seen_editions,SeenEditions
from app.services.daily_list_parser import parse,is_daily_list
from test_x_feed import FakeAdapter
from test_today_armed import armed_fixture


def item(pid,name='lakzonevn',slug='shared',title='Shared collection',compact=False):
    now=datetime.now(timezone.utc);header=now.astimezone(x_feed.daily_date.__globals__['WAT']).strftime('%B %d')
    text=(f'Mints today – {header}\n1. {title} @project\nhttps://opensea.io/collection/{slug}\n'
        '1,000 | Free\nGTD 13:00 | FCFS 14:00 | Public 15:00 UTC') if compact else (
        f'Daily mint drops {header}\n1. {title}\nChain: Base\nTime: 13:00 UTC\nPrice: Free\n'
        f'Link: https://opensea.io/collection/{slug}')
    return dict(post_id=str(pid),author_username=name,text=text,raw_text=text,posted_at=now)


@pytest.fixture
def source_providers(monkeypatch):
    monkeypatch.setattr(x_feed,'validate_safe_url',lambda url:url)
    monkeypatch.setattr(x_feed.OpenSeaClient,'get_drop',AsyncMock(return_value={
        'chain':'base','contract_address':'0x'+'a'*40}))


async def import_item(db,payload):
    await x_feed.ensure_source(db,'lakzonevn')
    await x_feed.ensure_source(db,payload['author_username'])
    await x_feed.save_raw(db,payload,payload['author_username'])
    post=await db.scalar(select(SourcePost).where(SourcePost.post_id==payload['post_id']))
    await x_feed.process_post(db,post.id)
    return post


def test_compact_list_dates_wat_and_no_invented_eligibility():
    text=('Mints today – October 31\n1. Collection @nft\nhttps://opensea.io/collection/test\n'
        '1,000 | Free / 0.001 ETH\nGTD 21:00 | Public 01:20 UTC (Nov 1)')
    assert is_daily_list(text)
    entry=parse(text,datetime(2026,10,31,tzinfo=timezone.utc))[0]
    assert entry['chain_id']==0 and entry['stages']==[]
    reports=entry['source_reported_stages']
    assert reports[0]['starts_at']=='2026-10-31T21:00:00+00:00'
    assert reports[1]['starts_at']=='2026-11-01T01:20:00+00:00'
    assert reports[1]['wat']=='01 Nov 02:20 WAT'
    assert not parse(text.replace(' UTC',''),datetime(2026,10,31,tzinfo=timezone.utc))[0]['source_reported_stages']


async def test_raw_post_survives_partial_fetch_failure_and_restarts(test_db,monkeypatch,source_providers):
    payload=item(1001)
    async def fail(self,name,on_post,**kwargs):
        await on_post(payload)
        raise x_feed.SourceUnavailable('Timeline interrupted')
    monkeypatch.setattr(x_feed.TwscrapeSourceAdapter,'fetch_posts',fail)
    assert await x_feed.sync_x_drops(test_db)==0
    assert await test_db.scalar(select(func.count()).select_from(SourceRevision))==1
    assert await x_feed.process_pending(test_db)==1
    source=await test_db.scalar(select(SourceConnection))
    assert source.status=='needs_attention' and source.next_attempt_at
    factory=async_sessionmaker(test_db.bind,expire_on_commit=False)
    async with factory() as db:
        assert await x_feed.sync_x_drops(db,FakeAdapter(error=RuntimeError()))==0
        post=await db.scalar(select(SourcePost))
        assert post.full_text==payload['text'] and post.processed_hash==post.content_hash


async def test_delayed_source_merges_duplicate_but_keeps_unique_collection(test_db,monkeypatch,source_providers):
    users,wallets,original,task,auth=await armed_fixture(test_db,monkeypatch)
    first=await import_item(test_db,item(1002,slug='test'))
    second_data=item(1003,'cassio_sch',slug='test',title='Different source spelling',compact=True)
    second_data['text']+='\n2. Unique collection @unique\nhttps://opensea.io/collection/unique\n1,000 | Free\nPublic 16:00 UTC'
    second_data['raw_text']=second_data['text']
    async def detail(slug):return {'chain':'base','contract_address':'0x'+('a' if slug=='test' else 'b')*40}
    monkeypatch.setattr(x_feed.OpenSeaClient,'get_drop',AsyncMock(side_effect=detail))
    await import_item(test_db,second_data)
    for value in [*users,*wallets,original,task,auth,first]:await test_db.refresh(value)
    result=await list_drops('all',users[0],test_db,wallet_id=wallets[0].id,daily_only=True)
    assert len(result.drops)==2
    card=next(c for c in result.drops if c.id==original.id)
    assert {s['author'].lower() for s in card.sources}=={'lakzonevn','cassio_sch'}
    assert card.automatic_mint['status']=='armed' and card.automatic_mint['stage_name']=='Approved GTD'
    assert (await test_db.get(MintStage,task.stage_id)).stage_name=='GTD'
    await feed_checks.queue_checks(test_db,users[0],wallets[0],[g['drop'] for g in await feed_sources.daily_collections(test_db,first.list_date)])
    assert await test_db.scalar(select(func.count()).select_from(FeedWalletCheck))==1
    task.status='confirmed';task.confirmed_at=datetime.now(timezone.utc);await test_db.commit()
    result=await list_drops('all',users[0],test_db,wallet_id=wallets[0].id,daily_only=True)
    assert next(c for c in result.drops if c.id==original.id).automatic_mint['status']=='confirmed'
    assert await test_db.scalar(select(func.count()).select_from(MintTask))==1


async def test_names_never_merge_distinct_collection_links(test_db,source_providers):
    await import_item(test_db,item(1010,slug='first',title='Same name'))
    await import_item(test_db,item(1011,'cassio_sch',slug='different',title='Same name'))
    day=datetime.now(timezone.utc).astimezone(x_feed.daily_date.__globals__['WAT']).date()
    assert len(await feed_sources.daily_collections(test_db,day))==2
    assert not feed_sources.same_collection(Drop(chain_id=1,contract_address=None,mint_page_url='https://opensea.io/collection/a'),
        Drop(chain_id=8453,contract_address=None,mint_page_url='https://opensea.io/collection/a'))


async def test_read_state_is_owner_scoped_and_old_ack_cannot_hide_revision(test_db,source_providers):
    post=await import_item(test_db,item(1020))
    users=(await test_db.scalars(select(User).order_by(User.username))).all()
    groups=await feed_sources.daily_collections(test_db,post.list_date)
    meta,_=await feed_sources.source_metadata(test_db,groups,users[0].id)
    assert next(iter(meta.values()))['additions']=='new'
    old=SeenEditions(editions=[{'id':post.id,'content_hash':post.content_hash}])
    await seen_editions(old,users[0],test_db)
    meta,_=await feed_sources.source_metadata(test_db,groups,users[0].id)
    assert next(iter(meta.values()))['additions'] is None
    meta,_=await feed_sources.source_metadata(test_db,groups,users[1].id)
    assert next(iter(meta.values()))['additions']=='new'
    changed=item(1020);changed['text']=changed['text'].replace('13:00','14:00');changed['raw_text']=changed['text']
    await import_item(test_db,changed)
    await seen_editions(old,users[0],test_db)
    groups=await feed_sources.daily_collections(test_db,post.list_date)
    meta,_=await feed_sources.source_metadata(test_db,groups,users[0].id)
    assert next(iter(meta.values()))['additions']=='updated'
    assert await test_db.scalar(select(func.count()).select_from(SourceRevision))==2


async def test_second_duplicate_list_alert_once_with_ordered_retries(test_db,source_providers):
    user=await test_db.scalar(select(User).where(User.username=='member'))
    test_db.add(NotificationDevice(user_id=user.id,device_token='two-source-test',is_active=True,preferences={'daily_list':True}))
    await test_db.commit()
    first=await import_item(test_db,item(1030));second=await import_item(test_db,item(1031,'cassio_sch'))
    assert first.list_sequence==1 and second.list_sequence==2
    factory=async_sessionmaker(test_db.bind,expire_on_commit=False);now=datetime.now(timezone.utc)
    assert await daily_notices.poll(factory,now=now)==2
    assert await daily_notices.poll(factory,now=now)==0
    failure=AsyncMock(return_value=False)
    assert await daily_notices.deliver(factory,failure,now=now)
    success=AsyncMock(return_value=True)
    assert not await daily_notices.deliver(factory,success,now=now+timedelta(seconds=1))
    assert await daily_notices.deliver(factory,success,now=now+timedelta(seconds=61))
    assert await daily_notices.deliver(factory,success,now=now+timedelta(seconds=62))
    assert [c.args[0] for c in success.await_args_list]==["Today's mint list is ready",'Second list just dropped']
    assert 'already on Today' in success.await_args_list[1].args[1]
    await import_item(test_db,item(1031,'cassio_sch',title='Updated spelling'))
    assert await daily_notices.poll(factory,now=now+timedelta(seconds=63))==0


async def test_source_archives_only_public_inbox_and_alerts_use_delivery_queue(test_db,source_providers,tmp_path):
    post=await import_item(test_db,item(1040));factory=async_sessionmaker(test_db.bind,expire_on_commit=False)
    archive=await source_archive.snapshot(factory,directory=tmp_path)
    with gzip.open(archive,'rt',encoding='utf-8') as content:rows=[json.loads(line) for line in content]
    assert rows[0]['post_id']==post.post_id and rows[0]['raw_text']==post.full_text
    assert not {'password_hash','device_token','user_id','snapshot'}&set(rows[0])
    await source_alerts.enqueue(test_db,'test-source','Source refresh delayed')
    await source_alerts.enqueue(test_db,'test-source','Source refresh delayed')
    assert await test_db.scalar(select(func.count()).select_from(SourceAlert))==1
    notify=AsyncMock(return_value=True)
    assert await source_alerts.deliver(factory,notify)
    assert notify.await_args.kwargs['category']=='source_health'


async def test_postgres_concurrent_sources_share_one_canonical_card(test_db,source_providers):
    if test_db.bind.dialect.name!='postgresql':pytest.skip('Requires PostgreSQL source publication locks')
    await x_feed.ensure_source(test_db,'lakzonevn');await x_feed.ensure_source(test_db,'cassio_sch')
    factory=async_sessionmaker(test_db.bind,expire_on_commit=False)
    async def publish(payload):
        async with factory() as db:await import_item(db,payload)
    await asyncio.gather(publish(item(1050)),publish(item(1051,'cassio_sch')))
    assert await test_db.scalar(select(func.count()).select_from(Drop))==1
    assert await test_db.scalar(select(func.count()).select_from(FeedMention))==2

async def test_cursor_is_checkpointed_after_saved_page_and_latest_is_checked_on_resume(test_db,monkeypatch):
    import sys
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules,'twscrape.models',SimpleNamespace(parse_tweets=lambda value:value['tweets']))
    now=datetime.now(timezone.utc);owner=SimpleNamespace(id=1,username='lakzonevn')
    def tweet(pid,date):
        return SimpleNamespace(id=pid,user=owner,date=date,rawContent='Public source post',links=[],
            retweetedTweet=None,inReplyToTweetId=None,isQuoteStatus=False)
    checkpoints=[];saved=[]
    async def save(value):saved.append(value['post_id'])
    async def checkpoint(cursor,boundary):checkpoints.append(cursor)
    class Broken:
        async def user_tweets_raw(self,uid,limit,kv):
            yield SimpleNamespace(json=lambda:{'tweets':[tweet(2001,now)],'cursor':{'cursorType':'Bottom','value':'page-two'}})
            raise TimeoutError('Next page interrupted')
    adapter=x_feed.TwscrapeSourceAdapter()
    with pytest.raises(TimeoutError):
        await adapter._pages(Broken(),owner,'lakzonevn',save,None,now-timedelta(days=1),checkpoint)
    assert saved==['2001'] and checkpoints==['page-two']
    class Resumed:
        async def user_tweets_raw(self,uid,limit,kv):
            if not kv:
                yield SimpleNamespace(json=lambda:{'tweets':[tweet(2002,now)],'cursor':{'cursorType':'Bottom','value':'new-top'}})
            else:
                assert kv=={'cursor':'page-two'}
                yield SimpleNamespace(json=lambda:{'tweets':[tweet(1999,now-timedelta(days=2))]})
    await adapter._pages(Resumed(),owner,'lakzonevn',save,'page-two',now-timedelta(days=1),checkpoint)
    assert saved==['2001','2002','1999'] and checkpoints[-1] is None


def test_real_cassio_list_retains_all_eight_collections_and_wat_stages():
    from pathlib import Path
    payload=json.loads((Path(__file__).parent/'fixtures/cassio-daily-list-2026-11-01.json').read_text(encoding='utf-8'))
    assert is_daily_list(payload['text'])
    rows=parse(payload['text'],datetime.fromisoformat(payload['posted_at']))
    assert len(rows)==8
    caravan=next(r for r in rows if r['name']=='Caravan RH')
    assert caravan['mint_page_url']=='https://opensea.io/collection/caravan-rh-421722141'
    assert caravan['source_reported_stages'][0]['wat']=='01 Nov 12:00 WAT'
    assert caravan['stages']==[] and all(r['chain_id']==0 for r in rows)


async def test_midnight_wat_visibility_does_not_reannounce_previous_list(test_db,source_providers):
    from datetime import date
    late=item(1060,slug='late')
    late['text']='Daily mint drops October 31\nLate collection\nChain: Base\nTime: 23:30 UTC\nPrice: Free\nLink: https://opensea.io/collection/late'
    late['raw_text']=late['text'];late['posted_at']=datetime(2026,10,31,23,10,tzinfo=timezone.utc)
    post=await import_item(test_db,late)
    assert post.list_date==date(2026,11,1)
    early=item(1061,slug='carry')
    early['text']=late['text'].replace('Late collection','Earlier list collection').replace('/late','/carry')
    early['raw_text']=early['text'];early['posted_at']=datetime(2026,10,31,9,tzinfo=timezone.utc)
    old=await import_item(test_db,early)
    assert old.list_date==date(2026,10,31)
    clock=datetime(2026,10,31,23,30,tzinfo=timezone.utc)
    assert len(await feed_sources.daily_collections(test_db,date(2026,11,1),now=clock))==2
    assert [p.id for p in await daily_notices.available(test_db,date(2026,11,1))]==[post.id]
    groups=await feed_sources.daily_collections(test_db,date(2026,11,1),now=clock)
    metadata,_=await feed_sources.source_metadata(test_db,groups,'viewer',date(2026,11,1))
    by_name={g['drop'].name:metadata[g['drop'].id] for g in groups}
    assert by_name['Earlier list collection']['list_context']=='From yesterday’s list'
    assert by_name['Late collection']['list_context'] is None
    assert all(m['today_schedule']=='Source listing 00:30 WAT' for m in by_name.values())
    assert not await feed_sources.daily_collections(test_db,date(2026,11,2))


async def test_expiry_uses_postponed_private_task_without_cancelling_it(test_db,source_providers,monkeypatch):
    users,wallets,drop,task,auth=await armed_fixture(test_db,monkeypatch)
    post=await import_item(test_db,item(1062,slug='test'))
    now=datetime.now(timezone.utc)
    day=now.astimezone(x_feed.daily_date.__globals__['WAT']).date()
    post.list_date=day-timedelta(days=1)
    original_post=await test_db.get(SourcePost,drop.source_post_id)
    original_post.list_date=post.list_date
    mention=await test_db.scalar(select(FeedMention).where(FeedMention.post_id==post.id))
    mention.details={'stages':[{'starts_at':(now-timedelta(hours=2)).isoformat()}]}
    task.schedule_checked_at=now;task.scheduled_for_utc=now+timedelta(hours=1)
    await test_db.commit()
    groups=await feed_sources.daily_collections(test_db,day,now=now)
    assert any(g['drop'].id==drop.id for g in groups)
    assert not await feed_sources.daily_collections(test_db,day,now=now+timedelta(hours=2))
    await test_db.refresh(task)
    assert task.status=='armed' and task.authorization_id==auth.id
