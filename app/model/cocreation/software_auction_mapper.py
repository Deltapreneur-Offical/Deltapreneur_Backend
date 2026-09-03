"""Map software auction ORM rows to camelCase API payloads."""

from __future__ import annotations

from typing import Any, Optional

from app.entity.cocreation.software_auction import SoftwareAuction
from app.entity.cocreation.software_auction_bid import SoftwareAuctionBid
from app.entity.cocreation.software_entity import Software
from app.model.cocreation.software_mapper import build_software_response


def _iso(dt) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


def auction_to_api(auction: SoftwareAuction) -> dict[str, Any]:
    return {
        "id": str(auction.id),
        "softwareId": str(auction.software_id),
        "status": auction.status.value if hasattr(auction.status, "value") else auction.status,
        "approvalStatus": (
            auction.approval_status.value
            if hasattr(auction.approval_status, "value")
            else auction.approval_status
        ),
        "duration": (
            auction.duration.value if hasattr(auction.duration, "value") else auction.duration
        ),
        "minBidPrice": auction.min_bid_price,
        "currentHighestBid": auction.current_highest_bid,
        "totalBids": auction.total_bids,
        "auctionRationale": auction.auction_rationale,
        "sourceCodeIncluded": auction.source_code_included,
        "supportIncluded": auction.support_included,
        "supportDays": auction.support_days,
        "transferDetails": auction.transfer_details,
        "rejectionReason": auction.rejection_reason,
        "currentWinnerId": (
            str(auction.current_winner_id) if auction.current_winner_id else None
        ),
        "winnerPaymentOrderId": auction.winner_payment_order_id,
        "winnerPaymentId": auction.winner_payment_id,
        "winnerPaymentPaid": bool(getattr(auction, "winner_payment_paid", False)),
        "startTime": _iso(auction.start_time),
        "endTime": _iso(auction.end_time),
        "originalEndTime": _iso(auction.original_end_time),
        "createdAt": _iso(auction.created_at),
        "updatedAt": _iso(auction.updated_at),
        "featured": bool(getattr(auction, "featured", False)),
        "takenDownAt": _iso(auction.taken_down_at),
        "takenDownById": str(auction.taken_down_by_id) if auction.taken_down_by_id else None,
        "takeDownReason": auction.take_down_reason,
        "takeDownDescription": auction.take_down_description,
        "takenDownBy": (
            {
                "id": str(auction.taken_down_by.id),
                "firstname": auction.taken_down_by.firstname,
                "lastname": auction.taken_down_by.lastname,
                "email": auction.taken_down_by.email,
            }
            if getattr(auction, "taken_down_by", None)
            else None
        ),
    }


def bid_to_api(bid: SoftwareAuctionBid) -> dict[str, Any]:
    return {
        "id": str(bid.id),
        "softwareAuctionId": str(bid.software_auction_id),
        "bidderId": str(bid.bidder_id),
        "amount": bid.amount,
        "bidderName": bid.bidder_name,
        "bidTime": _iso(bid.bid_time),
        "isWinningBid": bid.is_winning_bid,
        "createdAt": _iso(bid.created_at),
    }


def software_to_api(software: Software) -> dict[str, Any]:
    resp = build_software_response(software)
    data = resp.model_dump(mode="json", by_alias=True)
    listed_by = data.get("listedBy") or data.get("listed_by")
    return {
        "id": str(data["id"]),
        "name": data["name"],
        "description": data.get("description"),
        "whatItDoes": data.get("whatItDoes"),
        "imageUrl": data.get("imageUrl"),
        "price": data.get("price"),
        "category": data.get("category"),
        "purchaseType": data.get("purchaseType") or data.get("purchase_type"),
        "verified": bool(data.get("verified", False)),
        "listedBy": (
            {
                "id": str(listed_by["id"]),
                "firstname": listed_by.get("firstname"),
                "lastname": listed_by.get("lastname"),
                "username": listed_by.get("username"),
            }
            if listed_by
            else None
        ),
    }


from app.utils.auction_bid_limits import bid_limit_fields
from app.utils.auction_place_bid_common import bidder_display_name


def _winner_display_name(auction: SoftwareAuction, bids: list[SoftwareAuctionBid]) -> Optional[str]:
    if auction.current_winner is not None:
        return bidder_display_name(auction.current_winner) or None
    winning = next((b for b in bids if b.is_winning_bid), None)
    if winning and winning.bidder_name:
        return winning.bidder_name
    if bids:
        top = max(bids, key=lambda b: b.amount)
        return top.bidder_name or None
    return None


def min_next_bid(auction: SoftwareAuction) -> float:
    return bid_limit_fields(
        current_highest=auction.current_highest_bid,
        min_bid_price=auction.min_bid_price,
    )["minNextBid"]


def _bid_limits(auction: SoftwareAuction) -> dict[str, float]:
    return bid_limit_fields(
        current_highest=auction.current_highest_bid,
        min_bid_price=auction.min_bid_price,
    )


def build_detail_payload(
    auction: SoftwareAuction,
    bids: list[SoftwareAuctionBid],
) -> dict[str, Any]:
    payload = {
        "auction": auction_to_api(auction),
        "bids": [bid_to_api(b) for b in bids],
        "totalBids": auction.total_bids,
        "currentHighestBid": auction.current_highest_bid,
        **_bid_limits(auction),
    }
    if auction.software is not None:
        payload["auction"]["software"] = software_to_api(auction.software)
    winner_name = _winner_display_name(auction, bids)
    if winner_name:
        payload["auction"]["currentWinnerName"] = winner_name
    return payload


def build_by_software_payload(
    auction: Optional[SoftwareAuction],
    bids: list[SoftwareAuctionBid],
) -> dict[str, Any]:
    if auction is None:
        return {"auction": None, "bids": [], "minNextBid": None}
    out = {
        "auction": auction_to_api(auction),
        "bids": [bid_to_api(b) for b in bids],
        **_bid_limits(auction),
    }
    if auction.software is not None:
        out["software"] = software_to_api(auction.software)
        out["auction"]["software"] = out["software"]
    return out


def build_admin_item(auction: SoftwareAuction) -> dict[str, Any]:
    bids = list(auction.bids) if auction.bids else []
    item = build_detail_payload(auction, bids)
    if auction.software is not None:
        item["software"] = software_to_api(auction.software)
    return item
