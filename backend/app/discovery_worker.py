"""X polling and feed display checks run outside mint execution processes."""
import asyncio,logging
from app.config import settings
from app.database import AsyncSessionLocal
from app.services.x_feed import sync_x_drops,process_pending
from app.services.feed_checks import step
from app.services.source_archive import run as archives

async def poll(source_name='lakzonevn'):
    while True:
        try:
            if settings.X_DISCOVERY_ENABLED:
                async with AsyncSessionLocal() as db:
                    await sync_x_drops(db,source_name=source_name)
        except Exception as error:logging.getLogger('mintly.discovery').warning('Discovery refresh failed (%s).',type(error).__name__)
        await asyncio.sleep(max(60,settings.X_DISCOVERY_INTERVAL_SECONDS))

async def checks():
    while True:
        try:await step(AsyncSessionLocal)
        except Exception as error:logging.getLogger('mintly.discovery').warning('Wallet display check failed (%s).',type(error).__name__)
        await asyncio.sleep(1)
async def inbox():
    while True:
        try:
            async with AsyncSessionLocal() as db:await process_pending(db)
        except Exception:logging.getLogger('mintly.discovery').warning('Saved source processing will retry.')
        await asyncio.sleep(1)
async def main():await asyncio.gather(poll('lakzonevn'),poll('cassio_sch'),inbox(),checks(),archives())
if __name__=='__main__':asyncio.run(main())
