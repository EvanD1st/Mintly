"""Diagnostic script to test and verify Twikit feasibility against @lakzonevn."""

import os
import sys
import json
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from twikit import Client
from app.config import settings


async def run_twikit_diagnostic(
    target_username: str = "lakzonevn",
    cookies_path: Optional[str] = None
) -> Dict[str, Any]:
    """Runs a thorough diagnostic of the Twikit client for reading @lakzonevn.
    
    Reports redacted results, error codes (429 rate limit, 414 login error, 425 timeline parsing).
    Does NOT fabricate results.
    """
    cookies_path = cookies_path or settings.TWIKIT_COOKIES_FILE
    client = Client("en-US")
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target": target_username,
        "twikit_version": "2.3.3",
        "has_cookies_file": os.path.exists(cookies_path) if cookies_path else False,
        "status": "pending",
        "error_type": None,
        "details": None,
        "captured_post": None,
    }

    # Step 1: Check session configuration
    if not result["has_cookies_file"] and not settings.TWIKIT_USERNAME:
        result["status"] = "missing_credentials"
        result["error_type"] = "AUTH_BLOCKED"
        result["details"] = (
            "No X cookies.json or session credentials configured. "
            "Operator must provide cookies.json locally. Twikit cannot query X without an authenticated session. "
            "Falling back cleanly to manual import and demo mode."
        )
        return result

    # Step 2: Attempt loading cookies
    try:
        if result["has_cookies_file"]:
            client.load_cookies(cookies_path)
        elif settings.TWIKIT_USERNAME and settings.TWIKIT_PASSWORD:
            await client.login(
                auth_info_1=settings.TWIKIT_USERNAME,
                auth_info_2=settings.TWIKIT_EMAIL,
                password=settings.TWIKIT_PASSWORD,
            )
            client.save_cookies(cookies_path)
    except Exception as e:
        result["status"] = "auth_failed"
        result["error_type"] = "LOGIN_FAILURE"  # Twikit Issue #414
        result["details"] = f"Authentication failed: {type(e).__name__} - {str(e)}"
        return result

    # Step 3: Fetch User
    try:
        user = await client.get_user_by_screen_name(target_username)
        result["user_found"] = True
        result["user_id_redacted"] = str(user.id)[:4] + "****" if hasattr(user, "id") else None
    except Exception as e:
        err_str = str(e).lower()
        result["status"] = "failed"
        if "429" in err_str or "rate limit" in err_str:
            result["error_type"] = "RATE_LIMITED_429"  # Twikit Issue #433
        else:
            result["error_type"] = "USER_LOOKUP_ERROR"
        result["details"] = f"Failed to look up user {target_username}: {str(e)}"
        return result

    # Step 4: Fetch Tweets
    try:
        tweets = await client.get_user_tweets(user.id, "Tweets", count=10)
        if not tweets:
            result["status"] = "empty_timeline"
            result["details"] = "Timeline returned 0 tweets."
            return result

        # Step 5: Search for daily list post
        for tweet in tweets:
            text = getattr(tweet, "full_text", getattr(tweet, "text", ""))
            urls = getattr(tweet, "urls", [])
            if any(kw in text.lower() for kw in ["drops", "mint", "daily"]):
                result["status"] = "success"
                result["captured_post"] = {
                    "id": str(getattr(tweet, "id", "unknown")),
                    "created_at": str(getattr(tweet, "created_at", "")),
                    "text_preview": text[:120] + "...",
                    "extracted_urls_count": len(urls),
                    "urls_sample": [u.get("expanded_url", "") for u in urls[:3]] if urls else [],
                }
                break

        if not result["captured_post"]:
            result["status"] = "success_no_daily_list"
            result["details"] = "Fetched tweets successfully, but no recent post matched daily list keywords."

    except Exception as e:
        err_str = str(e).lower()
        result["status"] = "failed"
        if "429" in err_str:
            result["error_type"] = "RATE_LIMITED_429"
        elif "parsing" in err_str or "keyerror" in err_str or "typeerror" in err_str:
            result["error_type"] = "TIMELINE_PARSING_ERROR"  # Twikit Issue #425
        else:
            result["error_type"] = "TWEET_FETCH_ERROR"
        result["details"] = f"Failed to fetch user tweets: {str(e)}"

    return result


def main():
    """CLI runner for diagnostic."""
    print("=" * 60)
    print("Mintly - Twikit Diagnostic for @lakzonevn")
    print("=" * 60)
    
    res = asyncio.run(run_twikit_diagnostic())
    print(json.dumps(res, indent=2))
    print("=" * 60)
    if res["status"] == "success":
        print("RESULT: SUCCESS - Live tweets and URLs captured.")
    elif res["status"] == "missing_credentials":
        print("RESULT: CREDENTIALS REQUIRED - Falling back to manual import and demo mode.")
    else:
        print(f"RESULT: FAILED ({res.get('error_type')}) - {res.get('details')}")


if __name__ == "__main__":
    main()
