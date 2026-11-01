"""Durable source inbox; discovery never edits private mint approvals."""
import asyncio, hashlib, re, uuid, time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, urlunsplit
from sqlalchemy import select, or_, func, delete
from app.models import Drop, MintStage, SourceConnection, SourcePost, SourceRevision, FeedMention
from app.services.parser import DropPostParser
from app.services.twikit_adapter import SourceUnavailable
from app.services.twscrape_adapter import TwscrapeSourceAdapter
from app.services.url_validator import URLSecurityError, validate_safe_url, resolve_safe_url
from app.services.daily_list_parser import VERSION,daily_date,is_daily_list
from app.services.opensea import collection_slug,OpenSeaUnavailable,OpenSeaClient,CHAINS
from app.services.feed_sources import SOURCE_NAMES,discovery_lock,canonical_drop
from app.services.mint_plans import aware
from zoneinfo import ZoneInfo


def insert_for(db):
    from sqlalchemy.dialects.postgresql import insert as pg
    from sqlalchemy.dialects.sqlite import insert as sqlite
    return pg if db.bind.dialect.name=='postgresql' else sqlite


async def ensure_source(db,name):
    now=datetime.now(timezone.utc)
    await db.execute(insert_for(db)(SourceConnection).values(source_name=name,source_type='twscrape',
        status='needs_attention',is_monitoring=True,consecutive_failures=0,created_at=now,updated_at=now)
        .on_conflict_do_nothing(index_elements=['source_name']))
    await db.commit()
    return await db.scalar(select(SourceConnection).where(SourceConnection.source_name==name))


async def save_raw(db,item,name):
    if item.get('author_username',name).lower()!=name or not re.fullmatch(r'\d{1,30}',str(item.get('post_id',''))):return
    date=item.get('posted_at');expanded=item.get('text','');raw=item.get('raw_text',expanded)
    if not isinstance(date,datetime) or date.tzinfo is None or not isinstance(raw,str) or not isinstance(expanded,str) or max(len(raw),len(expanded))>100000:return
    digest=hashlib.sha256((raw+'\n'+expanded).encode()).hexdigest();now=datetime.now(timezone.utc)
    await db.execute(insert_for(db)(SourcePost).values(post_id=item['post_id'],author_username=name,
        full_text=raw,expanded_text=expanded,content_hash=digest,posted_at=date,
        extracted_urls=[],is_daily_list=False,is_manual_import=False,parser_version=0,created_at=now,updated_at=now)
        .on_conflict_do_nothing(index_elements=['post_id']))
    post=await db.scalar(select(SourcePost).where(SourcePost.post_id==item['post_id']).with_for_update())
    if post.author_username.lower()!=name or post.is_manual_import:
        await db.rollback();return
    await db.execute(insert_for(db)(SourceRevision).values(post_id=post.id,content_hash=digest,
        raw_text=raw,expanded_text=expanded,created_at=now,updated_at=now)
        .on_conflict_do_nothing(index_elements=['post_id','content_hash']))
    if post.content_hash!=digest:
        post.full_text,post.expanded_text,post.content_hash=raw,expanded,digest
        post.next_process_at=None
    await db.commit()


