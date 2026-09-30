"""Database and mandatory per-user authorization dependencies."""

from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.user import AuthSession, User
from app.services.auth import token_digest


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_authenticated_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in required.")
    token = authorization[7:]
    if not token or len(token) > 256:
        raise HTTPException(status_code=401, detail="Invalid session.")
    session = (await db.execute(select(AuthSession).where(
        AuthSession.token_hash == token_digest(token),
        AuthSession.revoked_at.is_(None),
    ))).scalar_one_or_none()
    if session is None or session.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired. Sign in again.")
    user = (await db.execute(select(User).where(User.id == session.user_id))).scalar_one_or_none()
    if user is None or not user.is_active or user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="Account unavailable.")
    return user


async def get_current_user(user: User = Depends(get_authenticated_user)) -> User:
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Change your temporary password first.")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


# Existing endpoint names continue to resolve to a real user, never a shared token.
verify_owner_authorization = get_current_user
