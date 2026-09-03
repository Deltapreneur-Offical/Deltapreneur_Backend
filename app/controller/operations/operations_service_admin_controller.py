"""Admin APIs for operations virtual-assistant services."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import require_role
from app.entity.user.app_user import AppUser
from app.model.operations.operations_service_request import (
    OperationsServiceAvailabilityRequest,
    OperationsServiceCreateRequest,
    OperationsServiceUpdateRequest,
)
from app.service.operations.operations_service_service import OperationsServiceService

router = APIRouter(
    prefix="/api/v1/admin/operations-services",
    tags=["Admin Operations Services"],
)


def _get_service(db: AsyncSession = Depends(get_async_db)) -> OperationsServiceService:
    return OperationsServiceService(db)


@router.get("")
async def admin_list_operations_services(
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    service: OperationsServiceService = Depends(_get_service),
) -> dict:
    items = await service.list_admin()
    return {
        "success": True,
        "message": "Operations services fetched",
        "data": items,
        "items": items,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def admin_create_operations_service(
    body: OperationsServiceCreateRequest,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    service: OperationsServiceService = Depends(_get_service),
) -> dict:
    item = await service.create_admin(body)
    return {
        "success": True,
        "message": "Operations service created",
        "data": item,
    }


@router.put("/{service_id}")
async def admin_update_operations_service(
    service_id: uuid.UUID,
    body: OperationsServiceUpdateRequest,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    service: OperationsServiceService = Depends(_get_service),
) -> dict:
    item = await service.update_admin(service_id, body)
    return {
        "success": True,
        "message": "Operations service updated",
        "data": item,
    }


@router.patch("/{service_id}/availability")
async def admin_patch_operations_service_availability(
    service_id: uuid.UUID,
    body: OperationsServiceAvailabilityRequest,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    service: OperationsServiceService = Depends(_get_service),
) -> dict:
    item = await service.patch_availability_admin(service_id, body)
    return {
        "success": True,
        "message": "Operations service availability updated",
        "data": item,
    }


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def admin_delete_operations_service(
    service_id: uuid.UUID,
    admin: AppUser = Depends(require_role(["ADMIN"])),
    service: OperationsServiceService = Depends(_get_service),
) -> Response:
    await service.delete_admin(service_id, deleted_by=admin.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
