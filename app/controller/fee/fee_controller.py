"""User-facing fee API (Java FeeController — /api/v1/fee)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.model.common.payment_request import RazorpayVerifyRequest
from app.service.fee.fee_service import FeeService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/fee", tags=["Fee"])


async def get_fee_service(db: AsyncSession = Depends(get_async_db)) -> FeeService:
    return FeeService(db)


@router.get("/my-requests")
async def my_fee_requests(
    service: FeeService = Depends(get_fee_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.list_my_requests(current_user)


@router.post("/requests/{request_id}/create-order")
async def create_fee_order(
    request_id: uuid.UUID,
    service: FeeService = Depends(get_fee_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.create_order(request_id, lister=current_user)


@router.post("/requests/{request_id}/verify")
async def verify_fee(
    request_id: uuid.UUID,
    body: RazorpayVerifyRequest,
    service: FeeService = Depends(get_fee_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.verify(
        request_id,
        razorpay_payment_id=body.razorpay_payment_id,
        razorpay_order_id=body.razorpay_order_id,
        razorpay_signature=body.razorpay_signature,
        lister=current_user,
    )


@router.post("/requests/{request_id}/cancel")
async def cancel_fee(
    request_id: uuid.UUID,
    service: FeeService = Depends(get_fee_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.cancel(request_id, lister=current_user)
