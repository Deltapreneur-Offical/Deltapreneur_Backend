"""Map domain auction ORM rows to camelCase admin/detail payloads."""

from __future__ import annotations

from typing import Any, Optional

from app.entity.auction.auction_entity import Auction
from app.entity.auction.bid_entity import Bid
from app.entity.auction.domain_entity import Domain
from app.entity.user.app_user import AppUser
from app.integrations.s3.supabase_storage import resolve_media_url


def _iso(dt) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


def _split_domain_name(full: str) -> tuple[str, str]:
    name = (full or "").strip()
    if not name:
        return "", ""
    if "." not in name:
        return name, ""
    dot = name.rfind(".")
    return name[:dot], name[dot:]


def _listing_full_domain(listing: Any) -> str:
    name = (getattr(listing, "domain_name", None) or "").strip()
    ext = (getattr(listing, "domain_extension", None) or "").strip()
    if not name:
        return ext
    if not ext:
        return name
    if name.lower().endswith(ext.lower()) or name.lower().endswith(
        ext.lstrip(".").lower()
    ):
        return name
    return f"{name}{ext if ext.startswith('.') else f'.{ext}'}"


def user_brief(user: AppUser | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": str(user.id),
        "firstname": user.firstname,
        "lastname": user.lastname,
        "email": user.email,
        "phoneNumber": user.phone_number,
    }


def _pricing_demand_value(listing: Any) -> str | None:
    pricing_demand = getattr(listing, "pricing_demand", None)
    if pricing_demand is None:
        return None
    if hasattr(pricing_demand, "value"):
        return str(pricing_demand.value)
    return str(pricing_demand)


def domain_summary_from_listing(listing: Any) -> dict[str, Any]:
    full = _listing_full_domain(listing)
    logo_raw = getattr(listing, "logo", None)
    return {
        "id": str(listing.id),
        "fullDomain": full,
        "domainName": listing.domain_name,
        "domainExtension": listing.domain_extension or "",
        "pricingDemand": _pricing_demand_value(listing),
        "logo": resolve_media_url(logo_raw) if logo_raw else None,
        "verified": bool(getattr(listing, "verified", False)),
        "listedBy": user_brief(getattr(listing, "listed_by", None)),
    }


def domain_summary_for_auction(domain: Domain | None) -> dict[str, Any] | None:
    if domain is None:
        return None
    full = (domain.domain_name or "").strip()
    domain_name, domain_extension = _split_domain_name(full)
    return {
        "id": str(domain.id),
        "fullDomain": full,
        "domainName": domain_name or full,
        "domainExtension": domain_extension,
        "description": domain.description,
        "verified": domain.is_verified,
        "listedBy": user_brief(domain.owner),
    }


def auction_to_api(auction: Auction) -> dict[str, Any]:
    status = (
        auction.status.value
        if hasattr(auction.status, "value")
        else auction.status
    )
    duration = (
        auction.duration.value
        if hasattr(auction.duration, "value")
        else auction.duration
    )
    highest = auction.current_highest_bid or 0
    return {
        "id": str(auction.id),
        "domainId": str(auction.domain_id),
        "status": status,
        "duration": duration,
        "minBidPrice": float(auction.min_bid_price),
        "currentHighestBid": float(highest),
        "totalBids": auction.total_bids,
        "currentWinnerId": (
            str(auction.current_winner_id) if auction.current_winner_id else None
        ),
        "startTime": _iso(auction.start_time),
        "endTime": _iso(auction.end_time),
        "originalEndTime": _iso(auction.original_end_time),
        "createdAt": _iso(auction.created_at),
        "updatedAt": _iso(auction.updated_at),
        "featured": bool(getattr(auction, "featured", False)),
    }


