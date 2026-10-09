"""Pytest configuration and async test fixtures for Mintly."""

import pytest
import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.database import Base
from app.models import User
from app.services.auth import hash_password
import app.models  # load models

TEST_DB_URL = os.environ.get('MINTLY_TEST_DATABASE_URL', "sqlite+aiosqlite:///./test_mintly.db")
if not TEST_DB_URL.startswith('sqlite'):
    from sqlalchemy.engine import make_url
    _test_url = make_url(TEST_DB_URL)
    if _test_url.host not in ('127.0.0.1', 'localhost') or not _test_url.database.startswith('mintly_test'):
        raise RuntimeError('PostgreSQL tests require a disposable localhost mintly_test* database')




@pytest.fixture(scope="function")
async def test_db():
    """Creates a fresh test database for each test run."""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        # The URL above is restricted to a disposable local test database.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add(User(username="admin", password_hash=hash_password("Admin test password 123"),
                         role="admin", is_active=True, must_change_password=False))
        session.add(User(username="member", password_hash=hash_password("Member test password 123"),
                         role="member", is_active=True, must_change_password=False))
        await session.commit()
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()
    if TEST_DB_URL.startswith('sqlite') and os.path.exists("./test_mintly.db"):
        try:
            os.remove("./test_mintly.db")
        except Exception:
            pass


@pytest.fixture(autouse=True)
def isolate_opensea_memory_caches():
    from app.services.opensea import _drop_cache,_verified_mints
    _drop_cache.clear();_verified_mints.clear()
    yield
    _drop_cache.clear();_verified_mints.clear()
