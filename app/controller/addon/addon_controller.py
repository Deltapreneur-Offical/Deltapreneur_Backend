"""Admin addon orders API."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import require_role
from app.entity.user.app_user import AppUser
from app.service.addon.addon_admin_service import AddonAdminService

router = APIRouter(prefix="/api/v1/addon", tags=["Addon"])


async def get_addon_service(db: AsyncSession = Depends(get_async_db)) -> AddonAdminService:
    return AddonAdminService(db)


@router.get("/admin/all")
async def admin_list_addon_orders(
    service: AddonAdminService = Depends(get_addon_service),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await service.list_addon_orders()
