import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db, get_async_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_current_user, require_role
from app.entity.auction.auction_participation_entity import (
    AuctionParticipation,
    AuctionParticipationStatus,
    AuctionParticipationType,
)
from app.entity.user.app_user import AppUser
from app.service.auction.auction_fee_sync import (
    community_participation_fee_inr,
    has_community_participation_paid,
)
from app.integrations.razorpay import client as rzp
from app.model.common.api_response import ApiResponse
from app.model.common.payment_request import RazorpayVerifyRequest
from app.model.community.community_auction_create_request import (
    CommunityAuctionCreateRequest,
)
from app.model.community.community_auction_bid_request import (
    CommunityAuctionBidRequest,
)
from app.model.community.community_auction_reauction_request import (
    CommunityAuctionReauctionRequest,
)
from app.repository.community_auction_repository import CommunityAuctionRepository
from app.service.community.community_auction_service import (
    CommunityAuctionService,
)
from app.service.auction.auction_owner import (
    is_community_auction_owner_sync,
    owner_participation_status,
)


router = APIRouter(tags=["Creator Auctions"])


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


@router.get("/test", response_model=ApiResponse)
def test_community_auction():
    return ApiResponse(
        success=True,
        message="Creator auction module is connected successfully",
        data={
            "module": "community-auction",
            "status": "ready",
        },
    )


