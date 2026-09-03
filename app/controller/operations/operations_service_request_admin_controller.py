"""Admin APIs for operations hire/booking requests."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import require_role
from app.entity.user.app_user import AppUser
from app.model.operations.operations_service_request_dto import (
    OperationsServiceRequestStatusBody,
)
from app.service.operations.operations_service_request_service import (
    OperationsServiceRequestService,
)

router = APIRouter(
    prefix="/api/v1/admin/operations-requests",
    tags=["Admin Operations Requests"],
)


def _get_service(db: AsyncSession = Depends(get_async_db)) -> OperationsServiceRequestService:
    return OperationsServiceRequestService(db)


@router.get("")
async def admin_list_operations_requests(
    request_type: str | None = Query(None, alias="requestType"),
    status: str | None = Query(None),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    service: OperationsServiceRequestService = Depends(_get_service),
) -> dict[str, Any]:
    items = await service.list_admin(request_type=request_type, status=status)
    return {
        "success": True,
        "message": "Operations requests fetched",
        "data": items,
        "items": items,
    }


@router.patch("/{request_id}")
async def admin_patch_operations_request_status(
    request_id: uuid.UUID,
    body: OperationsServiceRequestStatusBody,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    service: OperationsServiceRequestService = Depends(_get_service),
) -> dict[str, Any]:
    item = await service.patch_status_admin(request_id, body)
    return {
        "success": True,
        "message": "Operations request updated",
        "data": item,
    }


@router.delete("/{request_id}")
async def admin_delete_operations_request(
    request_id: uuid.UUID,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    service: OperationsServiceRequestService = Depends(_get_service),
) -> dict[str, Any]:
    await service.delete_admin(request_id)
    return {
        "success": True,
        "message": "Operations request deleted",
    }
