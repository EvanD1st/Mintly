"""Database and mandatory per-user authorization dependencies."""

from datetime import datetime, timezone, timedelta

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.user import AuthSession, User
from app.models.device_session import DeviceSession
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
    if session.device_session_id:
        from app.services.mint_plans import aware
        family=await db.get(DeviceSession,session.device_session_id)
        now=datetime.now(timezone.utc)
        if not family or family.user_id!=user.id or family.revoked_at or aware(family.expires_at)<=now:
            raise HTTPException(401,'Remembered session expired. Sign in again.')
        if aware(family.last_used_at)<now-timedelta(hours=1):
            # Finish these short locks before any endpoint takes the execution lock.
            user=await db.scalar(select(User).where(User.id==user.id).with_for_update().execution_options(populate_existing=True))
            family=await db.scalar(select(DeviceSession).where(DeviceSession.id==family.id).with_for_update().execution_options(populate_existing=True))
            if not user.is_active or user.deleted_at or family.revoked_at or aware(family.expires_at)<=now:
                raise HTTPException(401,'Remembered session expired. Sign in again.')
            family.last_used_at=now;family.expires_at=now+timedelta(days=90)
            await db.commit()
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
