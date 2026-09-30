"""Admin-provisioned accounts and revocable user sessions."""

from datetime import datetime, timedelta, timezone
import hashlib
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_authenticated_user, get_db, require_admin
from app.models import ActivityEvent, AuthSession, LoginAttempt, NotificationDevice, User, WalletPairing
from app.services.auth import (
    generate_temporary_password, hash_password, new_session_token,
    token_digest, verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])
USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,63}$")


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class AdminCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    admin_password: str = Field(min_length=1, max_length=256)


class AdminConfirmRequest(BaseModel):
    admin_password: str = Field(min_length=1, max_length=256)


def public_user(user: User) -> dict:
    return {
        "id": user.id, "username": user.username, "role": user.role,
        "must_change_password": user.must_change_password,
    }


async def revoke_sessions(db: AsyncSession, user_id: str) -> None:
    await db.execute(update(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None),
    ).values(revoked_at=datetime.now(timezone.utc)))


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    username = req.username.strip().lower()
    name_hash = hashlib.sha256(username.encode()).hexdigest()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    await db.execute(delete(LoginAttempt).where(LoginAttempt.attempted_at < cutoff))
    attempts = (await db.execute(select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.username_hash == name_hash,
    ))).scalar_one()
    if attempts >= 5:
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    valid = verify_password(user.password_hash if user else None, req.password)
    if not valid or user is None or not user.is_active or user.deleted_at is not None:
        db.add(LoginAttempt(username_hash=name_hash))
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    await db.execute(delete(LoginAttempt).where(LoginAttempt.username_hash == name_hash))
    token = new_session_token()
    expires = datetime.now(timezone.utc) + timedelta(hours=12 if user.role == "admin" else 24 * 7)
    db.add(AuthSession(user_id=user.id, token_hash=token_digest(token), expires_at=expires))
    await db.commit()
    return {"token": token, "expires_at": expires, "user": public_user(user)}


@router.get("/me")
async def me(user: User = Depends(get_authenticated_user)):
    return public_user(user)


@router.post("/logout")
async def logout(
    user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    await revoke_sessions(db, user.id)
    await db.commit()
    return {"status": "ok"}


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(user.password_hash, req.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if req.current_password == req.new_password:
        raise HTTPException(status_code=400, detail="Choose a different password.")
    user.password_hash = hash_password(req.new_password)
    user.must_change_password = False
    await revoke_sessions(db, user.id)
    await db.commit()
    return {"status": "ok", "message": "Password changed. Sign in again."}


@admin_router.get("/users")
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    users = (await db.execute(select(User).where(User.deleted_at.is_(None)).order_by(User.username))).scalars().all()
    return {"users": [public_user(user) for user in users]}


@admin_router.post("/users")
async def create_user(
    req: AdminCreateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(admin.password_hash, req.admin_password):
        raise HTTPException(status_code=403, detail="Admin password is incorrect.")
    username = req.username.strip().lower()
    if not USERNAME_PATTERN.fullmatch(username):
        raise HTTPException(status_code=400, detail="Use 3–64 lowercase letters, digits, dots, underscores, or hyphens; start with a letter.")
    if (await db.execute(select(User.id).where(User.username == username))).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username already exists.")
    temporary_password = generate_temporary_password()
    user = User(username=username, password_hash=hash_password(temporary_password),
                role="member", is_active=True, must_change_password=True)
    db.add(user)
    db.add(ActivityEvent(user_id=admin.id, event_type="account_created", label="Account created",
                         detail=username, icon_name="user-plus", is_demo=False))
    await db.commit()
    return {"user": public_user(user), "temporary_password": temporary_password}


@admin_router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    req: AdminConfirmRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(admin.password_hash, req.admin_password):
        raise HTTPException(status_code=403, detail="Admin password is incorrect.")
    user = (await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))).scalar_one_or_none()
    if user is None or user.role == "admin":
        raise HTTPException(status_code=404, detail="Member account not found.")
    temporary_password = generate_temporary_password()
    user.password_hash = hash_password(temporary_password)
    user.must_change_password = True
    await revoke_sessions(db, user.id)
    await db.execute(update(NotificationDevice).where(NotificationDevice.user_id == user.id).values(is_active=False))
    db.add(ActivityEvent(user_id=admin.id, event_type="password_reset", label="Password reset",
                         detail=user.username, icon_name="key", is_demo=False))
    await db.commit()
    return {"user": public_user(user), "temporary_password": temporary_password}


@admin_router.post("/users/{user_id}/delete")
async def delete_user(
    user_id: str,
    req: AdminConfirmRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(admin.password_hash, req.admin_password):
        raise HTTPException(status_code=403, detail="Admin password is incorrect.")
    user = (await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))).scalar_one_or_none()
    if user is None or user.role == "admin":
        raise HTTPException(status_code=404, detail="Member account not found.")
    user.is_active = False
    user.deleted_at = datetime.now(timezone.utc)
    await revoke_sessions(db, user.id)
    await db.execute(update(NotificationDevice).where(NotificationDevice.user_id == user.id).values(is_active=False))
    await db.execute(delete(WalletPairing).where(WalletPairing.user_id == user.id))
    db.add(ActivityEvent(user_id=admin.id, event_type="account_deleted", label="Account deleted",
                         detail=user.username, icon_name="user-x", is_demo=False))
    await db.commit()
    return {"status": "ok"}
