"""
Pydantic v2 request model for placing bids.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class PlaceBidRequest(BaseModel):
    """Payload for placing a new bid on an active auction."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    auction_id: Optional[uuid.UUID] = Field(
        default=None,
        description=(
            "UUID of the target auction. Optional for HTTP requests because "
            "the path parameter is authoritative."
        ),
    )

    amount: Decimal = Field(
        ...,
        gt=Decimal("0"),
        description="Bid amount; must be strictly greater than current highest bid.",
    )

    razorpay_order_id: str = Field(
        ...,
        validation_alias=AliasChoices("razorpayOrderId", "razorpay_order_id"),
    )
    razorpay_payment_id: str = Field(
        ...,
        validation_alias=AliasChoices("razorpayPaymentId", "razorpay_payment_id"),
    )
    razorpay_signature: str = Field(
        ...,
        validation_alias=AliasChoices("razorpaySignature", "razorpay_signature"),
    )

    @field_validator("amount")
    @classmethod
    def _validate_money(cls, v: Decimal) -> Decimal:
        # Reject NaN / Infinity / >2dp fractional precision.
        if not v.is_finite():
            raise ValueError("amount must be a finite decimal.")
        if v.as_tuple().exponent < -2:
            raise ValueError("amount must have at most 2 decimal places.")
        return v
