"""Domain marketplace listing response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.model.venture.venture_response import AgreementResponse, ContactInfoResponse
from app.model.user.public_user import PublicUserResponse
from app.utils.marketplace_enums import (
    DomainCategory,
    DomainListingStatus,
    DomainListingVerificationStatus,
    MarketplacePaymentStatus,
    PricingDemand,
    SaleType,
    VerificationMethod,
)


class _ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)


class DomainListingResponse(_ORMModel):
    id: uuid.UUID
    domain_name: str
    domain_extension: str
    domain_category: Optional[DomainCategory] = None
    asking_price: float
    seller_price: Optional[float] = None
    listing_price: Optional[float] = None
    commission_percentage: Optional[float] = None
    commission_amount: Optional[float] = None
    seller_payout_amount: Optional[float] = None
    platform_commission_percent: Optional[float] = None
    platform_commission_amount: Optional[float] = None
    final_listing_price: Optional[float] = None
    # Display-only GST / buyer payable. asking_price remains the pre-tax listing L.
    gst_inr: Optional[float] = None
    gst_rate: Optional[float] = None
    gst_enabled: bool = False
    buyer_payable_inr: Optional[float] = None
    pricing_demand: Optional[PricingDemand] = None
    domain_status: DomainListingStatus
    logo: Optional[str] = None
    logo_text: Optional[str] = None
    status: bool
    views: int
    payment_status: Optional[MarketplacePaymentStatus] = None
    purchased_by_user_id: Optional[uuid.UUID] = None
    sold_at: Optional[datetime] = None
    verified: bool
    verification_method: Optional[VerificationMethod] = None
    verified_at: Optional[datetime] = None
    whois_email: Optional[str] = None
    verification_status: DomainListingVerificationStatus = (
        DomainListingVerificationStatus.PENDING
    )
    sale_type: SaleType
    featured: bool
    admin_listed: bool = False
    taken_down: bool = False
    take_down_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    contact_info: Optional[ContactInfoResponse] = None
    agreement: Optional[AgreementResponse] = None
    listed_by: Optional[PublicUserResponse] = None
    listed_by_user_id: Optional[uuid.UUID] = None


class DomainListingListResponse(BaseModel):
    items: List[DomainListingResponse]


class DomainVerificationResponse(BaseModel):
    success: bool
    message: str
    verification_token: Optional[str] = None
    dns_record: Optional[str] = None
    meta_tag: Optional[str] = None
    file_path: Optional[str] = None
    file_content: Optional[str] = None
    instructions: Optional[List[str]] = None


class DomainVerificationOptionsResponse(BaseModel):
    whois_email_enabled: bool
    recommended_methods: List[str]
