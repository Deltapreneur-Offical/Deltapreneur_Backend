"""Venture deal escrow REST controller."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user, require_role
from app.entity.user.app_user import AppUser
from app.service.venture.venture_deal_service import VentureDealService

router = APIRouter(prefix="/api/v1/venture-deals", tags=["Venture Deals"])


class VerifyPaymentBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    razorpay_order_id: str = Field(..., alias="razorpayOrderId")
    razorpay_payment_id: str = Field(..., alias="razorpayPaymentId")
    razorpay_signature: str = Field(..., alias="razorpaySignature")


class RejectDealBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    reason: str = Field("", max_length=2000)


async def get_service(db: AsyncSession = Depends(get_async_db)) -> VentureDealService:
    return VentureDealService(db)


@router.post("/venture/{venture_id}/buy")
async def buy_full_acquisition(
    venture_id: uuid.UUID,
    service: VentureDealService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.buy_full_acquisition(venture_id, buyer=current_user)


@router.get("/my")
async def list_my_deals(
    service: VentureDealService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.list_my_deals(current_user)


@router.get("/admin/all")
async def admin_list_deals(
    service: VentureDealService = Depends(get_service),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await service.list_all_admin()


@router.get("/{deal_id}")
async def get_deal(
    deal_id: uuid.UUID,
    service: VentureDealService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.get_deal(deal_id, current_user)


@router.post("/{deal_id}/payment/create-order")
async def create_payment_order(
    deal_id: uuid.UUID,
    redeem_points: bool = False,
    service: VentureDealService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.create_payment_order(deal_id, buyer=current_user, redeem_points=redeem_points)


@router.post("/{deal_id}/payment/verify")
async def verify_payment(
    deal_id: uuid.UUID,
    payload: VerifyPaymentBody,
    service: VentureDealService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.verify_payment(
        deal_id,
        buyer=current_user,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_signature=payload.razorpay_signature,
    )


@router.post("/admin/{deal_id}/release-escrow")
async def admin_release_escrow(
    deal_id: uuid.UUID,
    service: VentureDealService = Depends(get_service),
    admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await service.admin_release_escrow(deal_id, admin=admin)


@router.post("/admin/{deal_id}/refund")
async def admin_refund_deal(
    deal_id: uuid.UUID,
    service: VentureDealService = Depends(get_service),
    admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await service.admin_refund(deal_id, admin=admin)


@router.post("/{deal_id}/admin/approve")
async def admin_approve_deal(
    deal_id: uuid.UUID,
    service: VentureDealService = Depends(get_service),
    admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await service.admin_approve_deal(deal_id, admin=admin)


@router.post("/{deal_id}/admin/reject")
async def admin_reject_deal(
    deal_id: uuid.UUID,
    payload: RejectDealBody,
    service: VentureDealService = Depends(get_service),
    admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await service.admin_reject_deal(deal_id, admin=admin, reason=payload.reason)
