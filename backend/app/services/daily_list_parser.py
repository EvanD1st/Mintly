"""Parse posted discovery facts without inventing stage eligibility or prices."""
import hashlib,re
from datetime import datetime,date,timezone,timedelta
from decimal import Decimal,InvalidOperation
from zoneinfo import ZoneInfo
from app.services.networks import NETWORKS
WAT=ZoneInfo('Africa/Lagos')
VERSION=1
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
    return bool(DAILY.search(headline) and re.search(r'(?mi)^\s*[-•*]?\s*(?:chain|network)\s*:',text))

def network(value):
    clean=re.sub(r'\s+(?:chain|network|mainnet)$','',value.strip(),flags=re.I).lower()
    aliases={'eth':'ethereum','apechain':'ape_chain','ape chain':'ape_chain','hyper evm':'hyperevm'}
    clean=aliases.get(clean,clean)
    n=next((n for n in NETWORKS.values() if clean in (n.slug.lower(),n.name.lower())),None)
    return (n.name,n.chain_id) if n else (value.strip() or 'Unknown',0)

def parse(text,posted_at):
    lines=text.splitlines();indices=[i for i,l in enumerate(lines) if re.match(r'^\s*[-•*]?\s*(?:Chain|Network)\s*:',l,re.I)]
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
        # A precise single posted price/time is display data only, never evidence of a phase.
        pm=re.fullmatch(r'(free|\d+(?:\.\d+)?)\s*(ETH|HYPE|APE)?',price,re.I)
        tm=re.fullmatch(r'(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?\s*(UTC|WAT)',clock,re.I)
        if day and pm and tm:
            hour=int(tm[1]);minute=int(tm[2] or 0);meridiem=(tm[3] or '').upper()
            valid=(1<=hour<=12) if meridiem else (0<=hour<24)
            if valid and minute<60:
                hour=hour%12+(12 if meridiem=='PM' else 0) if meridiem else hour
                try:
                    wei=0 if pm[1].lower()=='free' else int(Decimal(pm[1])*10**18)
                    dt=datetime(day.year,day.month,day.day,hour,minute,tzinfo=timezone.utc if tm[4].upper()=='UTC' else WAT)
                    if 0<=wei<2**63:stages=[dict(stage_name='Source listing',start_time_utc=dt.astimezone(timezone.utc),price_wei=wei,price_eth_str=pm[1],limit_per_wallet=0,eligibility_status='unknown')]
                except (ValueError,InvalidOperation):pass
        key=hashlib.sha256(f'{pos}:{title}:{cid}'.encode()).hexdigest()
        entries.append(dict(name=title,chain=chain,chain_id=cid,mint_page_url=url,
            source_entry_key=key,source_price_text=price[:200],source_time_text=clock[:100],
            site_label='OpenSea' if 'opensea.io/' in url else 'Project website',icon_name='gem',
            status_label='Not verified',status_kind='unknown',is_supported_integration=False,
            manual_notice='Posted discovery information. Wallet and mint terms require verification.',stages=stages))
    return entries
