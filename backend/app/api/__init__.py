"""API routers package."""

from fastapi import APIRouter, Depends
from app.api.deps import verify_owner_authorization
from app.api.drops import router as drops_router
from app.api.import_routes import router as import_router
from app.api.tasks import router as tasks_router
from app.api.wallets import router as wallets_router
from app.api.source import router as source_router
from app.api.notifications import router as notifications_router

api_router = APIRouter(prefix="/api", dependencies=[Depends(verify_owner_authorization)])
api_router.include_router(drops_router)
api_router.include_router(import_router)
api_router.include_router(tasks_router)
api_router.include_router(wallets_router)
api_router.include_router(source_router)
api_router.include_router(notifications_router)

__all__ = ["api_router"]
