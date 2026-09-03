"""
Bid REST controller — POST /api/v1/auction/{auction_id}/bid.

The actual bidding logic, locking, anti-snipe and websocket dispatch lives in
`app.service.auction.bid_service.BidService`. This controller is a thin HTTP
adapter.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.model.auction.auction_response import BidResponse
from app.model.auction.bid_request import PlaceBidRequest
from app.entity.auction.auction_fee_payment_entity import AuctionFeeAuctionType
from app.service.auction.auction_fee_service import AuctionFeeService
from app.service.auction.auction_participation_service import AuctionParticipationService
from app.service.auction.bid_service import BidService
from app.entity.auction.auction_participation_entity import AuctionParticipationType

router = APIRouter(prefix="/api/v1/auction", tags=["Bids"])


async def get_bid_service(
    db: AsyncSession = Depends(get_async_db),
) -> BidService:
    return BidService(db)


async def get_participation_service(
    db: AsyncSession = Depends(get_async_db),
) -> AuctionParticipationService:
    return AuctionParticipationService(db)


async def get_fee_service(
    db: AsyncSession = Depends(get_async_db),
) -> AuctionFeeService:
    return AuctionFeeService(db)


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


@router.get("/{auction_id}/participation/status")
async def participation_status(
    auction_id: uuid.UUID,
    service: AuctionParticipationService = Depends(get_participation_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.get_status(AuctionParticipationType.DOMAIN, auction_id, current_user)


@router.post("/{auction_id}/participation/create-order")
async def participation_create_order(
    auction_id: uuid.UUID,
    service: AuctionParticipationService = Depends(get_participation_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.create_order(AuctionParticipationType.DOMAIN, auction_id, current_user)


@router.post("/{auction_id}/participation/verify")
async def participation_verify(
    auction_id: uuid.UUID,
    payload: ParticipationVerifyBody,
    service: AuctionParticipationService = Depends(get_participation_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.verify_payment(
        AuctionParticipationType.DOMAIN,
        auction_id,
        current_user,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_signature=payload.razorpay_signature,
    )


@router.post(
    "/{auction_id}/bid",
    response_model=BidResponse,
    status_code=status.HTTP_201_CREATED,
)
async def place_bid(
    auction_id: uuid.UUID,
    payload: PlaceBidRequest,
    service: BidService = Depends(get_bid_service),
    current_user: AppUser = Depends(get_current_user),
) -> BidResponse:
    """
    Place a bid on an auction.

    All concurrency safety (SELECT FOR UPDATE on the auction row, atomic
    transaction, anti-snipe extension, websocket broadcast) is enforced
    inside `BidService.place_bid`.
    """
    # Path parameter is authoritative — overwrite any body-supplied auction_id.
    payload = payload.model_copy(update={"auction_id": auction_id})
    bid, _event = await service.place_bid(payload, bidder=current_user)
    return BidResponse.model_validate(bid)


__all__ = ["router"]
