"""Owner-controlled FCM device registrations and notification preferences."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, require_admin
from app.models import User
from app.models.activity import NotificationDevice
from app.services.notifier import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


class DeviceRegisterRequest(BaseModel):
    token: str = Field(min_length=20, max_length=255)
    platform: str = Field(default="android", pattern="^(android|ios)$")


class DevicePreferencesRequest(BaseModel):
    token: str = Field(min_length=20, max_length=255)
    daily_list: bool = True
    mint_status: bool = True
    source_health: bool = True


@router.post("/register")
async def register_device_token(req: DeviceRegisterRequest, db: AsyncSession = Depends(get_db),
                                user: User = Depends(get_current_user)):
    device = (await db.execute(select(NotificationDevice).where(
        NotificationDevice.device_token == req.token
    ))).scalar_one_or_none()
    if device is None:
        device = NotificationDevice(
            user_id=user.id, device_token=req.token, platform=req.platform, is_active=True,
            preferences={"daily_list": True, "mint_status": True, "source_health": True},
        )
        db.add(device)
    else:
        if device.user_id != user.id and device.is_active:
            raise HTTPException(status_code=409, detail="This device is already registered to another account.")
        if device.user_id != user.id:
            device.user_id = user.id
            device.preferences = {"daily_list": True, "mint_status": True, "source_health": True}
        device.platform = req.platform
        device.is_active = True
    await db.commit()
    return {"status": "ok", "preferences": device.preferences}


@router.post("/preferences")
async def update_device_preferences(req: DevicePreferencesRequest, db: AsyncSession = Depends(get_db),
                                    user: User = Depends(get_current_user)):
    device = (await db.execute(select(NotificationDevice).where(
        NotificationDevice.device_token == req.token,
        NotificationDevice.is_active.is_(True), NotificationDevice.user_id == user.id,
    ))).scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device is not registered.")
    device.preferences = req.model_dump(exclude={"token"})
    await db.commit()
    return {"status": "ok", "preferences": device.preferences}


@router.post("/unregister")
async def unregister_device_token(req: DeviceRegisterRequest, db: AsyncSession = Depends(get_db),
                                  user: User = Depends(get_current_user)):
    device = (await db.execute(select(NotificationDevice).where(
        NotificationDevice.device_token == req.token, NotificationDevice.user_id == user.id,
    ))).scalar_one_or_none()
    if device:
        device.is_active = False
        await db.commit()
    return {"status": "ok"}


@router.get("/recent")
async def get_recent_notifications(admin: User = Depends(require_admin)):
    return {"notifications": NotificationService.get_recent_notifications()}
