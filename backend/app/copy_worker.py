"""Dedicated public mint observer; contains no private keys or vault mounts."""
import asyncio
from datetime import datetime, timezone
import logging
from pathlib import Path
import tempfile
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import CopyWatch
from app.services.copy_mints import enabled, scan_watch


async def step(session_factory=AsyncSessionLocal):
    enabled()
    async with session_factory() as db:
        watches = (await db.scalars(select(CopyWatch).where(CopyWatch.archived_at.is_(None))
            .order_by(CopyWatch.updated_at, CopyWatch.id).limit(100))).all()
        pairs = [(watch.id, chain) for watch in watches for chain in watch.chains]
    slots = asyncio.Semaphore(4)
    async def scan_pair(watch_id, chain):
        async with slots:
            try:
                async with session_factory() as db:
                    watch = await db.get(CopyWatch, watch_id)
                    if watch and not watch.archived_at:
                        await scan_watch(db, watch, chain)
                        await db.commit()
            except Exception:
                logging.error('Copy pair unavailable; durable observations retained.')
    await asyncio.gather(*(scan_pair(wid, chain) for wid, chain in pairs))
    return bool(pairs)


async def run():
    enabled()
    while True:
        try:
            await step()
            (Path(tempfile.gettempdir()) / 'mintly-copy.heartbeat').touch()
        except Exception:
            logging.error('Public mint observation unavailable; cursor and spending records retained.')
        await asyncio.sleep(5)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
