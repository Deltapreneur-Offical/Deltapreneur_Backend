"""Singular /api/v1/community-auction/* routes (aliases for frontend; keep plural router)."""

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.entity.user.app_user import AppUser
from app.model.common.api_response import ApiResponse
from app.model.common.payment_request import RazorpayVerifyRequest
from app.model.community.community_auction_bid_request import CommunityAuctionBidRequest
from app.model.community.community_auction_create_request import CommunityAuctionCreateRequest
from app.model.community.community_auction_reauction_request import CommunityAuctionReauctionRequest
from app.repository.community_repository import CommunityRepository
from app.service.community.community_service import CommunityService
from app.service.community.community_auction_service import CommunityAuctionService
from app.utils.auction_bid_limits import bid_limit_fields

router = APIRouter(tags=["Creator Auctions"])


def _bundle_auction_payload(db: Session, auction: dict) -> dict:
    auction_id = auction.get("id")
    bids = []
    if auction_id:
        try:
            bids = CommunityAuctionService.get_auction_bids(
                db=db, auction_id=uuid.UUID(str(auction_id)),
            )
        except Exception:
            bids = []
    current_highest = float(auction.get("currentHighestBid") or auction.get("current_highest_bid") or 0)
    min_bid = float(auction.get("minBidPrice") or auction.get("min_bid_price") or 0)
    limits = bid_limit_fields(current_highest=current_highest, min_bid_price=min_bid)

    community_id = auction.get("communityId") or auction.get("community_id")
    if community_id:
        community = CommunityRepository.find_by_id(
            db=db, community_id=uuid.UUID(str(community_id)),
        )
        if community is not None:
            auction["community"] = CommunityService._to_response(community)

    return {
        "auction": auction,
        "bids": bids,
        "totalBids": auction.get("totalBids") or auction.get("total_bids") or len(bids),
        "currentHighestBid": current_highest,
        **limits,
    }


@router.post("")
def create_auction_singular(
    community_id: uuid.UUID = Query(..., alias="communityId"),
    request: CommunityAuctionCreateRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    """Frontend posts with query communityId + JSON body (same fields as plural create)."""
    payload = request.model_dump()
    payload["community_id"] = str(community_id)
    req = CommunityAuctionCreateRequest.model_validate(payload)
    auction = CommunityAuctionService.create_auction(
        db=db,
        request=req,
        current_user=current_user,
    )
    # Frontend expects `{ auction: {...} }` and reads `auction.id` for step-2 payment.
    return {
        "success": True,
        "message": "Creator auction created successfully",
        "auction": auction,
    }


@router.get("/{auction_id:uuid}")
def get_auction_singular(auction_id: uuid.UUID, db: Session = Depends(get_db)):
    auction = CommunityAuctionService.get_auction_by_id(db=db, auction_id=auction_id)
    return {
        "success": True,
        "message": "Creator auction fetched successfully",
        **_bundle_auction_payload(db, auction),
    }


@router.get("/community/{community_id}")
def get_by_community_singular(community_id: uuid.UUID, db: Session = Depends(get_db)):
    auction = CommunityAuctionService.get_auction_by_community_id(db=db, community_id=community_id)
    if not auction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator auction not found for this profile",
        )
    # Frontend currently cannot resume payment from the "pending" badge state.
    # Return 404 for PAYMENT_PENDING so UI shows "Put Profile to Auction" again.
    # The create endpoint is idempotent and will return this same pending auction,
    # allowing the modal to jump back to payment step.
    if str(auction.get("status", "")).upper() == "PAYMENT_PENDING":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator auction not found for this profile",
        )
    return {
        "success": True,
        "message": "Creator auction fetched successfully",
        **_bundle_auction_payload(db, auction),
    }


@router.get("/active")
def active_singular(db: Session = Depends(get_db)):
    auctions = CommunityAuctionService.get_active_auctions(db)
    # Frontend AuctionsPage expects a raw array (`Array.isArray(data)`).
    # Also enrich each row with community details used by CreatorAuctionCard.
    enriched: list[dict] = []
    for auction in auctions:
        item = dict(auction)
        community_id = item.get("communityId") or item.get("community_id")
        if community_id:
            try:
                community = CommunityRepository.find_by_id(
                    db=db, community_id=uuid.UUID(str(community_id)),
                )
                if community is not None:
                    item["community"] = CommunityService._to_response(community)
            except Exception:
                pass
        enriched.append(item)
    enriched.sort(key=lambda a: a.get("endTime") or a.get("end_time") or "")
    return enriched


@router.get("/my", response_model=ApiResponse)
def my_singular(db: Session = Depends(get_db), current_user: AppUser = Depends(get_current_user)):
    auctions = CommunityAuctionService.get_my_auctions(db=db, current_user=current_user)
    return ApiResponse(
        success=True,
        message="My community auctions fetched successfully",
        data=auctions,
    )


@router.get("/my-bids", response_model=ApiResponse)
def my_bids_singular(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    auctions = CommunityAuctionService.get_my_bids(db=db, current_user=current_user)
    return ApiResponse(
        success=True,
        message="My community auction bids fetched successfully",
        data=auctions,
    )


@router.post("/{auction_id}/bid", response_model=ApiResponse)
def bid_singular(
    auction_id: uuid.UUID,
    request: CommunityAuctionBidRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    bid = CommunityAuctionService.place_bid(
        db=db, auction_id=auction_id, request=request, current_user=current_user,
    )
    return ApiResponse(success=True, message="Creator auction bid placed successfully", data=bid)


@router.post("/{auction_id}/re-auction", response_model=ApiResponse)
def re_auction_singular(
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
    return ApiResponse(success=True, message="Creator auction re-opened", data=auction)


@router.post("/{auction_id}/close", response_model=ApiResponse)
def close_singular(
    auction_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    data = CommunityAuctionService.close_auction(
        db=db, auction_id=auction_id, current_user=current_user,
    )
    return ApiResponse(success=True, message="Auction closed", data=data)


@router.post("/{auction_id}/winner-payment/create-order")
def winner_payment_create_order(
    auction_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    order = CommunityAuctionService.create_winner_payment_order(
        db=db, auction_id=auction_id, current_user=current_user,
    )
    return {"success": True, "message": "Winner payment order created", **order}


@router.post("/{auction_id}/winner-payment/verify")
def winner_payment_verify(
    auction_id: uuid.UUID,
    body: RazorpayVerifyRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    return CommunityAuctionService.verify_winner_payment(
        db=db,
        auction_id=auction_id,
        razorpay_payment_id=body.razorpay_payment_id,
        razorpay_order_id=body.razorpay_order_id,
        razorpay_signature=body.razorpay_signature,
        current_user=current_user,
    )


@router.get("/admin/all", response_model=ApiResponse)
def admin_all_singular(
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    auctions = CommunityAuctionService.get_all_auctions_for_admin(db)
    return ApiResponse(
        success=True,
        message="Creator auctions (admin) fetched successfully",
        data=auctions,
    )
