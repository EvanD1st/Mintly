"""Pytest configuration and async test fixtures for Mintly."""

import pytest
import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.database import Base
from app.services.seed import seed_initial_data
import app.models  # load models

TEST_DB_URL = "sqlite+aiosqlite:///./test_mintly.db"




@pytest.fixture(scope="function")
async def test_db():
    """Creates a fresh test database for each test run."""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await seed_initial_data(session)
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()
    if os.path.exists("./test_mintly.db"):
        try:
            os.remove("./test_mintly.db")
        except Exception:
            pass
