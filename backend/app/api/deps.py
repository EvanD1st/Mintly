"""API Dependencies for Mintly."""

from typing import AsyncGenerator
from fastapi import Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal
from app.config import settings


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Database session dependency."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def verify_owner_authorization(authorization: str = Header(None)) -> str:
    """Verifies single-user owner authentication for API mutations."""
    # In development/local mode with private single-user deployment
    if settings.DEBUG:
        return "owner_jenny"
    
    if not authorization or authorization != f"Bearer {settings.APP_SECRET_KEY}":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing owner authorization token."
        )
    return "owner_jenny"
