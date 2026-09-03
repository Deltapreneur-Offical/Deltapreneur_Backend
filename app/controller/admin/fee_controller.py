from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.model.common.payment_request import RazorpayVerifyRequest
from app.service.payment.fee_service import FeeService

# Empty admin router kept for future admin fee endpoints.
router = APIRouter(
    prefix="/api/v1/admin/fees",
    tags=["Admin Fees"],
)

# Legacy participation-fee compat (same paths as CoBrother /api/v1/fee).
# Mounted only in tests — production uses app.controller.fee.fee_controller.
compat_router = APIRouter(
    prefix="/api/v1/fee",
    tags=["Fee (Compat)"],
)


async def get_fee_service(
    db: AsyncSession = Depends(get_async_db),
) -> FeeService:
    return FeeService(db)


@compat_router.get("/my-requests")
async def my_fee_requests(
    current_user: AppUser = Depends(get_current_user),
    service: FeeService = Depends(get_fee_service),
) -> dict:
    return await service.list_my_requests(current_user)


@compat_router.post("/requests/{request_id}/create-order")
async def create_fee_order(
    request_id: str,
    current_user: AppUser = Depends(get_current_user),
    service: FeeService = Depends(get_fee_service),
) -> dict:
    return await service.create_order(request_id, current_user)


@compat_router.post("/requests/{request_id}/verify")
async def verify_fee_order(
    request_id: str,
    body: RazorpayVerifyRequest,
    current_user: AppUser = Depends(get_current_user),
    service: FeeService = Depends(get_fee_service),
) -> dict:
    return await service.verify(
        request_id,
        current_user,
        razorpay_payment_id=body.razorpay_payment_id,
        razorpay_order_id=body.razorpay_order_id,
        razorpay_signature=body.razorpay_signature,
    )


@compat_router.post("/requests/{request_id}/cancel")
async def cancel_fee_order(
    request_id: str,
    current_user: AppUser = Depends(get_current_user),
    service: FeeService = Depends(get_fee_service),
) -> dict:
    return await service.cancel(request_id, current_user)
