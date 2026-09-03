"""
WebSocket event schemas + builders.

All event payloads are plain JSON-serializable `dict`s with a stable shape:

    {
      "type":      <EventType value>,
      "auction_id": "<uuid-str>",
      "emitted_at": "<iso8601 utc>",
      "data":       { ... event-specific ... }
    }

Builders never raise — they coerce types defensively so a misshapen call from
a service layer can never corrupt the wire format mid-broadcast.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Optional


# --------------------------------------------------------------------------- #
# Event types                                                                 #
# --------------------------------------------------------------------------- #


class EventType(str, Enum):
    BID_PLACED = "BID_PLACED"
    AUCTION_EXTENDED = "AUCTION_EXTENDED"
    AUCTION_ENDED = "AUCTION_ENDED"
    AUCTION_UNSOLD = "AUCTION_UNSOLD"
    USER_OUTBID = "USER_OUTBID"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_COMPLETED = "PAYMENT_COMPLETED"

    # Connection-level system events.
    CONNECTED = "CONNECTED"
    PING = "PING"
    PONG = "PONG"
    ERROR = "ERROR"


# --------------------------------------------------------------------------- #
# Internal helpers                                                            #
# --------------------------------------------------------------------------- #


def _stringify(value: Any) -> Any:
    """Coerce non-JSON-native types (UUID, Decimal, datetime) to strings."""
    if value is None:
        return None
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _stringify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stringify(v) for v in value]
    return value


def _envelope(
    event_type: EventType,
    auction_id: Any,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "type": event_type.value,
        "auction_id": _stringify(auction_id),
        "emitted_at": datetime.now(timezone.utc).isoformat(),
        "data": _stringify(dict(data)),
    }


# --------------------------------------------------------------------------- #
# Builders — one per event type                                               #
# --------------------------------------------------------------------------- #


def build_bid_placed(
    *,
    auction_id: Any,
    bid_id: Any,
    bidder_id: Any,
    bidder_name: str,
    amount: Decimal,
    current_highest_bid: Optional[Decimal],
    total_bids: int,
    end_time: datetime,
    extended: bool,
) -> dict[str, Any]:
    return _envelope(
        EventType.BID_PLACED,
        auction_id,
        {
            "bid_id": bid_id,
            "bidder_id": bidder_id,
            "bidder_name": bidder_name,
            "amount": amount,
            "current_highest_bid": current_highest_bid,
            "total_bids": total_bids,
            "end_time": end_time,
            "extended": extended,
        },
    )


def build_auction_extended(
    *,
    auction_id: Any,
    new_end_time: datetime,
    extended_by_seconds: int,
) -> dict[str, Any]:
    return _envelope(
        EventType.AUCTION_EXTENDED,
        auction_id,
        {
            "new_end_time": new_end_time,
            "extended_by_seconds": extended_by_seconds,
        },
    )


def build_auction_ended(
    *,
    auction_id: Any,
    domain_id: Any,
    winner_id: Any,
    winner_name: str,
    winning_amount: Decimal,
) -> dict[str, Any]:
    return _envelope(
        EventType.AUCTION_ENDED,
        auction_id,
        {
            "domain_id": domain_id,
            "winner_id": winner_id,
            "winner_name": winner_name,
            "winning_amount": winning_amount,
        },
    )


def build_auction_unsold(
    *,
    auction_id: Any,
    domain_id: Any,
    reason: str = "No qualifying bids.",
) -> dict[str, Any]:
    return _envelope(
        EventType.AUCTION_UNSOLD,
        auction_id,
        {"domain_id": domain_id, "reason": reason},
    )


def build_user_outbid(
    *,
    auction_id: Any,
    outbid_user_id: Any,
    new_highest_amount: Decimal,
    new_highest_bidder_name: str,
) -> dict[str, Any]:
    """
    Personal notification — to be dispatched via send_personal_notification,
    NOT broadcast to the whole room.
    """
    return _envelope(
        EventType.USER_OUTBID,
        auction_id,
        {
            "user_id": outbid_user_id,
            "new_highest_amount": new_highest_amount,
            "new_highest_bidder_name": new_highest_bidder_name,
        },
    )


def build_payment_pending(
    *,
    auction_id: Any,
    user_id: int,
    amount: Decimal,
    razorpay_order_id: Optional[str] = None,
) -> dict[str, Any]:
    return _envelope(
        EventType.PAYMENT_PENDING,
        auction_id,
        {
            "user_id": user_id,
            "amount": amount,
            "razorpay_order_id": razorpay_order_id,
        },
    )


def build_payment_completed(
    *,
    auction_id: Any,
    user_id: int,
    amount: Decimal,
    razorpay_order_id: Optional[str] = None,
    paid_at: Optional[datetime] = None,
) -> dict[str, Any]:
    return _envelope(
        EventType.PAYMENT_COMPLETED,
        auction_id,
        {
            "user_id": user_id,
            "amount": amount,
            "razorpay_order_id": razorpay_order_id,
            "paid_at": paid_at,
        },
    )


# --------------------------------------------------------------------------- #
# System events                                                               #
# --------------------------------------------------------------------------- #


def build_connected(
    *,
    auction_id: Any,
    user_id: Any,          # uuid.UUID or None — coerced by _stringify
    connection_id: Any,
) -> dict[str, Any]:
    return _envelope(
        EventType.CONNECTED,
        auction_id,
        {"user_id": user_id, "connection_id": connection_id},
    )


def build_ping() -> dict[str, Any]:
    return {
        "type": EventType.PING.value,
        "emitted_at": datetime.now(timezone.utc).isoformat(),
    }


def build_pong() -> dict[str, Any]:
    return {
        "type": EventType.PONG.value,
        "emitted_at": datetime.now(timezone.utc).isoformat(),
    }


def build_error(message: str, *, code: str = "WS_ERROR") -> dict[str, Any]:
    return {
        "type": EventType.ERROR.value,
        "emitted_at": datetime.now(timezone.utc).isoformat(),
        "data": {"code": code, "message": message},
    }
