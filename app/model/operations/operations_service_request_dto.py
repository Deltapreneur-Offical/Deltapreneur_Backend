"""DTOs for operations hire/booking requests."""

from __future__ import annotations

from typing import Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class OperationsServiceRequestCreateBody(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
        extra="forbid",
    )

    operations_service_id: str = Field(..., alias="operationsServiceId")
    full_name: str = Field(..., min_length=1, max_length=255, alias="fullName")
    email: str = Field(..., min_length=3, max_length=255)
    phone: str = Field(..., min_length=10, max_length=64)
    company_name: Optional[str] = Field(default=None, max_length=255, alias="companyName")
    city_state: Optional[str] = Field(default=None, max_length=255, alias="cityState")
    message: Optional[str] = Field(default=None, max_length=5000)
    preferred_timeline: Optional[str] = Field(
        default=None,
        max_length=255,
        alias="preferredTimeline",
    )

    @field_validator("full_name", "email", "phone")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must not be empty")
        return value.strip()


class OperationsPaymentOrderBody(BaseModel):
    """Create a Razorpay order for a Hub Registrar booking."""

    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True, extra="forbid")

    operations_service_id: str = Field(..., alias="operationsServiceId")
    full_name: str = Field(..., min_length=1, max_length=255, alias="fullName")
    email: str = Field(..., min_length=3, max_length=255)
    phone: str = Field(..., min_length=10, max_length=64)
    company_name: Optional[str] = Field(default=None, max_length=255, alias="companyName")
    city_state: Optional[str] = Field(default=None, max_length=255, alias="cityState")
    message: Optional[str] = Field(default=None, max_length=5000)
    preferred_timeline: Optional[str] = Field(
        default=None, max_length=255, alias="preferredTimeline",
    )


class OperationsPaymentVerifyBody(BaseModel):
    """Verify a Razorpay payment for a Hub Registrar booking."""

    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True, extra="forbid")

    request_id: str = Field(..., alias="requestId")
    razorpay_payment_id: str = Field(
        ..., validation_alias=AliasChoices("razorpayPaymentId", "razorpay_payment_id"),
    )
    razorpay_order_id: str = Field(
        ..., validation_alias=AliasChoices("razorpayOrderId", "razorpay_order_id"),
    )
    razorpay_signature: str = Field(
        ..., validation_alias=AliasChoices("razorpaySignature", "razorpay_signature"),
    )


class OperationsServiceRequestStatusBody(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
        extra="forbid",
    )

    status: str = Field(..., min_length=1, max_length=32)

    @field_validator("status")
    @classmethod
    def _valid_status(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"PENDING", "CONTACT_PENDING", "CONTACTED", "CLOSED", "PAYMENT_FAILED"}:
            raise ValueError("status must be PENDING, CONTACT_PENDING, CONTACTED, CLOSED, or PAYMENT_FAILED")
        return normalized