async def process_post(db,pid):
    post=await db.get(SourcePost,pid);now=datetime.now(timezone.utc)
    if not post.content_hash:
        post.expanded_text=post.expanded_text or post.full_text
        post.content_hash=hashlib.sha256((post.full_text+'\n'+post.expanded_text).encode()).hexdigest()
        db.add(SourceRevision(post_id=post.id,content_hash=post.content_hash,raw_text=post.full_text,expanded_text=post.expanded_text))
        await db.commit()
    text=post.expanded_text or post.full_text;digest=post.content_hash
    if not is_daily_list(text):
        post.processed_hash=digest;post.parser_version=VERSION
        await db.commit();return 0
    day=daily_date(text,aware(post.posted_at))
    if day is None:raise ValueError('The list date is not valid.')
    parsed=DropPostParser.parse(text,aware(post.posted_at));safe=[];unresolved=False
    await db.commit()
    metadata_deadline=time.monotonic()+15
    for data in parsed:
        url=data['mint_page_url']
        if not url.startswith('https://') or urlsplit(url).hostname in ('x.com','twitter.com'):continue
        try:
            if urlsplit(url).hostname=='t.co':url=await resolve_safe_url(url)
            parts=urlsplit(url)
            if parts.hostname=='opensea.io':
                url=urlunsplit((parts.scheme,parts.netloc,parts.path,'',''))
                url='https://opensea.io/collection/'+collection_slug(url)
            url=validate_safe_url(url)
        except (URLSecurityError,OpenSeaUnavailable):continue
        except Exception:unresolved=True;continue
        data['mint_page_url']=url
        if not data['chain_id'] and data.get('needs_network_lookup') and parts.hostname=='opensea.io':
            try:
                from app.services.feed_sources import approved
                known=await db.scalar(select(Drop).join(SourcePost,Drop.source_post_id==SourcePost.id).where(approved(),Drop.mint_page_url==url,Drop.chain_id>0,
                    Drop.contract_address.is_not(None),Drop.source_post_id.is_not(None),Drop.canonical_id.is_(None)).limit(1))
                cached=(known.chain_id,known.chain,known.contract_address) if known else None
                await db.rollback()  # Return the DB connection before any upstream wait.
                if cached:
                    data['chain_id'],data['chain'],data['contract_address']=cached
                else:
                    remaining=metadata_deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError('Metadata budget exhausted')
                    async with asyncio.timeout(min(12,remaining)):detail=await OpenSeaClient().get_drop(collection_slug(url))
                    data['chain_id'],data['chain']=CHAINS[detail['chain']]
                    data['contract_address']=detail['contract_address']
            except Exception:unresolved=True
        safe.append(data)
    if not safe:raise ValueError('No usable collection entries were parsed; saved entries are retained.')
    await db.rollback()
    await discovery_lock(db)
    post=await db.get(SourcePost,pid,populate_existing=True)
    if post.content_hash!=digest:
        await db.rollback();return 0
    source=await db.scalar(select(SourceConnection).where(SourceConnection.source_name==post.author_username))
    if source and not source.is_monitoring and not post.is_manual_import:
        await db.rollback();return 0
    count=0;entries=[]
    posted_day=aware(post.posted_at).astimezone(ZoneInfo('Africa/Lagos')).date()
    report_days={datetime.fromisoformat(s['starts_at']).astimezone(ZoneInfo('Africa/Lagos')).date()
        for d in safe for s in d.get('source_reported_stages',[])}
    if posted_day==day+timedelta(days=1) and posted_day in report_days:day=posted_day
    for data in safe:
        key=data.get('source_entry_key') or hashlib.sha256(data['mint_page_url'].encode()).hexdigest()
        prior=await db.get(FeedMention,(post.id,key))
        candidate=Drop(id='x_'+uuid.uuid4().hex[:12],source_post_id=post.id,
            source_entry_key=key,name=data['name'][:150],chain=data['chain'],chain_id=data['chain_id'],
            contract_address=data.get('contract_address'),mint_page_url=data['mint_page_url'],site_label=data['site_label'],
            icon_name='gem',status_label='Manual check',status_kind='manual',is_supported_integration=False,
            is_demo=False,source_price_text=data.get('source_price_text'),source_time_text=data.get('source_time_text'),
            manual_notice=f"Posted by @{post.author_username}. Mint terms require verification.")
        chosen=await canonical_drop(db,candidate)
        if chosen is candidate:
            old=await db.scalar(select(Drop).where(Drop.source_post_id==post.id,Drop.source_entry_key==key))
            chosen=old or candidate
            if not old:
                db.add(chosen);await db.flush();count+=1
                for index,stage in enumerate(data['stages']):db.add(MintStage(id=f'{chosen.id}_st_{index}',drop_id=chosen.id,**stage))
        details={'name':data['name'],'price':data.get('source_price_text'),'time_wat':data.get('source_time_text'),
            'stages':data.get('source_reported_stages',[]),'days':sorted({
                datetime.fromisoformat(s['starts_at']).astimezone(ZoneInfo('Africa/Lagos')).date().isoformat()
                for s in data.get('source_reported_stages',[])})}
        if prior:prior.drop_id,prior.details=chosen.id,details
        else:db.add(FeedMention(post_id=post.id,entry_key=key,drop_id=chosen.id,details=details))
        entries.append(key)
    if not unresolved:
        await db.execute(delete(FeedMention).where(FeedMention.post_id==post.id,FeedMention.entry_key.not_in(entries)))
    post.is_daily_list=True;post.list_date=day
    post.extracted_urls=[d['mint_page_url'] for d in safe]
    if safe and not post.published_at:
        post.list_sequence=1+(await db.scalar(select(func.max(SourcePost.list_sequence)).where(SourcePost.list_date==day)) or 0)
        post.published_at=now
    post.parser_version=VERSION
    post.processed_hash=digest if not unresolved else None
    post.processing_error='Some links or networks are waiting for verification.' if unresolved else None
    post.next_process_at=now+timedelta(minutes=2) if unresolved else None
    await db.commit();return count


