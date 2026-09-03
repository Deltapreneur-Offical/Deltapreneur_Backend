"""Admin APIs for Hub Registrar Main Categories."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import require_role
from app.entity.user.app_user import AppUser
from app.model.hub_registrar.hub_registrar_category_request import (
    HubRegistrarCategoryCreateRequest,
    HubRegistrarCategoryUpdateRequest,
)
from app.service.hub_registrar.hub_registrar_category_service import (
    HubRegistrarCategoryService,
)

router = APIRouter(
    prefix="/api/v1/admin/hub-registrar/categories",
    tags=["Admin Hub Registrar Categories"],
)


def _get_service(db: AsyncSession = Depends(get_async_db)) -> HubRegistrarCategoryService:
    return HubRegistrarCategoryService(db)


@router.get("")
async def admin_list_categories(
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    service: HubRegistrarCategoryService = Depends(_get_service),
) -> dict:
    """List all non-deleted Main Categories for admin."""
    items = await service.list_admin()
    return {
        "success": True,
        "message": "Categories fetched",
        "data": items,
        "items": items,
    }


@router.get("/{category_id}")
async def admin_get_category(
    category_id: uuid.UUID,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    service: HubRegistrarCategoryService = Depends(_get_service),
) -> dict:
    """Get a single Main Category."""
    item = await service.get_admin(category_id)
    return {
        "success": True,
        "message": "Category fetched",
        "data": item,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def admin_create_category(
    body: HubRegistrarCategoryCreateRequest,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    service: HubRegistrarCategoryService = Depends(_get_service),
) -> dict:
    """Create a new Main Category."""
    item = await service.create_admin(body)
    return {
        "success": True,
        "message": "Category created",
        "data": item,
    }


@router.put("/{category_id}")
async def admin_update_category(
    category_id: uuid.UUID,
    body: HubRegistrarCategoryUpdateRequest,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    service: HubRegistrarCategoryService = Depends(_get_service),
) -> dict:
    """Update an existing Main Category."""
    item = await service.update_admin(category_id, body)
    return {
        "success": True,
        "message": "Category updated",
        "data": item,
    }


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def admin_delete_category(
    category_id: uuid.UUID,
    admin: AppUser = Depends(require_role(["ADMIN"])),
    service: HubRegistrarCategoryService = Depends(_get_service),
) -> Response:
    """Soft-delete a Main Category."""
    await service.delete_admin(category_id, deleted_by=admin.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
