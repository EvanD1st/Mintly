"""The operator's X session is isolated from user wallets and app login."""
import asyncio,os,re,json,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from contextlib import aclosing
from app.config import settings
from app.services.twikit_adapter import SourceUnavailable
from app.services.daily_list_parser import is_daily_list

class TwscrapeSourceAdapter:
    @staticmethod
    def provider_backoff(path):
        """Honor Twscrape's durable endpoint reset locks across process restarts."""
        try:
            with sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True) as db:
                accounts=[json.loads(r[0] or '{}') for r in db.execute('SELECT locks FROM accounts WHERE active=1')]
            now=datetime.now(timezone.utc)
            delays=[]
            for endpoint in ('UserByScreenName','UserTweets'):
                values=[]
                for locks in accounts:
                    value=locks.get(endpoint)
                    until=datetime.fromisoformat(value).replace(tzinfo=timezone.utc) if isinstance(value,str) else now
                    values.append(max(0,(until-now).total_seconds()))
                if values:delays.append(min(values))
            return max(delays,default=0)
        except (sqlite3.Error,ValueError,TypeError):return 0

    async def fetch_posts(self,source_name='lakzonevn',on_post=None,*,cursor=None,since=None,on_checkpoint=None):
        from app.services.feed_sources import SOURCE_NAMES
        if source_name.lower() not in SOURCE_NAMES:raise SourceUnavailable('Unapproved X source.')
        if not settings.X_DISCOVERY_ENABLED:raise SourceUnavailable('X discovery is disabled; admin imports remain available.')
        path=settings.TWSCRAPE_ACCOUNTS_FILE
        if not os.path.isfile(path):raise SourceUnavailable('The operator X session is unavailable; admin imports remain available.')
        if settings.APP_ENV=='production' and os.name!='nt' and os.stat(path).st_mode&0o077:
            raise SourceUnavailable('The operator X session requires protected file permissions.')
        backoff=self.provider_backoff(path)
        if backoff>0:
            raise SourceUnavailable('X requested a backoff; saved daily lists are retained until the provider reset.',backoff)
        try:return await asyncio.wait_for(self._fetch(path,source_name,on_post,cursor=cursor,since=since,on_checkpoint=on_checkpoint),max(1,settings.X_DISCOVERY_TIMEOUT_SECONDS))
        except Exception as error:raise SourceUnavailable(f'X discovery could not refresh ({type(error).__name__}); saved lists are retained.') from None

    async def _fetch(self,path,source_name='lakzonevn',on_post=None,*,cursor=None,since=None,on_checkpoint=None):
        from twscrape import API
        from loguru import logger
        logger.disable('twscrape')  # Provider logs must not expose session headers/cookies.
        api=API(pool=path,raise_when_no_account=True,wait_timeout=5)
        user=await api.user_by_login(source_name)
        if not user or user.username.lower()!=source_name.lower():raise ValueError('Unexpected source account')
        if on_post:
            return await self._pages(api,user,source_name,on_post,cursor,since,on_checkpoint)
        posts=[]
        # Overlapping history catches lists posted during an outage; IDs/revisions deduplicate it.
        async for tweet in api.user_tweets(user.id,limit=200):
            if (not getattr(tweet,'user',None) or tweet.user.username.lower()!=source_name.lower() or tweet.user.id!=user.id
                    or getattr(tweet,'retweetedTweet',None) or getattr(tweet,'inReplyToTweetId',None)
                    or getattr(tweet,'isQuoteStatus',False)):continue
            pid=str(tweet.id);text=tweet.rawContent or '';raw_text=text
            if not re.fullmatch(r'\d{1,30}',pid) or len(text)>100000:continue
            for link in tweet.links or []:
                if link.tcourl and link.url and link.url.startswith('https://'):
                    text=text.replace(link.tcourl,link.url)
            if tweet.date.tzinfo is None:continue
            item=dict(post_id=pid,text=text,raw_text=raw_text,posted_at=tweet.date.astimezone(timezone.utc),
                post_url=f'https://x.com/{source_name}/status/{pid}',author_username=source_name)
            if on_post:await on_post(item)
            if is_daily_list(text):posts.append(item)
        return posts

    @staticmethod
    def bottom_cursor(value):
        pending=[value]
        while pending:
            item=pending.pop()
            if isinstance(item,dict):
                if item.get('cursorType')=='Bottom' and isinstance(item.get('value'),str):return item['value']
                pending.extend(item.values())
            elif isinstance(item,list):pending.extend(item)
        return None

    async def _pages(self,api,user,name,on_post,cursor,since,on_checkpoint):
        from twscrape.models import parse_tweets
        async def page_pass(start,latest=False):
            received=False
            async with aclosing(api.user_tweets_raw(user.id,limit=40 if latest else 200,
                    kv={'cursor':start} if start else None)) as pages:
                async for response in pages:
                    received=True;payload=response.json();dates=[]
                    for tweet in parse_tweets(payload):
                        if not getattr(tweet,'user',None) or tweet.user.id!=user.id or tweet.user.username.lower()!=name.lower():continue
                        if getattr(tweet,'retweetedTweet',None) or getattr(tweet,'inReplyToTweetId',None) or getattr(tweet,'isQuoteStatus',False):continue
                        if tweet.date.tzinfo is None:continue
                        dates.append(tweet.date)
                        raw=tweet.rawContent or '';text=raw
                        if len(raw)>100000 or not re.fullmatch(r'\d{1,30}',str(tweet.id)):continue
                        for link in tweet.links or []:
                            if link.tcourl and link.url and link.url.startswith('https://'):text=text.replace(link.tcourl,link.url)
                        await on_post(dict(post_id=str(tweet.id),text=text,raw_text=raw,
                            posted_at=tweet.date.astimezone(timezone.utc),author_username=name))
                    if latest:break
                    next_cursor=self.bottom_cursor(payload)
                    complete=not next_cursor or bool(since and dates and max(dates)<since)
                    if on_checkpoint:await on_checkpoint(None if complete else next_cursor,None if complete else since)
                    if complete:break
            if not received:raise SourceUnavailable('X returned no timeline pages; saved posts and catch-up position are retained.')
        # Fresh lists are checked even when an older interrupted pagination pass remains.
        if cursor:await page_pass(None,latest=True)
        await page_pass(cursor)
        return []
