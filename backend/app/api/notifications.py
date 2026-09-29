"""Notification endpoints for FCM device tokens and testing."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.models.activity import NotificationDevice
from app.services.notifier import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


class DeviceRegisterRequest(BaseModel):
    token: str
    platform: str = "android"


@router.post("/register")
async def register_device_token(req: DeviceRegisterRequest, db: AsyncSession = Depends(get_db)):
    """Registers an Android FCM device token for push notifications."""
    stmt = select(NotificationDevice).where(NotificationDevice.device_token == req.token)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if not existing:
        dev = NotificationDevice(
            device_token=req.token,
            platform=req.platform,
            is_active=True,
        )
        db.add(dev)
        await db.commit()
    return {"status": "ok", "message": "Device registered successfully."}


@router.get("/recent")
async def get_recent_notifications():
    """Returns recent notification logs from local sink."""
    return {"notifications": NotificationService.get_recent_notifications()}
