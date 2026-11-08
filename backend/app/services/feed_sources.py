"""Shared source identity, stable collection cards and account-scoped additions."""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, or_, func
from app.models import Drop, SourcePost, SourceConnection, FeedMention, FeedSeen, DismissedDrop, FeedWalletCheck, MintTask
from app.services.opensea import collection_slug, OpenSeaUnavailable

SOURCE_NAMES = ('lakzonevn','cassio_sch')
DISPLAY_NAMES = {'lakzonevn':'lakzonevn','cassio_sch':'Cassio_Sch'}


def approved():
    return or_(SourcePost.is_manual_import.is_(True),func.lower(SourcePost.author_username).in_(SOURCE_NAMES))


def slug(url):
    try:return collection_slug(url).lower()
    except OpenSeaUnavailable:return None


def same_collection(a,b):
    # Names can suggest candidates, but never establish identity.
    if a.chain_id and b.chain_id and a.chain_id!=b.chain_id:return False
    if a.contract_address and b.contract_address and a.chain_id==b.chain_id:
        return a.contract_address.lower()==b.contract_address.lower()
    return bool(slug(a.mint_page_url) and slug(a.mint_page_url)==slug(b.mint_page_url))


async def canonical_drop(db,candidate):
    """Caller holds the discovery-only lock; no provider IO or signer lock here."""
    rows=(await db.scalars(select(Drop).join(SourcePost,Drop.source_post_id==SourcePost.id)
        .where(approved(),Drop.is_demo.is_(False),Drop.canonical_id.is_(None),
            or_(func.lower(Drop.name)==candidate.name.lower(),Drop.mint_page_url==candidate.mint_page_url,
                func.lower(Drop.contract_address)==(candidate.contract_address or '').lower()))
        .order_by(Drop.created_at,Drop.id))).all()
    matches=[d for d in rows if same_collection(d,candidate)]
    if not matches:return candidate
    identities={(d.chain_id,d.contract_address.lower()) for d in matches if d.contract_address}
    if len(identities)>1:raise ValueError('Conflicting verified collection identities; source entry retained for review.')
    chosen=matches[0]
    for duplicate in matches[1:]:
        duplicate.canonical_id=chosen.id
        from sqlalchemy import update
        await db.execute(update(FeedMention).where(FeedMention.drop_id==duplicate.id).values(drop_id=chosen.id))
    # Only fill missing public identity. Never replace verified identity or stage rows.
    if not chosen.chain_id and candidate.chain_id:chosen.chain_id,chosen.chain=candidate.chain_id,candidate.chain
    if not chosen.contract_address and candidate.contract_address:chosen.contract_address=candidate.contract_address
    return chosen


async def discovery_lock(db):
    # A separate source row serializes publication/merges; it never blocks mint execution.
    if db.bind.dialect.name=='sqlite':
        from sqlalchemy import text
        await db.execute(text('BEGIN IMMEDIATE'))
    await db.scalar(select(SourceConnection).where(SourceConnection.source_name=='lakzonevn').with_for_update())


def carryover_visible(group,day,now,verified=None):
    """Presentation expiry only; never cancels tasks or edits discovery history."""
    if any(p.list_date>=day for p,_ in group['mentions']):return True
    stages=verified or [s for _,details in group['mentions'] for s in details.get('stages',[])]
    if not stages:return True
    openings=[]
    for stage in stages:
        try:
            opening=datetime.fromisoformat(stage['starts_at'])
            if opening.tzinfo is None:return True
            if opening.astimezone(ZoneInfo('Africa/Lagos')).date()<=day:openings.append(opening)
        except (KeyError,TypeError,ValueError):return True
    return bool(openings) and now<max(openings)+timedelta(hours=1)


