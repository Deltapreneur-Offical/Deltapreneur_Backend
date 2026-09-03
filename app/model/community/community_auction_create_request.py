from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.entity.community.community_auction_duration import (
    CommunityAuctionDuration,
)
from app.entity.community.work_type import WorkType


class CommunityAuctionCreateRequest(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    # For frontend compatibility, communityId is supplied as query param
    # and injected by the controller before service call.
    community_id: Optional[str] = Field(default=None, alias="communityId")

    duration: CommunityAuctionDuration

    min_bid_price: Decimal = Field(
        alias="minBidPrice",
        gt=0,
    )

    auction_title: str = Field(
        alias="auctionTitle",
        min_length=3,
        max_length=255,
    )

    auction_skills: Optional[str] = Field(
        alias="auctionSkills",
        default=None,
        max_length=1000,
    )

    work_type: Optional[WorkType] = Field(default=None, alias="workType")

    expected_rate: Optional[str] = Field(
        alias="expectedRate",
        default=None,
        max_length=255,
    )

    available_from: Optional[datetime] = Field(default=None, alias="availableFrom")

    additional_info: Optional[str] = Field(
        alias="additionalInfo",
        default=None,
        max_length=2000,
    )

    creation_fee_order_id: Optional[str] = Field(
        default=None,
        alias="creationFeeOrderId",
        description="Verified Razorpay order id for the auction creation fee. Optional for admins.",
    )

    @field_validator("available_from", mode="before")
    @classmethod
    def _parse_available_from(cls, value):
        """Accept ISO datetime; ignore free-text values from UI."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).strip()
        if not text:
            return None
        try:
            # Handle both "...Z" and offset/naive variants.
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            return datetime.fromisoformat(text)
        except ValueError:
            # UI may send hints like "May 2026"; keep request valid.
            return None
