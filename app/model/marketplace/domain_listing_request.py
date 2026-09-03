"""Domain marketplace listing request schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.model.venture.venture_request import AgreementRequest, ContactInfoRequest
from app.utils.marketplace_enums import DomainCategory, PricingDemand, SaleType


class CreateDomainListingRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        populate_by_name=True,
    )

    domain_name: str = Field(..., min_length=1, max_length=255, alias="domainName")
    domain_extension: str = Field(".com", max_length=32, alias="domainExtension")
    domain_category: Optional[DomainCategory] = Field(None, alias="domainCategory")
    asking_price: float = Field(..., ge=0, alias="askingPrice")
    pricing_demand: Optional[PricingDemand] = Field(None, alias="pricingDemand")
    contact_info: Optional[ContactInfoRequest] = Field(None, alias="contactInfo")
    agreement: Optional[AgreementRequest] = None
    sale_type: SaleType = Field(default=SaleType.ONE_TIME, alias="saleType")
    logo_text: Optional[str] = Field(None, alias="logoText", max_length=255)

    @field_validator("pricing_demand", mode="before")
    @classmethod
    def _blank_pricing_demand(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value


class UpdateDomainListingRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        populate_by_name=True,
    )

    domain_name: Optional[str] = Field(None, min_length=1, max_length=255, alias="domainName")
    domain_extension: Optional[str] = Field(None, max_length=32, alias="domainExtension")
    domain_category: Optional[DomainCategory] = Field(None, alias="domainCategory")
    asking_price: Optional[float] = Field(None, ge=0, alias="askingPrice")
    pricing_demand: Optional[PricingDemand] = Field(None, alias="pricingDemand")
    contact_info: Optional[ContactInfoRequest] = Field(None, alias="contactInfo")
    logo_text: Optional[str] = Field(None, alias="logoText", max_length=255)


class DomainVerificationInitRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    method: str = Field(..., description="DNS, META_TAG, or WHOIS_EMAIL")


class DomainVerificationCheckRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    token: Optional[str] = None