async def daily_collections(db,day,user_id=None,*,now=None):
    now=now or datetime.now(timezone.utc)
    rows=(await db.execute(select(FeedMention,SourcePost,Drop).join(SourcePost,FeedMention.post_id==SourcePost.id)
        .join(Drop,FeedMention.drop_id==Drop.id).where(SourcePost.list_date>=day-timedelta(days=1),
            SourcePost.list_date<=day+timedelta(days=1),approved(),Drop.is_demo.is_(False))
        .order_by(SourcePost.published_at,SourcePost.created_at,SourcePost.id))).all()
    legacy=(await db.execute(select(Drop,SourcePost).join(SourcePost,Drop.source_post_id==SourcePost.id)
        .where(SourcePost.list_date==day,approved(),Drop.is_demo.is_(False),
            ~select(FeedMention.post_id).where(FeedMention.post_id==SourcePost.id).exists())
        .order_by(Drop.created_at,Drop.id))).all()
    combined=[(d,p,m.details) for m,p,d in rows if p.list_date<=day or day.isoformat() in m.details.get('days',[])]+[
        (d,p,{'price':d.source_price_text,'time_wat':d.source_time_text,'stages':[]}) for d,p in legacy]
    groups=[]
    for d,p,details in combined:
        target=next((g for g in groups if g['drop'].id==d.id or same_collection(g['drop'],d)),None)
        if not target:
            target={'drop':d,'ids':set(),'mentions':[]};groups.append(target)
        target['ids'].add(d.id)
        target['mentions'].append((p,details))
    # Reuse the latest verified OpenSea phase schedule when available. This keeps
    # a postponed opening ahead of an older source time, without provider IO here.
    ids={i for g in groups if not any(p.list_date>=day for p,_ in g['mentions']) for i in g['ids']}
    checks=(await db.scalars(select(FeedWalletCheck).where(FeedWalletCheck.drop_id.in_(ids),
        FeedWalletCheck.checked_at.is_not(None)).order_by(FeedWalletCheck.checked_at.desc()))).all() if ids else []
    schedules={}
    for check in checks:
        if check.result.get('stages') and check.drop_id not in schedules:
            schedules[check.drop_id]=check.result['stages']
    from app.services.mint_plans import aware
    # Armed schedule tracking may have newer phase timing than display checks,
    # which intentionally stop once a mint is armed or completed.
    carryovers=[g for g in groups if g['ids']&ids]
    contracts=[g['drop'].contract_address.lower() for g in carryovers if g['drop'].contract_address]
    urls=[g['drop'].mint_page_url for g in carryovers]
    tasks=(await db.execute(select(MintTask.scheduled_for_utc,Drop).join(Drop,MintTask.drop_id==Drop.id).where(
        or_(Drop.id.in_(ids),func.lower(Drop.contract_address).in_(contracts),Drop.mint_page_url.in_(urls)),
        MintTask.is_demo.is_(False),MintTask.schedule_checked_at.is_not(None)))).all() if ids else []
    for opening,task_drop in tasks:
        for g in carryovers:
            if task_drop.id not in g['ids'] and not same_collection(g['drop'],task_drop):continue
            key=g['drop'].id
            schedules.setdefault(key,[s for _,details in g['mentions'] for s in details.get('stages',[])])
            schedules[key]=[*schedules[key],{'starts_at':aware(opening).isoformat()}]
    groups=[g for g in groups if carryover_visible(g,day,now,
        next((schedules[i] for i in g['ids'] if i in schedules),None))]
    if user_id:
        dismissed=set((await db.scalars(select(DismissedDrop.drop_id).where(DismissedDrop.user_id==user_id))).all())
        aliases=(await db.execute(select(Drop.id,Drop.canonical_id).where(Drop.id.in_(dismissed),Drop.canonical_id.is_not(None)))).all() if dismissed else []
        dismissed|={canonical for alias,canonical in aliases if alias in dismissed}
        groups=[g for g in groups if not(g['ids']&dismissed)]
    return groups


async def source_metadata(db,groups,user_id,day=None):
    ids={p.id for g in groups for p,_ in g['mentions']}
    seen={s.post_id:s.content_hash for s in (await db.scalars(select(FeedSeen).where(FeedSeen.user_id==user_id,FeedSeen.post_id.in_(ids)))).all()} if ids else {}
    result={};editions={}
    for group in groups:
        mentions=group['mentions'];sources=[]
        unseen=[];known=False
        for p,details in mentions:
            digest=p.content_hash or ''
            known=known or p.id in seen
            if digest and seen.get(p.id)!=digest:unseen.append(p.id)
            else:known=True
            editions[p.id]={'id':p.id,'content_hash':digest,'sequence':p.list_sequence or 1,
                'source':DISPLAY_NAMES.get(p.author_username.lower(),p.author_username),'published_at':p.published_at or p.created_at}
            sources.append({'author':DISPLAY_NAMES.get(p.author_username.lower(),p.author_username),
                'post_url':None if p.is_manual_import else f'https://x.com/{p.author_username}/status/{p.post_id}',
                'price':details.get('price'),'time_wat':details.get('time_wat'),'stages':details.get('stages',[])})
        context=None;schedule=[]
        if day:
            dates=[p.list_date for p,_ in mentions if p.list_date]
            if dates and max(dates)<day:
                context='From yesterday’s list' if max(dates)==day-timedelta(days=1) else 'From an earlier list'
            for _,details in mentions:
                for stage in details.get('stages',[]):
                    try:opening=datetime.fromisoformat(stage['starts_at']).astimezone(ZoneInfo('Africa/Lagos'))
                    except (KeyError,TypeError,ValueError):continue
                    if opening.date()==day:
                        label=f"{stage['name']} {opening.strftime('%H:%M')} WAT"
                        if label not in schedule:schedule.append(label)
        result[group['drop'].id]={'sources':sources,'additions':('updated' if known else 'new') if unseen else None,
            'list_context':context,'today_schedule':' · '.join(schedule) or None}
    return result,list(editions.values())


async def health(db):
    rows=(await db.scalars(select(SourceConnection).where(SourceConnection.source_name.in_(SOURCE_NAMES)))).all()
    result=[]
    from app.services.mint_plans import aware
    now=datetime.now(timezone.utc)
    day=now.astimezone(ZoneInfo('Africa/Lagos')).date()
    posts=(await db.execute(select(SourcePost.author_username,SourcePost.processing_error,
        SourcePost.posted_at,SourcePost.list_date,SourcePost.published_at).where(
            SourcePost.author_username.in_(SOURCE_NAMES),SourcePost.verification_retired_at.is_(None),
            or_(SourcePost.posted_at>=now-timedelta(days=2),SourcePost.list_date==day)))).all()
    for name in SOURCE_NAMES:
        row=next((r for r in rows if r.source_name==name),None)
        delayed=not row or not row.last_sync_at or (now-aware(row.last_sync_at)).total_seconds()>900
        result.append({'name':DISPLAY_NAMES[name],'status':row.status if row else 'needs_attention',
            'is_monitoring':row.is_monitoring if row else True,'last_sync_at':row.last_sync_at if row else None,
            'delayed':delayed,'last_error':row.last_error if row else None})
        result[-1]['catchup_pending']=bool(row and row.catchup_cursor)
        result[-1]['processing_pending']=any(p.processing_error and aware(p.posted_at)>=now-timedelta(days=2) for p in posts if p.author_username==name)
        result[-1]['today_posted']=any(p.list_date==day and p.published_at for p in posts if p.author_username==name)
    return result
