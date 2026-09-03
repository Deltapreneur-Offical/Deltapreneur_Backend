"""Auction creation fee and bid fee endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user, require_role
from app.core.exceptions import AppException
from app.entity.auction.auction_fee_payment_entity import AuctionFeeAuctionType
from app.entity.user.app_user import AppUser
from app.service.auction.auction_fee_service import AuctionFeeService
from app.service.platform.platform_settings_service import PlatformSettingsService

router = APIRouter(prefix="/api/v1/auction-fees", tags=["Auction Fees"])


class FeeVerifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    auction_type: str = Field(..., alias="auctionType")
    razorpay_payment_id: str = Field(
        ..., validation_alias=AliasChoices("razorpayPaymentId", "razorpay_payment_id")
    )
    razorpay_order_id: str = Field(
        ..., validation_alias=AliasChoices("razorpayOrderId", "razorpay_order_id")
    )
    razorpay_signature: str = Field(
        ..., validation_alias=AliasChoices("razorpaySignature", "razorpay_signature")
    )


class CreationOrderBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    auction_type: str = Field(..., alias="auctionType")
    reference_id: uuid.UUID | None = Field(None, alias="referenceId")


class BidOrderBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    auction_type: str = Field(..., alias="auctionType")
    bid_amount: float = Field(..., gt=0, alias="bidAmount")


class ListingFeesUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    listing_commission_percent: float | None = Field(
        None, ge=0, le=100, alias="listingCommissionPercent"
    )
    venture_acquisition_commission_percent: float | None = Field(
        None, ge=0, le=100, alias="ventureAcquisitionCommissionPercent"
    )
    auction_creation_fee_inr: float | None = Field(
        None, gt=0, le=100_000, alias="auctionCreationFeeInr"
    )
    auction_bid_fee_inr: float | None = Field(
        None, gt=0, le=100_000, alias="auctionBidFeeInr"
    )
    domain_participation_fee_inr: float | None = Field(
        None, gt=0, le=100_000, alias="domainParticipationFeeInr"
    )
    software_participation_fee_inr: float | None = Field(
        None, gt=0, le=100_000, alias="softwareParticipationFeeInr"
    )
    community_participation_fee_inr: float | None = Field(
        None, gt=0, le=100_000, alias="communityParticipationFeeInr"
    )
    software_onetime_commission_percent: float | None = Field(
        None, ge=0, le=100, alias="softwareOnetimeCommissionPercent"
    )
    hardware_onetime_commission_percent: float | None = Field(
        None, ge=0, le=100, alias="hardwareOnetimeCommissionPercent"
    )
    hardware_subscription_commission_percent: float | None = Field(
        None, ge=0, le=100, alias="hardwareSubscriptionCommissionPercent"
    )


def _parse_auction_type(raw: str) -> AuctionFeeAuctionType:
    try:
        return AuctionFeeAuctionType(raw.upper())
    except ValueError as exc:
        raise AppException("Invalid auction type.", status_code=400) from exc


async def get_fee_service(db: AsyncSession = Depends(get_async_db)) -> AuctionFeeService:
    return AuctionFeeService(db)


async def get_settings_service(
    db: AsyncSession = Depends(get_async_db),
) -> PlatformSettingsService:
    return PlatformSettingsService(db)


@router.get("/listing-fees-and-charges")
async def get_listing_fees_and_charges(
    service: PlatformSettingsService = Depends(get_settings_service),
):
    return await service.get_listing_fees_and_charges()


@router.put("/admin/listing-fees-and-charges")
async def update_listing_fees_and_charges(
    payload: ListingFeesUpdateBody,
    service: PlatformSettingsService = Depends(get_settings_service),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    try:
        return await service.update_listing_fees_and_charges(
            listing_commission_percent=payload.listing_commission_percent,
            venture_acquisition_commission_percent=(
                payload.venture_acquisition_commission_percent
            ),
            auction_creation_fee_inr=payload.auction_creation_fee_inr,
            auction_bid_fee_inr=payload.auction_bid_fee_inr,
            domain_participation_fee_inr=payload.domain_participation_fee_inr,
            software_participation_fee_inr=payload.software_participation_fee_inr,
            community_participation_fee_inr=payload.community_participation_fee_inr,
            software_onetime_commission_percent=payload.software_onetime_commission_percent,
            hardware_onetime_commission_percent=payload.hardware_onetime_commission_percent,
            hardware_subscription_commission_percent=(
                payload.hardware_subscription_commission_percent
            ),
        )
    except ValueError as exc:
        raise AppException(str(exc), status_code=400) from exc


@router.post("/creation/create-order")
async def creation_fee_create_order(
    payload: CreationOrderBody,
    redeem_points: bool = False,
    service: AuctionFeeService = Depends(get_fee_service),
    current_user: AppUser = Depends(get_current_user),
):
    auction_type = _parse_auction_type(payload.auction_type)
    return await service.create_creation_fee_order(
        auction_type=auction_type,
        user=current_user,
        reference_id=payload.reference_id,
        redeem_points=redeem_points,
    )


@router.post("/creation/verify")
async def creation_fee_verify(
    payload: FeeVerifyBody,
    service: AuctionFeeService = Depends(get_fee_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.verify_creation_fee_payment(
        user=current_user,
        auction_type=_parse_auction_type(payload.auction_type),
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_signature=payload.razorpay_signature,
    )


@router.post("/{auction_id}/bid/create-order")
async def bid_fee_create_order(
    auction_id: uuid.UUID,
    payload: BidOrderBody,
    redeem_points: bool = False,
    service: AuctionFeeService = Depends(get_fee_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.create_bid_fee_order(
        auction_type=_parse_auction_type(payload.auction_type),
        auction_id=auction_id,
        bid_amount=payload.bid_amount,
        user=current_user,
        redeem_points=redeem_points,
    )
