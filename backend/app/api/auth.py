"""Admin-provisioned accounts and revocable user sessions."""

from datetime import datetime, timedelta, timezone
import hashlib
import re

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_authenticated_user, get_db, require_admin
from app.models import ActivityEvent, AuthSession, LoginAttempt, NotificationDevice, User, WalletPairing, DeviceSession, AccountRecoveryCode
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
    await db.execute(select(User.id).where(User.id==user_id).with_for_update())
    now=datetime.now(timezone.utc)
    await db.execute(update(AccountRecoveryCode).where(
        or_(AccountRecoveryCode.user_id == user_id, AccountRecoveryCode.issued_by == user_id),
        AccountRecoveryCode.used_at.is_(None), AccountRecoveryCode.revoked_at.is_(None),
    ).values(revoked_at=now))
    await db.execute(update(DeviceSession).where(DeviceSession.user_id==user_id,
        DeviceSession.revoked_at.is_(None)).values(revoked_at=now))
    await db.execute(update(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None),
    ).values(revoked_at=now))


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    return await authenticate_password(req,db)


async def authenticate_password(req,db,origin=None):
    from app.services.account_recovery import CODE_PATTERN, consume_recovery_code
    if origin is not None:
        from app.services.device_sessions import allowed_origin
        allowed_origin(origin)
    username = req.username.strip().lower()
    name_hash = hashlib.sha256(username.encode()).hexdigest()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    await db.execute(delete(LoginAttempt).where(LoginAttempt.attempted_at < cutoff))
    attempts = (await db.execute(select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.username_hash == name_hash,
    ))).scalar_one()
    recovery_candidate = bool(CODE_PATTERN.fullmatch(req.password))
    if attempts >= 5 and not recovery_candidate:
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")
    user = (await db.execute(select(User).where(User.username == username).with_for_update()
        .execution_options(populate_existing=True))).scalar_one_or_none()
    if recovery_candidate:
        # Valid high-entropy codes allow recovery during a password lockout.
        valid = bool(user and user.role == 'member' and user.is_active and not user.deleted_at
            and not user.must_change_password and await consume_recovery_code(db, user, req.password))
        if attempts >= 5 and not valid:
            raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")
        if not valid:
            # A real password may happen to use the recovery-code format.
            valid = verify_password(user.password_hash if user else None, req.password)
    else:
        valid = verify_password(user.password_hash if user else None, req.password)
    if not valid or user is None or not user.is_active or user.deleted_at is not None:
        db.add(LoginAttempt(username_hash=name_hash))
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    await db.execute(delete(LoginAttempt).where(LoginAttempt.username_hash == name_hash))
    if origin is not None:
        from app.services.device_sessions import issue
        return await issue(db,user,origin)
    token = new_session_token()
    expires = datetime.now(timezone.utc) + timedelta(hours=12 if user.role == "admin" else 24 * 7)
    db.add(AuthSession(user_id=user.id, token_hash=token_digest(token), expires_at=expires))
    await db.commit()
    return {"token": token, "expires_at": expires, "user": public_user(user)}


class DeviceLogin(LoginRequest):
    origin: str = Field(max_length=250)
    protocol: int = Field(default=2,ge=2,le=2)

class DeviceRefresh(BaseModel):
    device_session_id: str = Field(min_length=36,max_length=36)
    refresh_token: str = Field(min_length=32,max_length=256)
    request_id: str = Field(min_length=32,max_length=64)
    origin: str = Field(max_length=250)

class RememberDevice(BaseModel):
    origin: str = Field(max_length=250)

@router.post('/device-login')
async def device_login(req:DeviceLogin,db:AsyncSession=Depends(get_db)):
    return await authenticate_password(req,db,req.origin)

@router.post('/device-remember')
async def remember_device(req:RememberDevice,user:User=Depends(get_authenticated_user),db:AsyncSession=Depends(get_db),authorization:str=Header()):
    from app.services.device_sessions import issue
    user=await db.scalar(select(User).where(User.id==user.id).with_for_update().execution_options(populate_existing=True))
    if not user.is_active or user.deleted_at:raise HTTPException(401,'Account unavailable.')
    session=await db.scalar(select(AuthSession).where(AuthSession.token_hash==token_digest(authorization[7:]),
        AuthSession.user_id==user.id,AuthSession.revoked_at.is_(None),AuthSession.expires_at>datetime.now(timezone.utc)))
    if not session:raise HTTPException(401,'Session expired. Sign in again.')
    return await issue(db,user,req.origin)

