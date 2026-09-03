"""Operations service create/update request models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OperationsServiceCreateRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
        extra="forbid",
    )

    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., min_length=1, max_length=64)
    description: Optional[str] = Field(default=None, max_length=5000)
    price: float = Field(..., ge=0)
    is_available: bool = Field(default=True, alias="isAvailable")
    service_type: str = Field(default="virtual_assistance", alias="serviceType")
    government_fees_applicable: bool = Field(default=False, alias="governmentFeesApplicable")
    government_fee_text: str = Field(default="Government fees applicable", alias="governmentFeeText", max_length=255)

    @field_validator("name", "category")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @field_validator("service_type")
    @classmethod
    def _valid_service_type(cls, value: str) -> str:
        normalized = (value or "virtual_assistance").strip().lower()
        if normalized not in {"virtual_assistance", "compliance"}:
            raise ValueError("service_type must be virtual_assistance or compliance")
        return normalized

    @model_validator(mode="after")
    def _validate_price_for_type(self) -> "OperationsServiceCreateRequest":
        if self.service_type == "virtual_assistance" and self.price <= 0:
            raise ValueError("price must be greater than 0 for virtual_assistance services")
        return self


class OperationsServiceUpdateRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
        extra="forbid",
    )

    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., min_length=1, max_length=64)
    description: Optional[str] = Field(default=None, max_length=5000)
    price: float = Field(..., ge=0)
    is_available: bool = Field(..., alias="isAvailable")
    service_type: str = Field(default="virtual_assistance", alias="serviceType")
    government_fees_applicable: bool = Field(default=False, alias="governmentFeesApplicable")
    government_fee_text: str = Field(default="Government fees applicable", alias="governmentFeeText", max_length=255)

    @field_validator("name", "category")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @field_validator("service_type")
    @classmethod
    def _valid_service_type(cls, value: str) -> str:
        normalized = (value or "virtual_assistance").strip().lower()
        if normalized not in {"virtual_assistance", "compliance"}:
            raise ValueError("service_type must be virtual_assistance or compliance")
        return normalized

    @model_validator(mode="after")
    def _validate_price_for_type(self) -> "OperationsServiceUpdateRequest":
        if self.service_type == "virtual_assistance" and self.price <= 0:
            raise ValueError("price must be greater than 0 for virtual_assistance services")
        return self


class OperationsServiceAvailabilityRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    is_available: bool = Field(..., alias="isAvailable")