@router.post("", response_model=ApiResponse)
def create_community_auction(
    request: CommunityAuctionCreateRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    auction = CommunityAuctionService.create_auction(
        db=db,
        request=request,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Creator auction created successfully",
        data=auction,
    )


@router.get("/all", response_model=ApiResponse)
def get_all_community_auctions(
    db: Session = Depends(get_db),
):
    auctions = CommunityAuctionService.get_all_auctions(db)

    return ApiResponse(
        success=True,
        message="Creator auctions fetched successfully",
        data=auctions,
    )


@router.get("/my", response_model=ApiResponse)
def get_my_community_auctions(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    auctions = CommunityAuctionService.get_my_auctions(
        db=db,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="My community auctions fetched successfully",
        data=auctions,
    )


@router.get("/my-bids", response_model=ApiResponse)
def get_my_community_auction_bids(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    auctions = CommunityAuctionService.get_my_bids(
        db=db,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="My community auction bids fetched successfully",
        data=auctions,
    )


@router.get("/active", response_model=ApiResponse)
def get_active_community_auctions(
    db: Session = Depends(get_db),
):
    auctions = CommunityAuctionService.get_active_auctions(db)
    return ApiResponse(
        success=True,
        message="Active community auctions fetched successfully",
        data=auctions,
    )


@router.get("/admin/all", response_model=ApiResponse)
def admin_all_community_auctions(
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    auctions = CommunityAuctionService.get_all_auctions_for_admin(db)
    return ApiResponse(
        success=True,
        message="Creator auctions (admin) fetched successfully",
        data=auctions,
    )


@router.get("/community/{community_id}", response_model=ApiResponse)
def get_community_auction_by_community(
    community_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    auction = CommunityAuctionService.get_auction_by_community_id(
        db=db,
        community_id=community_id,
    )
    if not auction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator auction not found for this profile",
        )
    return ApiResponse(
        success=True,
        message="Creator auction fetched successfully",
        data=auction,
    )


@router.get("/{auction_id}", response_model=ApiResponse)
def get_community_auction_by_id(
    auction_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    auction = CommunityAuctionService.get_auction_by_id(
        db=db,
        auction_id=auction_id,
    )

    return ApiResponse(
        success=True,
        message="Creator auction fetched successfully",
        data=auction,
    )
@router.put("/{auction_id}/activate", response_model=ApiResponse)
def activate_community_auction(
    auction_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    auction = CommunityAuctionService.activate_auction_after_payment(
        db=db,
        auction_id=auction_id,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Creator auction activated successfully",
        data=auction,
    )


@router.post("/{auction_id}/bid", response_model=ApiResponse)
def place_community_auction_bid_singular(
    auction_id: uuid.UUID,
    request: CommunityAuctionBidRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    bid = CommunityAuctionService.place_bid(
        db=db,
        auction_id=auction_id,
        request=request,
        current_user=current_user,
    )
    return ApiResponse(
        success=True,
        message="Creator auction bid placed successfully",
        data=bid,
    )


@router.post("/{auction_id}/bids", response_model=ApiResponse)
def place_community_auction_bid(
    auction_id: uuid.UUID,
    request: CommunityAuctionBidRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    bid = CommunityAuctionService.place_bid(
        db=db,
        auction_id=auction_id,
        request=request,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Creator auction bid placed successfully",
        data=bid,
    )


@router.get("/{auction_id}/participation/status", response_model=ApiResponse)
def community_participation_status(
    auction_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    auction = CommunityAuctionRepository.find_by_id(db=db, auction_id=auction_id)
    if auction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator auction not found",
        )
    if is_community_auction_owner_sync(db, auction_id, current_user.id):
        return ApiResponse(
            success=True,
            message="Participation status fetched",
            data=owner_participation_status(),
        )
    fee = community_participation_fee_inr(db)
    paid = has_community_participation_paid(db, auction_id, current_user.id)
    return ApiResponse(
        success=True,
        message="Participation status fetched",
        data={"paid": paid, "participationFeeInr": fee, "canBid": paid, "isOwner": False},
    )


@router.post("/{auction_id}/participation/create-order", response_model=ApiResponse)
async def community_participation_create_order(
    auction_id: uuid.UUID,
    redeem_points: bool = False,
    db: Session = Depends(get_db),
    async_db: AsyncSession = Depends(get_async_db),
    current_user: AppUser = Depends(get_current_user),
):
    if is_community_auction_owner_sync(db, auction_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot participate in your own auction",
        )
    fee = community_participation_fee_inr(db)
    existing = db.query(AuctionParticipation).filter(
        AuctionParticipation.auction_type == AuctionParticipationType.COMMUNITY,
        AuctionParticipation.auction_id == auction_id,
        AuctionParticipation.user_id == current_user.id,
    ).first()
    if existing and existing.status == AuctionParticipationStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Participation fee already paid")

    amount_to_charge = fee
    points_redeemed = 0
    if redeem_points and amount_to_charge > 0:
        from app.service.user.edge_points_service import EdgePointsService
        amount_to_charge, points_redeemed = await EdgePointsService.calculate_redemption(
            async_db, current_user, amount_to_charge, redeem_points
        )

    order = rzp.create_order(
        amount_inr=amount_to_charge,
        receipt=f"cap_{auction_id}_{current_user.id}"[:40],
        notes={"auctionId": str(auction_id), "userId": str(current_user.id), "type": "community_auction_participation"},
    )
    if points_redeemed > 0:
        from app.service.user.edge_points_service import EdgePointsService
        await EdgePointsService.create_pending_redemption(
            async_db, current_user.id, order["id"], points_redeemed
        )

    if existing:
        existing.razorpay_order_id = order["id"]
        existing.fee_amount_inr = amount_to_charge
        existing.status = AuctionParticipationStatus.CREATED
    else:
        db.add(
            AuctionParticipation(
                auction_type=AuctionParticipationType.COMMUNITY,
                auction_id=auction_id,
                user_id=current_user.id,
                fee_amount_inr=amount_to_charge,
                razorpay_order_id=order["id"],
                status=AuctionParticipationStatus.CREATED,
            )
        )
    db.commit()
    return ApiResponse(
        success=True,
        message="Participation order created",
        data={"orderId": order["id"], "amount": amount_to_charge, "currency": "INR", "keyId": rzp.get_key_id(), "auctionId": str(auction_id)},
    )


@router.post("/{auction_id}/participation/verify", response_model=ApiResponse)
async def community_participation_verify(
    auction_id: uuid.UUID,
    payload: ParticipationVerifyBody,
    db: Session = Depends(get_db),
    async_db: AsyncSession = Depends(get_async_db),
    current_user: AppUser = Depends(get_current_user),
):
    if is_community_auction_owner_sync(db, auction_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot participate in your own auction",
        )
    if not rzp.verify_payment_signature(
        payload.razorpay_order_id, payload.razorpay_payment_id, payload.razorpay_signature
    ):
        from app.service.user.edge_points_service import EdgePointsService
        await EdgePointsService.cancel_redemption(async_db, payload.razorpay_order_id)
        raise HTTPException(status_code=400, detail="Invalid payment signature")
    row = db.query(AuctionParticipation).filter(
        AuctionParticipation.auction_type == AuctionParticipationType.COMMUNITY,
        AuctionParticipation.auction_id == auction_id,
        AuctionParticipation.user_id == current_user.id,
        AuctionParticipation.razorpay_order_id == payload.razorpay_order_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Participation record not found")
    row.status = AuctionParticipationStatus.COMPLETED
    row.razorpay_payment_id = payload.razorpay_payment_id
    db.commit()
    from app.service.user.edge_points_service import EdgePointsService
    await EdgePointsService.confirm_redemption(async_db, payload.razorpay_order_id)
    return ApiResponse(
        success=True,
        message="Participation fee verified",
        data={"paid": True, "message": "Participation fee confirmed. You can now place bids."},
    )


@router.post("/{auction_id}/re-auction", response_model=ApiResponse)
def re_auction_community_auction(
    auction_id: uuid.UUID,
    body: CommunityAuctionReauctionRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    auction = CommunityAuctionService.re_auction(
        db=db,
        auction_id=auction_id,
        min_bid_price=body.min_bid_price,
        duration=body.duration,
        current_user=current_user,
        creation_fee_order_id=body.creation_fee_order_id,
    )
    return ApiResponse(
        success=True,
        message="Creator auction re-opened",
        data=auction,
    )


@router.post("/{auction_id}/close", response_model=ApiResponse)
def close_community_auction(
    auction_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    data = CommunityAuctionService.close_auction(
        db=db,
        auction_id=auction_id,
        current_user=current_user,
    )
    return ApiResponse(
        success=True,
        message="Auction closed",
        data=data,
    )


@router.get("/{auction_id}/bids", response_model=ApiResponse)
def get_community_auction_bids(
    auction_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    bids = CommunityAuctionService.get_auction_bids(
        db=db,
        auction_id=auction_id,
    )

    return ApiResponse(
        success=True,
        message="Creator auction bids fetched successfully",
        data=bids,
    )