@router.post('/device-refresh')
async def device_refresh(req:DeviceRefresh,db:AsyncSession=Depends(get_db)):
    from app.services.device_sessions import rotate
    return await rotate(db,req.device_session_id,req.refresh_token,req.request_id,req.origin)


@router.post('/session-only')
async def session_only(user: User = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db),
                       authorization: str = Header()):
    """Keep a login when saving its remembered credential fails or is cancelled."""
    user = await db.scalar(select(User).where(User.id == user.id).with_for_update()
        .execution_options(populate_existing=True))
    if not user or not user.is_active or user.deleted_at:
        raise HTTPException(401, 'Account unavailable.')
    now = datetime.now(timezone.utc)
    session = await db.scalar(select(AuthSession).where(
        AuthSession.token_hash == token_digest(authorization[7:]), AuthSession.user_id == user.id,
        AuthSession.revoked_at.is_(None), AuthSession.expires_at > now).with_for_update()
        .execution_options(populate_existing=True))
    if not session:
        raise HTTPException(401, 'Session expired. Sign in again.')
    if session.device_session_id:
        from app.services.device_sessions import revoke_family
        family = await db.scalar(select(DeviceSession).where(DeviceSession.id == session.device_session_id)
            .with_for_update().execution_options(populate_existing=True))
        from app.services.mint_plans import aware
        if not family or family.user_id != user.id or family.revoked_at or aware(family.expires_at) <= now:
            raise HTTPException(401, 'Remembered session expired. Sign in again.')
        await revoke_family(db, family, now)
    else:
        session.revoked_at = now
    token = new_session_token()
    expires = now + timedelta(hours=12 if user.role == 'admin' else 168)
    db.add(AuthSession(user_id=user.id, token_hash=token_digest(token), expires_at=expires))
    await db.commit()
    return {'token': token, 'expires_at': expires, 'user': public_user(user)}

@router.post('/device-revoke')
async def device_revoke(req:DeviceRefresh,db:AsyncSession=Depends(get_db)):
    from app.services.device_sessions import rotate
    return await rotate(db,req.device_session_id,req.refresh_token,req.request_id,req.origin,revoke=True)


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


@router.post('/sign-out')
async def sign_out(
    user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
    authorization: str = Header(),
):
    """Retire this bearer only; saved device families require explicit removal."""
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    await db.execute(update(AuthSession).where(
        AuthSession.user_id == user.id,
        AuthSession.token_hash == token_digest(authorization[7:]),
    ).values(revoked_at=datetime.now(timezone.utc)))
    await db.commit()
    return {'status': 'ok'}


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    user=await db.scalar(select(User).where(User.id==user.id).with_for_update().execution_options(populate_existing=True))
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


@admin_router.post('/users/{user_id}/recovery-code')
async def create_recovery_code(
    user_id: str,
    req: AdminConfirmRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.services.account_recovery import issue_recovery_code
    # Use the same member -> administrator lock order as recovery redemption.
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update()
        .execution_options(populate_existing=True))
    if not user or user.role != 'member' or not user.is_active or user.deleted_at or user.must_change_password:
        raise HTTPException(404, 'Active member with an established password not found.')
    # Serialize fresh confirmation attempts and recheck the administrator state.
    admin = await db.scalar(select(User).where(User.id == admin.id).with_for_update()
        .execution_options(populate_existing=True))
    if not admin or admin.role != 'admin' or not admin.is_active or admin.deleted_at or admin.must_change_password:
        raise HTTPException(403, 'Admin access required.')
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    name_hash = token_digest('recovery-confirm:' + admin.id)
    attempts = await db.scalar(select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.username_hash == name_hash, LoginAttempt.attempted_at > cutoff))
    if attempts >= 5:
        raise HTTPException(429, 'Too many recovery confirmation attempts. Try again later.')
    if not verify_password(admin.password_hash, req.admin_password):
        db.add(LoginAttempt(username_hash=name_hash))
        await db.commit()
        raise HTTPException(403, 'Admin password is incorrect.')
    await db.execute(delete(LoginAttempt).where(LoginAttempt.username_hash == name_hash))
    code, expires_at = await issue_recovery_code(db, user, admin)
    await db.commit()
    return {'user': public_user(user), 'recovery_code': code, 'expires_at': expires_at,
        'instructions': 'Sign in with this username and use the recovery code in the password field. '
            'Valid once for 10 minutes. Your existing password is unchanged.'}


@admin_router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    req: AdminConfirmRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(admin.password_hash, req.admin_password):
        raise HTTPException(status_code=403, detail="Admin password is incorrect.")
    user = (await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)).with_for_update())).scalar_one_or_none()
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
    user = (await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)).with_for_update())).scalar_one_or_none()
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
