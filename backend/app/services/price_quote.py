"""Display-only ETH/USDT conversion; never a signing or spending price."""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import aiohttp

_cached = None
_lock = asyncio.Lock()

async def eth_usdt_quote():
    global _cached
    async with _lock:
        now = datetime.now(timezone.utc)
        if _cached and now - _cached[1] < timedelta(seconds=60):
            return _cached
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4), trust_env=False) as session:
                async with session.get('https://api.exchange.coinbase.com/products/ETH-USDT/ticker', allow_redirects=False) as response:
                    if response.status != 200:
                        return None
                    data = await response.json()
                    price = Decimal(data['price'])
                    tick = datetime.fromisoformat(data['time'].replace('Z', '+00:00'))
                    if not price.is_finite() or not 0 < price < 1000000 or tick.tzinfo is None or abs(now - tick) > timedelta(minutes=5):
                        return None
                    _cached = (format(price, 'f'), now)
                    return _cached
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError, InvalidOperation):
            return None
