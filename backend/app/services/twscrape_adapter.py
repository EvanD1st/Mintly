"""The operator's X session is isolated from user wallets and app login."""
import asyncio,os,re,json,sqlite3
from datetime import datetime,timezone
from pathlib import Path
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

    async def fetch_posts(self):
        if not settings.X_DISCOVERY_ENABLED:raise SourceUnavailable('X discovery is disabled; admin imports remain available.')
        path=settings.TWSCRAPE_ACCOUNTS_FILE
        if not os.path.isfile(path):raise SourceUnavailable('The operator X session is unavailable; admin imports remain available.')
        if settings.APP_ENV=='production' and os.name!='nt' and os.stat(path).st_mode&0o077:
            raise SourceUnavailable('The operator X session requires protected file permissions.')
        if self.provider_backoff(path)>0:
            raise SourceUnavailable('X requested a backoff; saved daily lists are retained until the provider reset.')
        try:return await asyncio.wait_for(self._fetch(path),max(1,settings.X_DISCOVERY_TIMEOUT_SECONDS))
        except Exception as error:raise SourceUnavailable(f'X discovery could not refresh ({type(error).__name__}); saved lists are retained.') from None

    async def _fetch(self,path):
        from twscrape import API
        from loguru import logger
        logger.disable('twscrape')  # Provider logs must not expose session headers/cookies.
        api=API(pool=path,raise_when_no_account=True,wait_timeout=5)
        user=await api.user_by_login('lakzonevn')
        if not user or user.username.lower()!='lakzonevn':raise ValueError('Unexpected source account')
        posts=[]
        async for tweet in api.user_tweets(user.id,limit=50):
            if (not getattr(tweet,'user',None) or tweet.user.username.lower()!='lakzonevn' or tweet.user.id!=user.id
                    or getattr(tweet,'retweetedTweet',None) or getattr(tweet,'inReplyToTweetId',None)
                    or getattr(tweet,'isQuoteStatus',False)):continue
            pid=str(tweet.id);text=tweet.rawContent or '';raw_text=text
            if not re.fullmatch(r'\d{1,30}',pid) or not is_daily_list(text):continue
            for link in tweet.links or []:
                if link.tcourl and link.url and link.url.startswith('https://'):
                    text=text.replace(link.tcourl,link.url)
            if tweet.date.tzinfo is None:continue
            posts.append(dict(post_id=pid,text=text,raw_text=raw_text,posted_at=tweet.date.astimezone(timezone.utc),
                post_url=f'https://x.com/lakzonevn/status/{pid}',author_username='lakzonevn'))
        return posts
