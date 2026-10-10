"""Bounded retries fitted to the unchanged approval deadline and provider cooldown."""
from datetime import timedelta

def next_retry(now,deadline,attempt,provider_wait=0):
    remaining=max(0,(deadline-now).total_seconds())
    # A fast FCFS window gets another check after 2s, rather than a fixed 15s.
    backoff=min(2**min(max(1,attempt),8),60,max(2,remaining/4))
    delay=max(provider_wait,backoff)
    return min(now+timedelta(seconds=delay),deadline),delay>=remaining
