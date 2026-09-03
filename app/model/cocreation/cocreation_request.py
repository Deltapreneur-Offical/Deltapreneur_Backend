"""CoCreation (software) request schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.model.venture.venture_request import AgreementRequest
from app.utils.cocreation_enums import (
    SoftwareAuctionDuration,
    SoftwareCategory,
    SoftwarePricingDemand,
    SoftwarePurchaseType,
    TechnologyType,
    TechnologyPricingPlanDuration,
)
from app.utils.field_validators import blank_to_none, normalize_http_url


class CreateSoftwareRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="ignore",
        populate_by_name=True,
    )

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    video_link: Optional[str] = Field(None, max_length=512, alias="videoLink")
    what_it_does: Optional[str] = Field(None, alias="whatItDoes")
    how_it_helps: Optional[str] = Field(None, alias="howItHelps")
    github_link: Optional[str] = Field(None, max_length=512, alias="githubLink")
    documentation_urls: Optional[str] = Field(None, alias="documentationUrls")
    download_urls: Optional[str] = Field(None, alias="downloadUrls")
    live_demo_link: Optional[str] = Field(None, max_length=512, alias="liveDemoLink")
    tech_stack: Optional[str] = Field(None, max_length=512, alias="techStack")
    category: Optional[SoftwareCategory] = None
    technology_type: TechnologyType = Field(default=TechnologyType.SOFTWARE, alias="technologyType")
    pricing_demand: Optional[SoftwarePricingDemand] = Field(
        None,
        alias="pricingDemand",
    )
    price: float = Field(0, ge=0)
    
    # Pricing plans
    pricing_plans: Optional[dict[TechnologyPricingPlanDuration, float]] = Field(None, alias="pricingPlans")

    currency: Optional[str] = None
    purchase_type: SoftwarePurchaseType = Field(
        default=SoftwarePurchaseType.ONE_TIME,
        alias="purchaseType",
    )
    agreement: Optional[AgreementRequest] = None

    min_bid_price: Optional[float] = Field(None, gt=0, alias="minBidPrice")
    auction_duration: Optional[SoftwareAuctionDuration] = Field(
        None,
        alias="auctionDuration",
    )
    auction_rationale: Optional[str] = Field(None, alias="auctionRationale")
    source_code_included: Optional[bool] = Field(None, alias="sourceCodeIncluded")
    support_included: Optional[bool] = Field(None, alias="supportIncluded")
    support_days: Optional[int] = Field(None, ge=0, alias="supportDays")
    transfer_details: Optional[str] = Field(None, alias="transferDetails")
    creation_fee_order_id: Optional[str] = Field(
        None,
        min_length=1,
        validation_alias=AliasChoices("creation_fee_order_id", "creationFeeOrderId"),
    )

    @model_validator(mode="after")
    def _auction_subscription_validation(self) -> "CreateSoftwareRequest":
        """Auction is only allowed for one-time purchases, not subscriptions."""
        if self.purchase_type == SoftwarePurchaseType.AUCTION and self.pricing_plans:
            raise ValueError("Auction is only available for one-time purchases. Subscription plans are not allowed with auction.")
        return self

    @field_validator("category", "pricing_demand", "auction_duration", mode="before")
    @classmethod
    def _empty_optional_enum(cls, v: str | None):
        return blank_to_none(v)

    @field_validator("github_link", "video_link", "live_demo_link", mode="before")
    @classmethod
    def _http_urls(cls, v: str | None) -> str | None:
        raw = blank_to_none(v)
        if raw is None:
            return None
        return normalize_http_url(raw)

    @field_validator("pricing_plans", mode="before")
    @classmethod
    def _convert_pricing_plans(cls, v):
        """Convert array format from frontend to dictionary format."""
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        if isinstance(v, list):
            # Convert array of objects to dictionary
            result = {}
            for item in v:
                if isinstance(item, dict):
                    key = item.get("key")
                    price = item.get("price")
                    enabled = item.get("enabled")
                    # Only add if explicitly enabled and price is greater than 0
                    if key and price is not None and enabled is True:
                        # Map frontend keys to enum values
                        key_mapping = {
                            "1_MONTH": "ONE_MONTH",
                            "3_MONTHS": "THREE_MONTHS",
                            "6_MONTHS": "SIX_MONTHS",
                            "12_MONTHS": "TWELVE_MONTHS",
                        }
                        enum_key = key_mapping.get(key, key)
                        try:
                            price_val = float(price)
                            if price_val > 0:
                                result[enum_key] = price_val
                        except (ValueError, TypeError):
                            continue
            return result if result else None
        return None

    @field_validator("price", mode="before")
    @classmethod
    def _coerce_price(cls, v):
        if v == "" or v is None:
            return 0
        return v


class UpdateSoftwareRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="ignore",
        populate_by_name=True,
    )

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    video_link: Optional[str] = Field(None, alias="videoLink")
    what_it_does: Optional[str] = Field(None, alias="whatItDoes")
    how_it_helps: Optional[str] = Field(None, alias="howItHelps")
    github_link: Optional[str] = Field(None, alias="githubLink")
    documentation_urls: Optional[str] = Field(None, alias="documentationUrls")
    download_urls: Optional[str] = Field(None, alias="downloadUrls")
    live_demo_link: Optional[str] = Field(None, alias="liveDemoLink")
    tech_stack: Optional[str] = Field(None, alias="techStack")
    category: Optional[SoftwareCategory] = None
    pricing_demand: Optional[SoftwarePricingDemand] = Field(
        None,
        alias="pricingDemand",
    )
    price: Optional[float] = Field(None, ge=0)
    pricing_plans: Optional[dict[TechnologyPricingPlanDuration, float]] = Field(None, alias="pricingPlans")
    currency: Optional[str] = None
    status: Optional[bool] = None

    @field_validator("github_link", "video_link", "live_demo_link", mode="before")
    @classmethod
    def _http_urls(cls, v: str | None) -> str | None:
        raw = blank_to_none(v)
        if raw is None:
            return None
        return normalize_http_url(raw)

    @field_validator("pricing_plans", mode="before")
    @classmethod
    def _convert_pricing_plans(cls, v):
        """Convert array format from frontend to dictionary format."""
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        if isinstance(v, list):
            # Convert array of objects to dictionary
            result = {}
            for item in v:
                if isinstance(item, dict):
                    key = item.get("key")
                    price = item.get("price")
                    enabled = item.get("enabled")
                    # Only add if explicitly enabled and price is greater than 0
                    if key and price is not None and enabled is True:
                        # Map frontend keys to enum values
                        key_mapping = {
                            "1_MONTH": "ONE_MONTH",
                            "3_MONTHS": "THREE_MONTHS",
                            "6_MONTHS": "SIX_MONTHS",
                            "12_MONTHS": "TWELVE_MONTHS",
                        }
                        enum_key = key_mapping.get(key, key)
                        try:
                            price_val = float(price)
                            if price_val > 0:
                                result[enum_key] = price_val
                        except (ValueError, TypeError):
                            continue
            return result if result else None
        return None
