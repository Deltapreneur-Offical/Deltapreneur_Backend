"""
Domain auction winner payment routes (Razorpay TEST/LIVE).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.model.common.payment_request import RazorpayVerifyRequest
from app.model.payment.payment_response import (
    CreatePaymentOrderResponse,
    VerifyPaymentResponse,
)
from app.service.auction.auction_payment_service import AuctionPaymentService

router = APIRouter(prefix="/api/v1/payment", tags=["Payments"])


async def get_payment_service(
    db: AsyncSession = Depends(get_async_db),
) -> AuctionPaymentService:
    return AuctionPaymentService(db)


@router.post(
    "/create-order/{auction_id}",
    response_model=CreatePaymentOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Razorpay order for auction winner payment",
)
async def create_payment_order(
    auction_id: uuid.UUID,
    redeem_points: bool = False,
    current_user: AppUser = Depends(get_current_user),
    service: AuctionPaymentService = Depends(get_payment_service),
) -> CreatePaymentOrderResponse:
    return await service.create_winner_order(auction_id, current_user, redeem_points=redeem_points)


@router.post(
    "/verify",
    response_model=VerifyPaymentResponse,
    summary="Verify Razorpay payment signature and complete auction",
)
async def verify_payment(
    body: RazorpayVerifyRequest,
    current_user: AppUser = Depends(get_current_user),
    service: AuctionPaymentService = Depends(get_payment_service),
) -> VerifyPaymentResponse:
    return await service.verify_winner_payment(
        user=current_user,
        razorpay_order_id=body.razorpay_order_id,
        razorpay_payment_id=body.razorpay_payment_id,
        razorpay_signature=body.razorpay_signature,
    )
