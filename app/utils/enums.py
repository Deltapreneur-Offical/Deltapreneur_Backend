

"""
Centralized enum definitions for the auction & payment subsystem.

Using str-based enums ensures clean serialization across:
- SQLAlchemy persistence (stored as VARCHAR via Enum type)
- Pydantic v2 request/response models
- JSON API responses
- Redis cache keys (future)
"""

from __future__ import annotations

from enum import Enum


class AuctionStatus(str, Enum):
    """Lifecycle states of an auction."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXTENDED = "EXTENDED"          # anti-snipe extension applied
    ENDED = "ENDED"                # auction time elapsed; awaiting resolution
    UNSOLD = "UNSOLD"              # ended with no qualifying bids
    CLOSED = "CLOSED"              # manually closed listing
    CANCELLED = "CANCELLED"
    TAKEN_DOWN = "TAKEN_DOWN"      # removed by admin
    PAYMENT_PENDING = "PAYMENT_PENDING"
    COMPLETED = "COMPLETED"        # paid + settled


class AuctionDuration(str, Enum):
    """Allowed auction durations selectable at creation time."""

    ONE_DAY = "ONE_DAY"
    SEVEN_DAYS = "SEVEN_DAYS"
    THIRTY_DAYS = "THIRTY_DAYS"
    SIXTY_DAYS = "SIXTY_DAYS"
    NINETY_DAYS = "NINETY_DAYS"

    def to_seconds(self) -> int:
        """Convert duration enum to its equivalent seconds value."""
        mapping = {
            AuctionDuration.ONE_DAY: 24 * 60 * 60,
            AuctionDuration.SEVEN_DAYS: 7 * 24 * 60 * 60,
            AuctionDuration.THIRTY_DAYS: 30 * 24 * 60 * 60,
            AuctionDuration.SIXTY_DAYS: 60 * 24 * 60 * 60,
            AuctionDuration.NINETY_DAYS: 90 * 24 * 60 * 60,
        }
        return mapping[self]


class PaymentStatus(str, Enum):
    """High-level payment lifecycle state."""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class TransactionStatus(str, Enum):
    """Low-level gateway transaction state (per Razorpay attempt)."""

    INITIATED = "INITIATED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    VERIFIED = "VERIFIED"   # signature-verified post payment
