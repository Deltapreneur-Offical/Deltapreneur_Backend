"""
Pydantic v2 request models for auction lifecycle endpoints.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.utils.enums import AuctionDuration


# Money is validated as Decimal (no float — avoids IEEE 754 rounding drift).
PositiveMoney = Decimal


def _normalize_legacy_duration(value: object) -> object:
    if isinstance(value, str) and value.strip().upper() == "ONE_HOUR":
        return AuctionDuration.ONE_DAY
    return value


class CreateAuctionRequest(BaseModel):
    """Payload for creating a new auction on a domain."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        populate_by_name=True,
    )

    domain_id: Optional[uuid.UUID] = Field(
        default=None,
        description="ID of the domain being auctioned.",
    )

    min_bid_price: PositiveMoney = Field(
        ...,
        gt=Decimal("0"),
        description="Reserve / minimum-acceptable bid price.",
        validation_alias=AliasChoices("min_bid_price", "minBidPrice"),
    )

    duration: AuctionDuration = Field(
        ...,
        description="Auction duration. Must be one of AuctionDuration values.",
    )

    creation_fee_order_id: Optional[str] = Field(
        default=None,
        description="Verified Razorpay order id for the auction creation fee.",
        validation_alias=AliasChoices("creation_fee_order_id", "creationFeeOrderId"),
    )

    @field_validator("min_bid_price")
    @classmethod
    def _quantize_money(cls, v: Decimal) -> Decimal:
        # Enforce 2-decimal precision; reject extra fractional digits.
        if v.as_tuple().exponent < -2:
            raise ValueError("min_bid_price must have at most 2 decimal places.")
        return v

    @field_validator("duration", mode="before")
    @classmethod
    def _coerce_legacy_duration(cls, value: object) -> object:
        return _normalize_legacy_duration(value)


class ReAuctionRequest(BaseModel):
    """
    Payload for re-listing a previously UNSOLD / CANCELLED auction.

    `min_bid_price` is optional — if omitted the previous reserve is reused.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        populate_by_name=True,
    )

    domain_id: uuid.UUID = Field(...)

    duration: AuctionDuration = Field(...)

    min_bid_price: Optional[PositiveMoney] = Field(
        default=None,
        gt=Decimal("0"),
        description="Optional new reserve price. Defaults to prior auction's reserve.",
        validation_alias=AliasChoices("min_bid_price", "minBidPrice"),
    )
    creation_fee_order_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("creation_fee_order_id", "creationFeeOrderId"),
    )

    @field_validator("min_bid_price")
    @classmethod
    def _quantize_money(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is None:
            return v
        if v.as_tuple().exponent < -2:
            raise ValueError("min_bid_price must have at most 2 decimal places.")
        return v

    @field_validator("duration", mode="before")
    @classmethod
    def _coerce_legacy_duration(cls, value: object) -> object:
        return _normalize_legacy_duration(value)
