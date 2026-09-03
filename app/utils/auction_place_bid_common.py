"""Shared bid placement rules for all auction types (domain, venture, software, community)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.entity.user.app_user import AppUser
from app.utils.auction_bid_limits import (
    bid_amount_in_range,
    format_bid_range_error,
)

ANTI_SNIPE_WINDOW = timedelta(minutes=5)
ANTI_SNIPE_EXTENSION = timedelta(minutes=5)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def bidder_display_name(user: AppUser) -> str:
    parts = [p for p in (user.firstname, user.lastname) if p]
    if parts:
        return " ".join(parts)
    return user.email or f"user#{user.id}"


def normalize_bid_amount(
    amount: float | Decimal | int | str,
    *,
    current_highest: float | Decimal | int | None,
    min_bid_price: float | Decimal | int | None,
) -> tuple[float, Decimal, Decimal]:
    """
    Validate bid against shared min/max rules.
    Returns (amount_as_float, min_required, max_allowed).
    Raises ValueError with a user-facing message when invalid.
    """
    _ok, min_required, max_allowed, normalized = bid_amount_in_range(
        amount,
        current_highest=current_highest or 0,
        min_bid_price=min_bid_price or 0,
    )
    range_error = format_bid_range_error(
        normalized=normalized,
        min_required=min_required,
        max_allowed=max_allowed,
    )
    if range_error:
        raise ValueError(range_error)
    return float(normalized), min_required, max_allowed


def apply_anti_snipe(
    end_time: datetime | None,
    now: datetime,
    *,
    status: Any,
    extended_status: Any,
) -> tuple[datetime | None, Any, bool]:
    """
    Extend end_time by ANTI_SNIPE_EXTENSION when inside the snipe window.
    Matches domain auction behavior (add extension to current end_time).
    """
    if end_time is None:
        return end_time, status, False
    if end_time <= now:
        return end_time, status, False
    remaining = end_time - now
    if remaining < ANTI_SNIPE_WINDOW:
        return end_time + ANTI_SNIPE_EXTENSION, extended_status, True
    return end_time, status, False


def build_bid_placed_ws_event(
    *,
    auction_id: Any,
    status: Any,
    current_highest_bid: float | Decimal | None,
    total_bids: int,
    end_time: datetime | None,
    bidder_name: str,
    amount: float | Decimal,
    bid_time: datetime | None = None,
    extended: bool = False,
    bid_id: Any | None = None,
    bidder_id: Any | None = None,
) -> dict[str, Any]:
    """CamelCase WebSocket payload used by all live auction rooms."""
    status_value = status.value if hasattr(status, "value") else status
    highest = float(current_highest_bid or 0)
    amount_f = float(amount)
    end_iso = end_time.isoformat() if end_time else None
    bid_time_iso = (bid_time or utc_now()).isoformat()
    latest = {
        "bidderName": bidder_name,
        "amount": amount_f,
        "bidTime": bid_time_iso,
        "isWinningBid": True,
    }
    if bid_id is not None:
        latest["id"] = str(bid_id)
    if bidder_id is not None:
        latest["bidder_id"] = str(bidder_id)
    return {
        "type": "BID_PLACED",
        "auctionId": str(auction_id),
        "auction_id": str(auction_id),
        "status": status_value,
        "currentHighestBid": highest,
        "current_highest_bid": str(highest) if highest else None,
        "totalBids": total_bids,
        "total_bids": total_bids,
        "endTime": end_iso,
        "end_time": end_iso,
        "extended": extended,
        "currentWinnerName": bidder_name,
        "latestBid": latest,
        "bid": latest,
    }
