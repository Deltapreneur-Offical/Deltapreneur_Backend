"""Public Hub Registrar categories API."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.public_list_cache import public_list_cache_get, public_list_cache_put
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
    cached = public_list_cache_get("hub-registrar:categories")
    if cached is not None:
        return cached
    items = await service.list_public()
    payload = {
        "success": True,
        "message": "Categories fetched",
        "data": items,
        "items": items,
    }
    public_list_cache_put("hub-registrar:categories", payload)
    return payload
