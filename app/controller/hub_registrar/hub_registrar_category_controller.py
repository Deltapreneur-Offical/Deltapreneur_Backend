"""Public Hub Registrar categories API."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.service.hub_registrar.hub_registrar_category_service import (
    HubRegistrarCategoryService,
)

router = APIRouter(
    prefix="/api/v1/hub-registrar/categories",
    tags=["Hub Registrar Categories"],
)


def _get_service(db: AsyncSession = Depends(get_async_db)) -> HubRegistrarCategoryService:
    return HubRegistrarCategoryService(db)


@router.get("")
async def list_categories(
    service: HubRegistrarCategoryService = Depends(_get_service),
) -> dict:
    """Return all active, non-deleted Hub Registrar categories for the public website."""
    items = await service.list_public()
    return {
        "success": True,
        "message": "Categories fetched",
        "data": items,
        "items": items,
    }
