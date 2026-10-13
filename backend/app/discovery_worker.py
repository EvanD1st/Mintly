"""X polling and feed display checks run outside mint execution processes."""
import asyncio,logging
from app.config import settings
from app.database import AsyncSessionLocal
from app.services.x_feed import sync_x_drops
from app.services.feed_checks import step
from app.services.notifier import NotificationService

async def poll():
    while True:
        try:
            if settings.X_DISCOVERY_ENABLED:
                async with AsyncSessionLocal() as db:
                    count=await sync_x_drops(db)
                if count:await NotificationService.send_notification(title='New daily mint list',
                    body=f'{count} new collections from @lakzonevn are available to review.',category='daily_list',deep_link='mintly://drops')
        except Exception as error:logging.getLogger('mintly.discovery').warning('Discovery refresh failed (%s).',type(error).__name__)
        await asyncio.sleep(max(60,settings.X_DISCOVERY_INTERVAL_SECONDS))

async def checks():
    while True:
        try:await step(AsyncSessionLocal)
        except Exception as error:logging.getLogger('mintly.discovery').warning('Wallet display check failed (%s).',type(error).__name__)
        await asyncio.sleep(1)
async def main():await asyncio.gather(poll(),checks())
if __name__=='__main__':asyncio.run(main())