async def sync_x_drops(db,adapter=None,source_name='lakzonevn'):
    name=source_name.lower()
    if name not in SOURCE_NAMES:raise ValueError('Unapproved discovery source')
    source=await ensure_source(db,name)
    source_id=source.id
    if name!='lakzonevn':await ensure_source(db,'lakzonevn')
    now=datetime.now(timezone.utc)
    if not source.is_monitoring:
        source.status='monitoring_paused';await db.commit();return 0
    due=not source.next_attempt_at or aware(source.next_attempt_at)<=now
    if due:
        source=await db.scalar(select(SourceConnection).where(SourceConnection.id==source_id,
            SourceConnection.is_monitoring.is_(True),or_(SourceConnection.next_attempt_at.is_(None),
                SourceConnection.next_attempt_at<=now)).with_for_update(skip_locked=True))
        if not source:
            await db.rollback()
            return await process_pending(db,source_name=name,limit=25) if adapter is not None else 0
        from app.config import settings
        cursor=source.catchup_cursor
        until=source.catchup_until or ((aware(source.last_sync_at) if source.last_sync_at else now-timedelta(days=14))-timedelta(days=2))
        source.next_attempt_at=now+timedelta(seconds=max(60,settings.X_DISCOVERY_TIMEOUT_SECONDS+30))
        await db.commit()
        try:
            if adapter is None:
                async def checkpoint(cursor,boundary):
                    state=await db.get(SourceConnection,source_id,populate_existing=True)
                    state.catchup_cursor,state.catchup_until=cursor,boundary
                    await db.commit()
                await TwscrapeSourceAdapter().fetch_posts(name,lambda item:save_raw(db,item,name),
                    cursor=cursor,since=aware(until),on_checkpoint=checkpoint)
            else:
                for item in await adapter.fetch_posts():await save_raw(db,item,name)
            source=await db.get(SourceConnection,source_id,populate_existing=True)
            source.status='healthy';source.last_sync_at=now;source.last_error=None;source.consecutive_failures=0
            source.next_attempt_at=now+timedelta(seconds=60)
        except Exception as error:
            await db.rollback();source=await db.get(SourceConnection,source_id,populate_existing=True)
            source.status='needs_attention';source.consecutive_failures+=1
            source.last_error=str(error) if isinstance(error,SourceUnavailable) else f'X refresh failed ({type(error).__name__}); saved posts are retained.'
            delay=max(getattr(error,'retry_after_seconds',60),min(1800,60*2**min(source.consecutive_failures-1,5)))
            source.next_attempt_at=now+timedelta(seconds=delay)
            if source.consecutive_failures in (3,12):
                from app.services.source_alerts import enqueue
                await enqueue(db,f'{name}:{source.consecutive_failures}',
                    f'@{name} could not refresh. Saved lists remain available; discovery will retry.')
        await db.commit()
    # Production fetchers release the X session without waiting for provider processing.
    return await process_pending(db,source_name=name,limit=25) if adapter is not None else 0


async def process_pending(db,*,source_name=None,limit=1):
    from app.services.feed_sources import approved
    now=datetime.now(timezone.utc)
    count=0
    for _ in range(limit):
        statement=select(SourcePost).where(approved(),or_(SourcePost.processed_hash.is_(None),
            SourcePost.processed_hash!=SourcePost.content_hash,SourcePost.parser_version!=VERSION),
            or_(SourcePost.next_process_at.is_(None),SourcePost.next_process_at<=now))
        if source_name:statement=statement.where(SourcePost.author_username==source_name)
        post=await db.scalar(statement.order_by(SourcePost.posted_at.desc()).with_for_update(skip_locked=True).limit(1))
        if not post:break
        pid=post.id;post.next_process_at=now+timedelta(minutes=2)
        await db.commit()
        try:
            async with asyncio.timeout(75):count+=await process_post(db,pid)
        except Exception:
            await db.rollback();post=await db.get(SourcePost,pid)
            post.processing_error='Saved post processing will retry.';post.next_process_at=now+timedelta(minutes=2)
            await db.commit()
    return count
