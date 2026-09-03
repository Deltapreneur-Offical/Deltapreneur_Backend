"""CoCreation response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.model.venture.venture_response import AgreementResponse
from app.model.user.public_user import PublicUserResponse
from app.utils.cocreation_enums import (
    SoftwareCategory,
    SoftwarePricingDemand,
    SoftwarePurchaseType,
    SoftwareStatus,
    TechnologyType,
    TechnologyPricingPlanDuration,
)


class _ORMModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        populate_by_name=True,
    )

class TechnologyPricingPlanResponse(_ORMModel):
    id: uuid.UUID
    plan_duration: TechnologyPricingPlanDuration = Field(serialization_alias="planDuration")
    price: float
    is_active: bool = Field(serialization_alias="isActive")


class SoftwareResponse(_ORMModel):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    video_link: Optional[str] = Field(None, serialization_alias="videoLink")
    what_it_does: Optional[str] = Field(None, serialization_alias="whatItDoes")
    how_it_helps: Optional[str] = Field(None, serialization_alias="howItHelps")
    github_link: Optional[str] = Field(None, serialization_alias="githubLink")
    documentation_urls: Optional[str] = Field(None, serialization_alias="documentationUrls")
    download_urls: Optional[str] = Field(None, serialization_alias="downloadUrls")
    image_url: Optional[str] = Field(None, serialization_alias="imageUrl")
    logo_url: Optional[str] = Field(None, serialization_alias="logoUrl")
    logo: Optional[str] = None
    live_demo_link: Optional[str] = Field(None, serialization_alias="liveDemoLink")
    tech_stack: Optional[str] = Field(None, serialization_alias="techStack")
    technology_type: TechnologyType = Field(default=TechnologyType.SOFTWARE, serialization_alias="technologyType")
    category: Optional[SoftwareCategory] = None
    pricing_demand: Optional[SoftwarePricingDemand] = Field(
        None, serialization_alias="pricingDemand"
    )
    price: float
    seller_price: Optional[float] = Field(None, serialization_alias="sellerPrice")
    currency: str = "INR"
    pricing_plans: Optional[list[TechnologyPricingPlanResponse]] = Field(None, serialization_alias="pricingPlans")
    platform_commission_percent: Optional[float] = Field(
        None, serialization_alias="platformCommissionPercent"
    )
    platform_commission_amount: Optional[float] = Field(
        None, serialization_alias="platformCommissionAmount"
    )
    final_listing_price: Optional[float] = Field(
        None, serialization_alias="finalListingPrice"
    )
    software_status: SoftwareStatus = Field(serialization_alias="softwareStatus")
    purchase_type: SoftwarePurchaseType = Field(serialization_alias="purchaseType")
    status: bool
    views: int
    official: bool
    featured: bool
    verified: bool = False
    verified_at: Optional[datetime] = Field(None, serialization_alias="verifiedAt")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    agreement: Optional[AgreementResponse] = None
    listed_by: Optional[PublicUserResponse] = Field(
        None, serialization_alias="listedBy"
    )
    buyer_has_purchased: bool = Field(False, serialization_alias="buyerHasPurchased")
    buyer_completion_status: Optional[str] = Field(
        None, serialization_alias="buyerCompletionStatus"
    )
    purchase_count: int = Field(0, serialization_alias="purchaseCount")


class SoftwareListResponse(BaseModel):
    items: List[SoftwareResponse]