def bid_to_api(bid: Bid) -> dict[str, Any]:
    return {
        "id": str(bid.id),
        "auctionId": str(bid.auction_id),
        "bidderId": str(bid.bidder_id),
        "amount": float(bid.amount),
        "bidderName": bid.bidder_name,
        "bidTime": _iso(bid.created_at),
        "isWinningBid": bid.is_winning_bid,
        "createdAt": _iso(bid.created_at),
    }


def build_public_auction_item(
    auction: Auction,
    *,
    listing: Any | None = None,
) -> dict[str, Any]:
    """Active auction card / list item with nested domain (camelCase)."""
    item = auction_to_api(auction)
    if listing is not None:
        domain_payload = domain_summary_from_listing(listing)
        registry_domain = getattr(auction, "domain", None)
        registry_description = getattr(registry_domain, "description", None)
        if registry_description:
            domain_payload["description"] = registry_description
    else:
        domain_payload = domain_summary_for_auction(auction.domain)
    if domain_payload:
        item["domain"] = domain_payload
        display = domain_payload.get("fullDomain") or (
            f"{domain_payload.get('domainName', '')}"
            f"{domain_payload.get('domainExtension', '')}"
        ).strip()
        if display:
            item["domainDisplayName"] = display
    return item


def _winner_display_name(auction: Auction, bids: list[Bid]) -> str | None:
    winner = getattr(auction, "current_winner", None)
    if winner is not None:
        parts = [p for p in (winner.firstname, winner.lastname) if p]
        if parts:
            return " ".join(parts)
        if winner.email:
            return winner.email
    for bid in bids:
        if bid.is_winning_bid and bid.bidder_name:
            return bid.bidder_name
    if bids:
        return bids[0].bidder_name
    return None


def build_public_auction_detail(
    auction: Auction,
    *,
    listing: Any | None = None,
    winner_payment_paid: bool = False,
    transfer_transaction_id: str | None = None,
) -> dict[str, Any]:
    """Single auction page: auction + bids + min next bid + domain."""
    bids = sorted(
        list(auction.bids or []),
        key=lambda b: b.created_at,
        reverse=True,
    )
    item = build_public_auction_item(auction, listing=listing)
    highest = float(auction.current_highest_bid or 0)
    min_bid = float(auction.min_bid_price)
    min_next = highest * 1.05 if highest > 0 else min_bid
    winner_name = _winner_display_name(auction, bids)
    if winner_name:
        item["currentWinnerName"] = winner_name
    item["winnerPaymentPaid"] = bool(winner_payment_paid)
    if transfer_transaction_id:
        item["transferTransactionId"] = transfer_transaction_id
    return {
        "auction": item,
        "bids": [bid_to_api(b) for b in bids],
        "minNextBid": min_next,
        "domain": item.get("domain"),
    }


def build_admin_auction_item(
    auction: Auction,
    *,
    listing: Any | None = None,
) -> dict[str, Any]:
    bids = sorted(
        list(auction.bids or []),
        key=lambda b: b.created_at,
        reverse=True,
    )
    payload: dict[str, Any] = {
        "auction": auction_to_api(auction),
        "bids": [bid_to_api(b) for b in bids],
        "totalBids": auction.total_bids,
        "currentHighestBid": float(auction.current_highest_bid or 0),
    }
    if listing is not None:
        domain_payload = domain_summary_from_listing(listing)
    else:
        domain_payload = domain_summary_for_auction(auction.domain)
    if domain_payload:
        payload["domain"] = domain_payload
        payload["auction"]["domain"] = domain_payload
        display = domain_payload.get("fullDomain") or (
            f"{domain_payload.get('domainName', '')}"
            f"{domain_payload.get('domainExtension', '')}"
        ).strip()
        if display:
            payload["auction"]["domainDisplayName"] = display
    winner = auction.current_winner
    if winner:
        winner_brief = user_brief(winner)
        payload["auction"]["currentWinner"] = winner_brief
    elif bids:
        top = bids[0]
        payload["auction"]["currentWinnerName"] = top.bidder_name
    return payload
