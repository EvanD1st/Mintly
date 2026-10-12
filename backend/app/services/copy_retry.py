"""Space repeated copy preparation failures without extending consent."""
from datetime import timedelta
from hashlib import sha256


def next_copy_retry(now, deadline, attempt, event_id, provider_wait=0):
    # Spread peers deterministically; the first check remains prompt, while
    # persistently unavailable instructions stop consuming capacity each minute.
    backoff = min(300, 60 * 2 ** min(max(attempt - 1, 0), 3))
    jitter = int.from_bytes(sha256(event_id.encode()).digest()[:2], 'big') % 16
    delay = max(backoff + jitter, provider_wait)
    return min(now + timedelta(seconds=delay), deadline)
