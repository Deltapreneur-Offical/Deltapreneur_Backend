"""Software auction REST controller."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user, require_role
from app.entity.auction.auction_participation_entity import AuctionParticipationType
from app.entity.user.app_user import AppUser
from app.service.auction.auction_participation_service import AuctionParticipationService
from app.core.exceptions import AppException
from app.entity.auction.auction_fee_payment_entity import AuctionFeeAuctionType
from app.service.auction.auction_fee_service import AuctionFeeService
from app.service.cocreation.software_auction_service import SoftwareAuctionService
from app.service.platform.platform_settings_service import PlatformSettingsService
from app.utils.cocreation_enums import SoftwareAuctionDuration

router = APIRouter(
    prefix="/api/v1/software-auction",
    tags=["Software Auction"],
)


class CreateSoftwareAuctionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    min_bid_price: float = Field(..., gt=0, alias="minBidPrice")
    creation_fee_order_id: str = Field(..., alias="creationFeeOrderId")
    duration: SoftwareAuctionDuration
    auction_rationale: str = Field(..., min_length=1, alias="auctionRationale")
    source_code_included: bool = Field(default=False, alias="sourceCodeIncluded")
    support_included: bool = Field(default=False, alias="supportIncluded")
    support_days: int = Field(default=0, ge=0, alias="supportDays")
    transfer_details: Optional[str] = Field(default=None, alias="transferDetails")


class PlaceSoftwareBidRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    amount: float = Field(..., gt=0)
    razorpay_order_id: str = Field(..., alias="razorpayOrderId")
    razorpay_payment_id: str = Field(..., alias="razorpayPaymentId")
    razorpay_signature: str = Field(..., alias="razorpaySignature")


class ReSoftwareAuctionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    min_bid_price: float = Field(..., gt=0, alias="minBidPrice")
    duration: SoftwareAuctionDuration
    creation_fee_order_id: str = Field(..., min_length=1, alias="creationFeeOrderId")


class RejectSoftwareAuctionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(..., min_length=1)


class SoftwareAuctionSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    participation_fee_inr: float | None = Field(
        None,
        gt=0,
        le=100_000,
        validation_alias=AliasChoices("participationFeeInr", "participation_fee_inr"),
    )


class ParticipationVerifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    razorpay_payment_id: str = Field(
        ...,
        validation_alias=AliasChoices("razorpayPaymentId", "razorpay_payment_id"),
    )
    razorpay_order_id: str = Field(
        ...,
        validation_alias=AliasChoices("razorpayOrderId", "razorpay_order_id"),
    )
    razorpay_signature: str = Field(
        ...,
        validation_alias=AliasChoices("razorpaySignature", "razorpay_signature"),
    )


class WinnerPaymentVerifyBody(ParticipationVerifyBody):
    """Razorpay verify payload for software auction winner checkout."""


async def get_service(db: AsyncSession = Depends(get_async_db)) -> SoftwareAuctionService:
    return SoftwareAuctionService(db)


async def get_fee_service(db: AsyncSession = Depends(get_async_db)) -> AuctionFeeService:
    return AuctionFeeService(db)


async def get_participation_service(
    db: AsyncSession = Depends(get_async_db),
) -> AuctionParticipationService:
    return AuctionParticipationService(db)


@router.get("/active")
async def list_active(
    service: SoftwareAuctionService = Depends(get_service),
):
    """Public listing for Live Auctions page (approved + ACTIVE/EXTENDED only)."""
    return await service.list_active()


@router.get("/my")
async def list_my_software_auctions(
    service: SoftwareAuctionService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    """Technology auctions for listings owned by the current user."""
    items = await service.list_my_auctions(current_user)
    return {"success": True, "count": len(items), "data": items, "items": items}


@router.get("/my-bids")
async def list_my_software_bids(
    service: SoftwareAuctionService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    """Technology auctions the current user has bid on."""
    items = await service.list_my_bids(current_user)
    return {"success": True, "count": len(items), "data": items, "items": items}


@router.get("/admin/all")
async def admin_all(
    service: SoftwareAuctionService = Depends(get_service),
    _admin: AppUser = Depends(require_role(["SUPER_ADMIN", "AUCTION_MODERATOR", "ADMIN"])),
):
    data = await service.list_all_for_admin()
    return {"success": True, "count": len(data), "data": data}


@router.get("/admin/pending")
async def admin_pending(
    service: SoftwareAuctionService = Depends(get_service),
    _admin: AppUser = Depends(require_role(["SUPER_ADMIN", "AUCTION_MODERATOR", "ADMIN"])),
):
    data = await service.list_pending_for_admin()
    return {"success": True, "count": len(data), "data": data}


@router.post("/admin/{auction_id}/approve")
async def admin_approve(
    auction_id: uuid.UUID,
    service: SoftwareAuctionService = Depends(get_service),
    _admin: AppUser = Depends(require_role(["SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    auction = await service.approve_auction(auction_id)
    return {"id": str(auction.id), "status": auction.status.value}


@router.post("/admin/{auction_id}/reject")
async def admin_reject(
    auction_id: uuid.UUID,
    payload: RejectSoftwareAuctionRequest,
    service: SoftwareAuctionService = Depends(get_service),
    _admin: AppUser = Depends(require_role(["SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    auction = await service.reject_auction(auction_id, reason=payload.reason)
    return {"id": str(auction.id), "status": auction.status.value}


class TakeDownAuctionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(..., min_length=1)
    description: Optional[str] = None


@router.post("/admin/{auction_id}/take-down")
async def admin_take_down(
    auction_id: uuid.UUID,
    payload: TakeDownAuctionRequest,
    service: SoftwareAuctionService = Depends(get_service),
    admin: AppUser = Depends(require_role(["SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    # Pass IP optionally if needed, for now None
    await service.take_down_auction(
        auction_id, 
        admin=admin, 
        reason=payload.reason, 
        description=payload.description
    )
    return {"success": True, "message": "Auction taken down successfully."}


@router.get("/admin/taken-down")
async def admin_taken_down_list(
    service: SoftwareAuctionService = Depends(get_service),
    _admin: AppUser = Depends(require_role(["SUPER_ADMIN", "AUCTION_MODERATOR", "ADMIN"])),
):
    data = await service.get_taken_down_auctions()
    return {"success": True, "count": len(data), "data": data}


@router.post("/admin/{auction_id}/approve-again")
async def admin_approve_again(
    auction_id: uuid.UUID,
    service: SoftwareAuctionService = Depends(get_service),
    admin: AppUser = Depends(require_role(["SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    auction = await service.approve_again_auction(auction_id, admin=admin)
    return {"id": str(auction.id), "status": auction.status.value, "approvalStatus": auction.approval_status.value}



@router.post("/software/{software_id}")
async def create_auction(
    software_id: uuid.UUID,
    payload: CreateSoftwareAuctionRequest,
    service: SoftwareAuctionService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    auction = await service.create_auction(
        software_id,
        min_bid_price=payload.min_bid_price,
        duration=payload.duration,
        auction_rationale=payload.auction_rationale,
        source_code_included=payload.source_code_included,
        support_included=payload.support_included,
        support_days=payload.support_days,
        transfer_details=payload.transfer_details,
        lister=current_user,
        creation_fee_order_id=payload.creation_fee_order_id,
    )
    return {
        "id": str(auction.id),
        "status": auction.status.value,
        "approvalStatus": (
            auction.approval_status.value
            if hasattr(auction.approval_status, "value")
            else auction.approval_status
        ),
    }


@router.get("/software/{software_id}")
async def get_by_software(
    software_id: uuid.UUID,
    service: SoftwareAuctionService = Depends(get_service),
    _user: AppUser = Depends(get_current_user),
):
    return await service.get_by_software(software_id)


@router.get("/{auction_id}")
async def get_auction(
    auction_id: uuid.UUID,
    service: SoftwareAuctionService = Depends(get_service),
    _user: AppUser = Depends(get_current_user),
):
    return await service.get_auction_detail(auction_id)


@router.get("/{auction_id}/participation/status")
async def participation_status(
    auction_id: uuid.UUID,
    service: AuctionParticipationService = Depends(get_participation_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.get_status(AuctionParticipationType.SOFTWARE, auction_id, current_user)


@router.post("/{auction_id}/participation/create-order")
async def participation_create_order(
    auction_id: uuid.UUID,
    service: AuctionParticipationService = Depends(get_participation_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.create_order(AuctionParticipationType.SOFTWARE, auction_id, current_user)


@router.post("/{auction_id}/participation/verify")
async def participation_verify(
    auction_id: uuid.UUID,
    payload: ParticipationVerifyBody,
    service: AuctionParticipationService = Depends(get_participation_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.verify_payment(
        AuctionParticipationType.SOFTWARE,
        auction_id,
        current_user,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_signature=payload.razorpay_signature,
    )


@router.post("/{auction_id}/bid")
async def place_bid(
    auction_id: uuid.UUID,
    payload: PlaceSoftwareBidRequest,
    service: SoftwareAuctionService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.place_bid(
        auction_id,
        payload.amount,
        bidder=current_user,
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_signature=payload.razorpay_signature,
    )


@router.post("/{auction_id}/re-auction")
async def re_auction(
    auction_id: uuid.UUID,
    payload: ReSoftwareAuctionRequest,
    service: SoftwareAuctionService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    auction = await service.re_auction(
        auction_id,
        min_bid_price=payload.min_bid_price,
        duration=payload.duration,
        lister=current_user,
        creation_fee_order_id=payload.creation_fee_order_id,
    )
    return {"id": str(auction.id), "status": auction.status.value}


@router.post("/{auction_id}/close")
async def close_auction(
    auction_id: uuid.UUID,
    service: SoftwareAuctionService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.close_auction(auction_id, lister=current_user)


@router.post("/{auction_id}/winner-payment/create-order")
async def winner_payment_create_order(
    auction_id: uuid.UUID,
    redeem_points: bool = False,
    service: SoftwareAuctionService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    order = await service.create_winner_payment_order(
        auction_id,
        current_user,
        redeem_points=redeem_points,
    )
    return {"success": True, "message": "Winner payment order created", "data": order}


@router.post("/{auction_id}/winner-payment/verify")
async def winner_payment_verify(
    auction_id: uuid.UUID,
    payload: WinnerPaymentVerifyBody,
    service: SoftwareAuctionService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.verify_winner_payment(
        auction_id,
        current_user,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_signature=payload.razorpay_signature,
    )
