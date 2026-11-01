"""Parse posted discovery facts without inventing stage eligibility or prices."""
import hashlib,re
from datetime import datetime,date,timezone,timedelta
from decimal import Decimal,InvalidOperation
from zoneinfo import ZoneInfo
from app.services.networks import NETWORKS
WAT=ZoneInfo('Africa/Lagos')
VERSION=2
FIELD=re.compile(r'^\s*[-•*]?\s*(chain|network|time|mint\s*page(?:\s*/\s*checker)?|link|price|supply|wl|public|presale|allowlist)\s*:\s*(.*)$',re.I)
DAILY=re.compile(r'\bdaily\s+(?:mint\s+)?(?:drops?|mint\s+list|list)\b',re.I)

def daily_date(text,posted_at):
    anchor=posted_at.astimezone(WAT).date()
    match=re.search(r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:st|nd|rd|th)?(?:[, ]+(20\d{2}))?',text,re.I)
    if not match:return anchor
    month=datetime.strptime(match[1].capitalize(),'%B').month
    try:
        years=[int(match[3])] if match[3] else [anchor.year-1,anchor.year,anchor.year+1]
        return min((date(y,month,int(match[2])) for y in years),key=lambda d:abs((d-anchor).days))
    except ValueError:return None

def is_daily_list(text):
    headline=' '.join([line.strip() for line in text.splitlines() if line.strip()][:2])
    return bool((DAILY.search(headline) and re.search(r'(?mi)^\s*[-•*]?\s*(?:chain|network)\s*:',text))
        or (re.search(r'\bmints?\s+today\b',headline,re.I)
            and re.search(r'(?:^|\n)\s*\d+[.)]\s+',text) and re.search(r'https://',text)))

def network(value):
    clean=re.sub(r'\s+(?:chain|network|mainnet)$','',value.strip(),flags=re.I).lower()
    aliases={'eth':'ethereum','apechain':'ape_chain','ape chain':'ape_chain','hyper evm':'hyperevm'}
    clean=aliases.get(clean,clean)
    n=next((n for n in NETWORKS.values() if clean in (n.slug.lower(),n.name.lower())),None)
    return (n.name,n.chain_id) if n else (value.strip() or 'Unknown',0)

def parse(text,posted_at):
    lines=text.splitlines();indices=[i for i,l in enumerate(lines) if re.match(r'^\s*[-•*]?\s*(?:Chain|Network)\s*:',l,re.I)]
    if not indices:return compact(text,posted_at)
    entries=[];day=daily_date(text,posted_at)
    for pos,i in enumerate(indices):
        lower=indices[pos-1]+1 if pos else 0
        headers=[l.strip() for l in lines[lower:i] if l.strip() and not FIELD.match(l)]
        headers=[l for l in headers if not DAILY.search(l) and not re.match(r'\[.*\]$',l)]
        title=headers[-1] if headers else 'Unnamed collection'
        title=re.sub(r'^\s*(?:\d+[.)]|#\d+)\s*','',title).strip()[:150]
        fields={}
        for l in lines[i:indices[pos+1] if pos+1<len(indices) else len(lines)]:
            m=FIELD.match(l)
            if m and m[1].lower() not in fields:fields[m[1].lower()]=m[2].strip()
        chain,cid=network(fields.get('chain',fields.get('network','')))
        page=next((v for k,v in fields.items() if k.startswith('mint') or k=='link'),'')
        link=re.search(r'https?://[^\s<>"\']+',page)
        url=link[0].rstrip('.,)') if link else ''
        price=fields.get('price','TBA');clock=fields.get('time','TBA');stages=[]
        phase_fields=[(k,v) for k,v in fields.items() if k in ('wl','presale','allowlist','public')]
        for kind,value in phase_fields or [('Source listing',price)]:
            claim=re.fullmatch(r'(.+?)\s*\(([^)]+)\)',value)
            amount,when=(claim[1],claim[2]) if claim else (value,clock)
            label='Allowlist' if kind in ('wl','presale','allowlist') else 'Public' if kind=='public' else kind
            stage=stated_stage(label,amount,when,day)
            if stage:stages.append(stage)
        key=hashlib.sha256(f'{pos}:{title}:{cid}'.encode()).hexdigest()
        clock_only=stated_stage('Source listing','Free',clock,day)
        wat_clock=' · '.join(s['start_time_utc'].astimezone(WAT).strftime('%d %b %H:%M WAT') for s in stages) if stages else (
            clock_only['start_time_utc'].astimezone(WAT).strftime('%d %b %H:%M WAT') if clock_only else clock)
        entries.append(dict(name=title,chain=chain,chain_id=cid,mint_page_url=url,
            source_entry_key=key,source_price_text=price[:200],source_time_text=wat_clock[:100],
            source_reported_stages=[{'name':s['stage_name'],'starts_at':s['start_time_utc'].isoformat(),
                'wat':s['start_time_utc'].astimezone(WAT).strftime('%d %b %H:%M WAT')} for s in (stages or ([clock_only] if clock_only else []))],
            site_label='OpenSea' if 'opensea.io/' in url else 'Project website',icon_name='gem',
            status_label='Not verified',status_kind='manual',is_supported_integration=False,
            manual_notice='Posted discovery terms are not verified. Wallet and mint terms require verification.',stages=stages))
    return entries


