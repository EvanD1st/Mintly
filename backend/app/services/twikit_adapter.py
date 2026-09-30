"""Read-only Twikit adapter for the single approved X account."""

import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from twikit import Client

from app.config import settings


class SourceUnavailable(Exception):
    pass


def _posted_at(value):
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = parsedate_to_datetime(str(value))
        except (TypeError, ValueError):
            try:
                result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except (TypeError, ValueError) as error:
                raise SourceUnavailable("X returned a post without a valid date.") from error
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def _expanded_text(tweet):
    text = str(getattr(tweet, "full_text", None) or getattr(tweet, "text", "") or "")
    for entry in getattr(tweet, "urls", []) or []:
        short = entry.get("url") if isinstance(entry, dict) else getattr(entry, "url", None)
        expanded = entry.get("expanded_url") if isinstance(entry, dict) else getattr(entry, "expanded_url", None)
        if short and expanded and expanded.startswith("https://"):
            text = text.replace(short, expanded)
    return text


class TwikitSourceAdapter:
    """Fetch posts from @lakzonevn; never create drops from another account."""

    async def fetch_posts(self):
        cookies_path = settings.TWIKIT_COOKIES_FILE
        has_cookies = bool(cookies_path and os.path.isfile(cookies_path))
        if not has_cookies and not (settings.TWIKIT_USERNAME and settings.TWIKIT_PASSWORD):
            raise SourceUnavailable("An authenticated X session is required for Twikit. Admin imports remain available.")

        client = Client("en-US")
        try:
            if has_cookies:
                client.load_cookies(cookies_path)
            else:
                await client.login(auth_info_1=settings.TWIKIT_USERNAME,
                                   auth_info_2=settings.TWIKIT_EMAIL,
                                   password=settings.TWIKIT_PASSWORD)
                if cookies_path:
                    client.save_cookies(cookies_path)
            user = await client.get_user_by_screen_name("lakzonevn")
            if str(getattr(user, "screen_name", "")).lower() != "lakzonevn":
                raise SourceUnavailable("X returned a different account for @lakzonevn.")
            tweets = await client.get_user_tweets(user.id, "Tweets", count=20)
        except SourceUnavailable:
            raise
        except Exception as error:
            raise SourceUnavailable(f"Twikit could not read @lakzonevn ({type(error).__name__}).") from error

        posts = []
        for tweet in tweets:
            tweet_user = getattr(tweet, "user", None)
            if tweet_user and str(getattr(tweet_user, "screen_name", "")).lower() != "lakzonevn":
                continue
            if getattr(tweet, "retweeted_tweet", None) or getattr(tweet, "in_reply_to", None):
                continue
            post_id = str(getattr(tweet, "id", ""))
            text = _expanded_text(tweet)
            if not post_id.isdecimal() or not text:
                continue
            if not re.search(r"\b(mint|mints|drop|drops)\b", text, re.I):
                continue
            try:
                posted_at = _posted_at(getattr(tweet, "created_at", None))
            except SourceUnavailable:
                continue
            posts.append({"post_id": post_id, "text": text,
                          "posted_at": posted_at,
                          "post_url": f"https://x.com/lakzonevn/status/{post_id}"})
        return posts
