"""Public operations hire/booking request API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.model.operations.operations_service_request_dto import (
    OperationsPaymentOrderBody,
    OperationsPaymentVerifyBody,
    OperationsServiceRequestCreateBody,
)
from app.service.operations.operations_service_request_service import (
    OperationsServiceRequestService,
)

router = APIRouter(prefix="/api/v1/operations/requests", tags=["Operations Requests"])


def _get_service(db: AsyncSession = Depends(get_async_db)) -> OperationsServiceRequestService:
    return OperationsServiceRequestService(db)


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_operations_request(
    body: OperationsServiceRequestCreateBody,
    service: OperationsServiceRequestService = Depends(_get_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    item = await service.submit(body, user=current_user)
    return {
        "success": True,
        "message": "Operations request submitted",
        "data": item,
    }


@router.post("/order")
async def create_booking_order(
    body: OperationsPaymentOrderBody,
    service: OperationsServiceRequestService = Depends(_get_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await service.create_payment_order(body, user=current_user)


@router.post("/verify")
async def verify_booking_payment(
    body: OperationsPaymentVerifyBody,
    service: OperationsServiceRequestService = Depends(_get_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await service.verify_payment(body, user=current_user)


@router.get("/me")
async def list_my_operations_requests(
    service: OperationsServiceRequestService = Depends(_get_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    items = await service.list_for_user(user=current_user)
    return {"data": items}
