"""Helpers for Your Auctions / Your Bids tracking payloads (read-only)."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from app.utils.enums import AuctionStatus

_LIVE = {AuctionStatus.ACTIVE, AuctionStatus.EXTENDED}
_PENDING_WINNER = {
    AuctionStatus.ENDED,
    AuctionStatus.PAYMENT_PENDING,
}


def bidder_tracking_fields(
    *,
    user_id: uuid.UUID,
    user_highest_bid: float,
    current_highest_bid: float,
    current_winner_id: Optional[uuid.UUID],
    status: AuctionStatus | str,
) -> dict[str, Any]:
    """Common bidder summary fields for my-bids cards."""
    status_val = status.value if hasattr(status, "value") else str(status)
    try:
        status_enum = status if isinstance(status, AuctionStatus) else AuctionStatus(status_val)
    except ValueError:
        status_enum = None

    is_winner = current_winner_id is not None and current_winner_id == user_id
    is_live = status_enum in _LIVE if status_enum is not None else status_val in {
        "ACTIVE",
        "EXTENDED",
    }
    is_leading = bool(
        is_live
        and user_highest_bid > 0
        and current_highest_bid > 0
        and abs(user_highest_bid - current_highest_bid) < 0.01
    )
    payment_pending = bool(
        is_winner
        and (
            status_enum in _PENDING_WINNER
            if status_enum is not None
            else status_val in {"ENDED", "PAYMENT_PENDING"}
        )
    )

    return {
        "userHighestBid": float(user_highest_bid),
        "isLeading": is_leading,
        "isWinner": is_winner,
        "paymentPending": payment_pending,
        "trackingRole": "bidder",
    }


def seller_tracking_fields() -> dict[str, Any]:
    return {"trackingRole": "seller"}
