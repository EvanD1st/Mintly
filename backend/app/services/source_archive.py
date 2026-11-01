"""Bounded public-source backups, excluding sessions, wallets and signer state."""
import asyncio,gzip,json,os
from datetime import datetime,timezone,timedelta
from pathlib import Path
from sqlalchemy import select
from app.models import SourcePost,SourceRevision
from app.config import settings
from app.database import AsyncSessionLocal


async def snapshot(factory=AsyncSessionLocal,*,directory=None,now=None):
    destination=directory or settings.SOURCE_ARCHIVE_DIR
    if not destination:return None
    root=Path(destination).resolve()
    if not root.is_dir():raise RuntimeError('Protected source archive directory is unavailable')
    now=now or datetime.now(timezone.utc)
    final=root/f"source-inbox-{now:%Y%m%d%H}.jsonl.gz"
    if final.exists():return final
    temporary=root/(final.name+'.tmp')
    # The configured folder and restrictive modes keep public-source archives separate
    # from credentials. Exact filenames and a fixed cap bound storage use.
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    try:
        with os.fdopen(fd,'wb') as output,gzip.GzipFile(fileobj=output,mode='wb') as archive:
            async with factory() as db:
                rows=await db.stream(select(SourcePost.post_id,SourcePost.author_username,SourcePost.posted_at,
                    SourceRevision.content_hash,SourceRevision.raw_text,SourceRevision.expanded_text)
                    .join(SourceRevision,SourceRevision.post_id==SourcePost.id)
                    .where(SourceRevision.created_at>=now-timedelta(days=14),SourcePost.is_manual_import.is_(False),
                        SourcePost.author_username.in_(('lakzonevn','cassio_sch'))))
                async for row in rows:
                    archive.write((json.dumps(dict(row._mapping),default=str,ensure_ascii=False)+'\n').encode())
            archive.flush()
        os.replace(temporary,final)
    except BaseException:
        if temporary.exists():temporary.unlink()
        raise
    files=sorted(root.glob('source-inbox-??????????.jsonl.gz'),reverse=True)
    kept=0
    for index,path in enumerate(files):
        if path.resolve().parent!=root:continue
        size=path.stat().st_size
        if index and (index>=48 or kept+size>128*1024*1024):path.unlink()
        else:kept+=size
    return final


async def run():
    while True:
        try:await snapshot()
        except Exception:
            import logging
            logging.getLogger('mintly.discovery').warning('Source archive backup failed; database inbox is retained.')
            try:
                from app.services.source_alerts import enqueue
                async with AsyncSessionLocal() as db:await enqueue(db,'source-archive',
                    'Source archive backup failed. The database inbox is retained; check archive storage.')
            except Exception:pass
        await asyncio.sleep(3600)
