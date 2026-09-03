"""Shared Razorpay payment verification request body."""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class RazorpayVerifyRequest(BaseModel):
    # Accept both snake_case and camelCase request keys.
    # Frontend currently sends snake_case while some clients send camelCase.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    razorpay_payment_id: str = Field(
        ...,
        validation_alias=AliasChoices("razorpayPaymentId", "razorpay_payment_id"),
        serialization_alias="razorpayPaymentId",
    )
    razorpay_order_id: str = Field(
        ...,
        validation_alias=AliasChoices("razorpayOrderId", "razorpay_order_id"),
        serialization_alias="razorpayOrderId",
    )
    razorpay_signature: str = Field(
        ...,
        validation_alias=AliasChoices("razorpaySignature", "razorpay_signature"),
        serialization_alias="razorpaySignature",
    )