def stated_stage(label,price,clock,day):
    pm=re.fullmatch(r'(free|\d+(?:\.\d+)?)\s*(ETH|HYPE|APE)?',price.strip(),re.I)
    tm=re.fullmatch(r'(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?\s*(UTC|WAT)',clock.strip(),re.I)
    if not day or not pm or not tm:return None
    hour=int(tm[1]);minute=int(tm[2] or 0);meridiem=(tm[3] or '').upper()
    if not (1<=hour<=12 if meridiem else 0<=hour<24) or minute>59:return None
    hour=hour%12+(12 if meridiem=='PM' else 0) if meridiem else hour
    try:
        wei=0 if pm[1].lower()=='free' else int(Decimal(pm[1])*10**18)
        start=datetime(day.year,day.month,day.day,hour,minute,tzinfo=timezone.utc if tm[4].upper()=='UTC' else WAT)
        if 0<=wei<2**63:return dict(stage_name=label,start_time_utc=start.astimezone(timezone.utc),price_wei=wei,
            price_eth_str=pm[1],limit_per_wallet=0,eligibility_status='unknown')
    except (ValueError,InvalidOperation):pass


def compact(text,posted_at):
    """Numbered UTC lists: source claims stay display-only, never approval terms."""
    entries=[];day=daily_date(text,posted_at)
    chunks=re.split(r'(?:^|\n)\s*\d+[.)]\s+',text)[1:]
    for index,chunk in enumerate(chunks):
        url=re.search(r'https?://[^\s<>"\']+',chunk)
        if not url:continue
        title=re.sub(r'\s+@\w+.*','',chunk[:url.start()].splitlines()[0]).strip()[:150]
        if not title:continue
        tail=chunk[url.end():].strip();price=tail.split('|',1)[1].splitlines()[0].strip() if '|' in tail else 'TBA'
        tz=timezone.utc if re.search(r'\bUTC\b',tail,re.I) else WAT if re.search(r'\bWAT\b',tail,re.I) else None
        reports=[];date_cursor=day;previous=None
        for match in re.finditer(r'([A-Za-z][A-Za-z /-]{0,35}?)\s+(\d{1,2}):(\d{2})(?:\s*(AM|PM))?',tail):
            hour,minute=int(match[2]),int(match[3]);ampm=(match[4] or '').upper()
            if minute>59 or (not ampm and hour>23) or (ampm and not 1<=hour<=12):continue
            if ampm:hour=hour%12+(12 if ampm=='PM' else 0)
            if not tz or not day:continue
            # A source's explicit next-day suffix or midnight rollover is retained.
            suffix=tail[match.end():].split('|',1)[0].split('\n',1)[0]
            explicit=re.search(r'\((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2})\)',suffix,re.I)
            if explicit:
                month=datetime.strptime(explicit[1].title(),'%b').month
                try:date_cursor=min((date(y,month,int(explicit[2])) for y in (day.year-1,day.year,day.year+1)),key=lambda d:abs((d-day).days))
                except ValueError:continue
            elif previous is not None and hour*60+minute<previous:date_cursor+=timedelta(days=1)
            previous=hour*60+minute
            start=datetime.combine(date_cursor,datetime.min.time(),tzinfo=tz)+timedelta(hours=hour,minutes=minute)
            reports.append({'name':match[1].strip(' |-/'), 'starts_at':start.astimezone(timezone.utc).isoformat(),
                'wat':start.astimezone(WAT).strftime('%d %b %H:%M WAT')})
        clock=' · '.join(f"{s['name']} {s['wat']}" for s in reports) or 'Time not verified'
        page=url[0].rstrip('.,)');key=hashlib.sha256(page.encode()).hexdigest()
        entries.append(dict(name=title,chain='Unknown',chain_id=0,mint_page_url=page,needs_network_lookup=True,
            source_entry_key=key,source_price_text=price[:200],source_time_text=clock[:100],
            source_reported_stages=reports,site_label='OpenSea' if 'opensea.io/' in page else 'Project website',
            icon_name='gem',status_kind='manual',status_label='Not verified',is_supported_integration=False,
            stages=[],manual_notice='Posted discovery information. Wallet and mint terms require verification.'))
    return entries
