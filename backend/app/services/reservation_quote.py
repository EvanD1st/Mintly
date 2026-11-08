"""Fresh USD conversion for queued holds only; never changes signing authority."""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING

import aiohttp

_cache = {}
_lock = asyncio.Lock()


def parse_quote(data, currency):
    value = data['data']
    if value['base'] != currency or value['currency'] != 'USD':
        raise ValueError('Unexpected quote currency')
    price = Decimal(value['amount'])
    if not price.is_finite() or not Decimal('0.000001') <= price <= Decimal('1000000'):
        raise ValueError('Invalid native token price')
    return int((Decimal(10**18) / price).to_integral_value(rounding=ROUND_CEILING))


async def dollar_native_wei(currency):
    if currency not in ('APE', 'HYPE'):
        raise ValueError('Unsupported reservation currency')
    async with _lock:
        now = datetime.now(timezone.utc)
        cached = _cache.get(currency)
        if cached and now - cached[1] < timedelta(seconds=60):
            return cached[0]
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4), trust_env=False) as session:
                async with session.get(f'https://api.coinbase.com/v2/prices/{currency}-USD/spot', allow_redirects=False) as response:
                    if response.status != 200:
                        return None
                    amount = parse_quote(await response.json(), currency)
            _cache[currency] = (amount, datetime.now(timezone.utc))
            return amount
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError, InvalidOperation, OverflowError):
            return None
