"""Opaque refresh rotation with a bounded identical-request recovery window."""
import base64,hashlib,hmac,uuid
from datetime import datetime,timezone,timedelta
from fastapi import HTTPException
from sqlalchemy import select,update
from app.config import settings
from app.models import DeviceSession,DeviceRefreshUse,AuthSession,User
from app.services.auth import token_digest,new_session_token
from app.services.mint_plans import aware

def allowed_origin(origin):
    if origin!=settings.PUBLIC_URL.rstrip('/')+'/api':
        raise HTTPException(400,'This remembered session belongs to another server.')

def tokens(row,request_id):
    def derive(kind):
        message=f'mintly/device/v1/{kind}/{row.id}/{row.generation}/{request_id}'.encode()
        return base64.urlsafe_b64encode(hmac.new(settings.APP_SECRET_KEY.encode(),message,hashlib.sha256).digest()).decode().rstrip('=')
    return derive('refresh'),derive('access')

def response(row,refresh,access,user):
    from app.api.auth import public_user
    return dict(token=access,expires_at=aware(row.access_expires_at),user=public_user(user),
        refresh_token=refresh,device_session_id=row.id,remembered_expires_at=aware(row.expires_at),origin=row.origin)

async def issue(db,user,origin):
    allowed_origin(origin)
    if not settings.REMEMBERED_LOGIN_ISSUANCE_ENABLED:
        raise HTTPException(503,'Remembered login is temporarily unavailable. Use password login.')
    now=datetime.now(timezone.utc);refresh,access=new_session_token(),new_session_token()
    row=DeviceSession(id=str(uuid.uuid4()),user_id=user.id,origin=origin,token_hash=token_digest(refresh),
        generation=0,last_used_at=now,expires_at=now+timedelta(days=90),
        access_expires_at=now+timedelta(hours=12 if user.role=='admin' else 168))
    db.add(row);await db.flush()
    db.add(AuthSession(user_id=user.id,token_hash=token_digest(access),expires_at=row.access_expires_at,device_session_id=row.id))
    await db.commit();return response(row,refresh,access,user)

async def revoke_family(db,row,now):
    row.revoked_at=now
    await db.execute(update(AuthSession).where(AuthSession.device_session_id==row.id,
        AuthSession.revoked_at.is_(None)).values(revoked_at=now))

async def rotate(db,family_id,refresh,request_id,origin,*,revoke=False,now=None):
    allowed_origin(origin);now=now or datetime.now(timezone.utc)
    initial=await db.get(DeviceSession,family_id)
    if not initial:raise HTTPException(401,'Remembered login expired. Sign in with your password.')
    # Password/revocation writers take the same owner -> family order.
    user=await db.scalar(select(User).where(User.id==initial.user_id).with_for_update().execution_options(populate_existing=True))
    row=await db.scalar(select(DeviceSession).where(DeviceSession.id==family_id).with_for_update().execution_options(populate_existing=True))
    if row and user and (not user.is_active or user.deleted_at):
        await revoke_family(db,row,now);await db.commit()
        raise HTTPException(401,'Remembered account unavailable.')
    if not row or row.origin!=origin or not user:
        raise HTTPException(401,'Remembered account unavailable.')
    digest=token_digest(refresh);request_hash=token_digest(request_id)
    used=await db.get(DeviceRefreshUse,digest)
    if digest!=row.token_hash:
        if not used or used.family_id!=row.id:raise HTTPException(401,'Invalid remembered session.')
        recovery=bool(not revoke and not row.revoked_at and aware(row.expires_at)>now and
            row.rotated_at and timedelta(0)<=now-aware(row.rotated_at)<=timedelta(seconds=30) and
            row.last_request_hash==request_hash and used.generation==row.generation-1)
        if recovery:
            fresh,access=tokens(row,request_id)
            await db.commit();return response(row,fresh,access,user)
        await revoke_family(db,row,now);await db.commit()
        raise HTTPException(401,'Remembered session was reused. Sign in with your password.')
    if revoke:
        await revoke_family(db,row,now);await db.commit();return {'status':'ok'}
    if row.revoked_at or aware(row.expires_at)<=now:
        await revoke_family(db,row,now);await db.commit()
        raise HTTPException(401,'Remembered login expired. Sign in with your password.')
    db.add(DeviceRefreshUse(token_hash=digest,family_id=row.id,generation=row.generation,used_at=now))
    row.generation+=1;row.last_request_hash=request_hash;row.rotated_at=now;row.last_used_at=now
    row.expires_at=now+timedelta(days=90)
    row.access_expires_at=now+timedelta(hours=12 if user.role=='admin' else 168)
    fresh,access=tokens(row,request_id);row.token_hash=token_digest(fresh)
    db.add(AuthSession(user_id=user.id,token_hash=token_digest(access),expires_at=row.access_expires_at,device_session_id=row.id))
    await db.commit();return response(row,fresh,access,user)
