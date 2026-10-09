"""API routers package."""

from fastapi import APIRouter, Depends
from app.api.automatic import router as automatic_router
from app.api.deps import get_current_user
from app.api.auth import router as auth_router, admin_router
from app.api.drops import router as drops_router
from app.api.import_routes import router as import_router
from app.api.tasks import router as tasks_router
from app.api.wallets import router as wallets_router, public_router as wallet_public_router
from app.api.source import router as source_router
from app.api.notifications import router as notifications_router
from app.api.mint_plans import router as mint_plans_router
from app.api.mint_permissions import router as permission_router, public_router as permission_public_router

from app.api.history import router as history_router
from app.api.copy_mints import router as copy_router
from app.api.opensea_access import router as opensea_access_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(wallet_public_router)
api_router.include_router(permission_public_router)
protected = APIRouter(dependencies=[Depends(get_current_user)])
protected.include_router(history_router)
protected.include_router(copy_router)
protected.include_router(automatic_router)
protected.include_router(drops_router)
protected.include_router(import_router)
protected.include_router(tasks_router)
protected.include_router(opensea_access_router)
protected.include_router(wallets_router)
protected.include_router(source_router)
protected.include_router(notifications_router)
protected.include_router(mint_plans_router)
protected.include_router(permission_router)
protected.include_router(admin_router)
api_router.include_router(protected)

__all__ = ["api_router"]
