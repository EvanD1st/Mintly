from fastapi import APIRouter,Depends,Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import require_admin,get_db
from app.services.reliability import report

router=APIRouter(prefix='/admin/reliability',tags=['admin'])


@router.get('')
async def reliability(hours:int=Query(24,ge=1,le=168),admin=Depends(require_admin),db:AsyncSession=Depends(get_db)):
    return await report(db,hours=hours)
