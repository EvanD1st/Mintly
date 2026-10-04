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
        watch = await db.scalar(select(CopyWatch).where(CopyWatch.archived_at.is_(None))
            .order_by(CopyWatch.updated_at, CopyWatch.id).limit(1))
        if not watch:
            return False
        for chain in watch.chains:
            await scan_watch(db, watch, chain)
            await db.commit()
        return True


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
