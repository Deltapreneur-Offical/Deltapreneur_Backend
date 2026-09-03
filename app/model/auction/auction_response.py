"""
Pydantic v2 response models for the auction subsystem.

`from_attributes=True` enables ORM-mode (Pydantic v2 replacement for orm_mode).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.utils.enums import AuctionDuration, AuctionStatus


class _ORMModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
    )


class BidResponse(_ORMModel):
    """Serialized representation of a single bid."""

    id: uuid.UUID
    auction_id: uuid.UUID
    bidder_id: uuid.UUID
    bidder_name: str = Field(..., min_length=1, max_length=255)
    amount: Decimal
    is_winning_bid: bool
    created_at: datetime


class WinnerResponse(_ORMModel):
    """Lightweight representation of an auction's current/final winner."""

    user_id: uuid.UUID = Field(..., description="ID of the winning user.")
    name: Optional[str] = Field(default=None, max_length=500)
    winning_amount: Decimal
    won_at: Optional[datetime] = None


class AuctionResponse(_ORMModel):
    """Full single-auction response with nested winner + latest bids."""

    id: uuid.UUID
    domain_id: uuid.UUID
    status: AuctionStatus
    duration: AuctionDuration

    min_bid_price: Decimal
    current_highest_bid: Optional[Decimal] = None
    total_bids: int

    current_winner_id: Optional[uuid.UUID] = None
    winner: Optional[WinnerResponse] = None

    start_time: datetime
    end_time: datetime
    original_end_time: datetime

    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

    recent_bids: List[BidResponse] = Field(
        default_factory=list,
        validation_alias=AliasChoices("recent_bids", "bids"),
    )


class AuctionListResponse(BaseModel):
    """Paginated list-response wrapper."""

    model_config = ConfigDict(from_attributes=True)

    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=200)
    items: List[AuctionResponse]
