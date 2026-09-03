"""Venture API response schemas — public vs owner shapes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.entity.coventure.venture_entity import Venture
from app.entity.user.app_user import AppUser
from app.integrations.s3.supabase_storage import resolve_media_url
from app.model.user.public_user import (
    OwnerUserSummaryResponse,
    PublicUserResponse,
    to_owner_user,
    to_public_user,
)
from app.utils.equity_percent import normalize_equity_percent
from app.utils.money import round_inr
from app.utils.venture_enums import (
    Industry,
    VentureAcquisitionFlow,
    VentureDealType,
    VentureListingApprovalStatus,
    VentureListingMode,
    VentureListingStatus,
    VentureSaleType,
    VentureStage,
    VentureType,
    VentureVerificationStatus,
)

def _to_camel(field_name: str) -> str:
    parts = field_name.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def _to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


class _ORMModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        populate_by_name=True,
        alias_generator=_to_camel,
    )


class BrandDetailsResponse(_ORMModel):
    id: uuid.UUID
    description: Optional[str] = None
    brand_name: Optional[str] = None
    website: Optional[str] = None
    video_url: Optional[str] = None
    industry: Optional[Industry] = None
    deal_value: Optional[int] = None
    seller_deal_value: Optional[int] = None
    venture_image_url: Optional[str] = None
    venture_type: Optional[VentureType] = None

    @field_validator("deal_value", "seller_deal_value", mode="before")
    @classmethod
    def _normalize_inr_amounts(cls, value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            rounded = round_inr(value)
            return rounded if rounded > 0 else None
        except (TypeError, ValueError):
            return None


class ContactInfoResponse(_ORMModel):
    id: uuid.UUID
    email: Optional[str] = None
    phone_number: Optional[str] = None


class AgreementResponse(_ORMModel):
    id: uuid.UUID
    terms: bool


class VentureRoleResponse(_ORMModel):
    id: uuid.UUID
    type: Optional[str] = None
    title: Optional[str] = None
    skill_domain: Optional[str] = None
    description: Optional[str] = None
    commitment: Optional[str] = None
    location: Optional[str] = None
    experience_level: Optional[str] = None
    equity_min: Optional[float] = None
    equity_max: Optional[float] = None
    vesting_terms: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    investment_min: Optional[float] = None
    investment_max: Optional[float] = None
    investment_seeking: Optional[float] = Field(
        None,
        ge=0,
        validation_alias=AliasChoices("investment_seeking", "investmentSeeking"),
    )
    sort_order: int = 0


class PublicCompanyProfileResponse(_ORMModel):
    """Public + Optional Public tiers only.

    Never includes legal_entity_name, registration_number, incorporation_date,
    company_type, or completion metadata (Private/Admin-only tiers).
    """

    company_name: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    business_description: Optional[str] = None
    products_services: Optional[str] = None
    target_market: Optional[str] = None
    business_model: Optional[str] = None
    annual_revenue_inr: Optional[int] = None
    current_year_revenue_inr: Optional[int] = None
    previous_year_revenue_inr: Optional[int] = None
    two_years_ago_revenue_inr: Optional[int] = None
    profitability_status: Optional[str] = None
    profitability_amount_inr: Optional[int] = None
    funding_raised_summary: Optional[str] = None
    valuation_inr: Optional[int] = None
    market_cap_inr: Optional[int] = None
    founder_name: Optional[str] = None
    team_size: Optional[int] = None
    key_team_members: Optional[str] = None
    team_members: Optional[list] = None
    customer_count: Optional[int] = None
    user_base: Optional[str] = None
    growth_metrics: Optional[str] = None
    market_reach: Optional[str] = None
    public_contact_person: Optional[str] = None
    public_email: Optional[str] = None
    public_phone_number: Optional[str] = None


class CompanyProfileResponse(PublicCompanyProfileResponse):
    """Owner/admin shape — adds Private-tier fields and completion metadata."""

    legal_entity_name: Optional[str] = None
    registration_number: Optional[str] = None
    incorporation_date: Optional[str] = None
    company_type: Optional[str] = None
    is_complete: bool = False
    completed_at: Optional[datetime] = None


class VentureVerificationDocumentResponse(_ORMModel):
    id: uuid.UUID
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    created_at: Optional[datetime] = None


def _resolve_coventure_investment_seeking(venture: Venture) -> float | None:
    """Primary co-venture card amount — role investment, then brand/profile fallbacks."""
    if (venture.listing_mode or VentureListingMode.VENTURE) != VentureListingMode.CO_VENTURE:
        return None
    for role in venture.roles or []:
        raw = role.investment_min if role.investment_min is not None else role.investment_max
        if raw is None:
            continue
        value = float(raw)
        if value >= 0:
            return value
    brand = venture.brand_details
    if brand is not None:
        for candidate in (brand.seller_deal_value, brand.deal_value):
            if candidate is None:
                continue
            value = float(candidate)
            if value >= 0:
                return value
    profile = getattr(venture, "company_profile", None)
    valuation = getattr(profile, "valuation_inr", None) if profile else None
    if valuation is not None and float(valuation) >= 0:
        return float(valuation)
    return None


class PublicVentureResponse(_ORMModel):
    """Marketplace catalog — no contact PII, agreement, or GST legal name."""

    id: uuid.UUID
    status: bool
    views: int
    like_count: int = Field(alias="likeCount", default=0)
    co_venture_application_count: int = Field(alias="coVentureApplicationCount", default=0)
    pitch_application_count: int = Field(alias="pitchApplicationCount", default=0)
    stage: Optional[VentureStage] = None
    current_problem: Optional[str] = None
    looking_for: Optional[str] = None
    sale_type: VentureSaleType
    listing_mode: VentureListingMode = VentureListingMode.VENTURE
    venture_listing_status: VentureListingStatus = VentureListingStatus.ACTIVE
    deal_type: Optional[VentureDealType] = None
    acquisition_flow: Optional[VentureAcquisitionFlow] = None
    company_profile: Optional[PublicCompanyProfileResponse] = None
    equity_percent_offered: Optional[float] = None
    investment_seeking: Optional[float] = Field(
        None,
        validation_alias=AliasChoices("investment_seeking", "investmentSeeking"),
    )
    ownership_liquidation_percent: Optional[float] = Field(
        None,
        serialization_alias="ownershipLiquidationPercent",
    )
    valuation_amount: Optional[int] = None
    verified: bool = False
    verified_at: Optional[datetime] = None
    verification_requested: bool = False
    verification_video_url: Optional[str] = None
    verification_status: VentureVerificationStatus = VentureVerificationStatus.NONE
    gstin_verified: bool = False
    listing_approval_status: VentureListingApprovalStatus = (
        VentureListingApprovalStatus.PENDING_APPROVAL
    )
    listing_rejection_reason: Optional[str] = None
    featured: bool = False
    created_at: datetime
    updated_at: datetime
    brand_details: Optional[BrandDetailsResponse] = None
    listed_by: Optional[PublicUserResponse] = None
    roles: List[VentureRoleResponse] = Field(default_factory=list)

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        alias_generator=_to_camel,
    )


class VentureResponse(_ORMModel):
    """Owner/admin view — full listing including contact and agreement."""

    id: uuid.UUID
    status: bool
    views: int
    co_venture_application_count: int = Field(alias="coVentureApplicationCount", default=0)
    pitch_application_count: int = Field(alias="pitchApplicationCount", default=0)
    stage: Optional[VentureStage] = None
    current_problem: Optional[str] = None
    looking_for: Optional[str] = None
    sale_type: VentureSaleType
    listing_mode: VentureListingMode = VentureListingMode.VENTURE
    venture_listing_status: VentureListingStatus = VentureListingStatus.ACTIVE
    deal_type: Optional[VentureDealType] = None
    acquisition_flow: Optional[VentureAcquisitionFlow] = None
    company_profile: Optional[CompanyProfileResponse] = None
    equity_percent_offered: Optional[float] = None
    ownership_liquidation_percent: Optional[float] = Field(
        None,
        serialization_alias="ownershipLiquidationPercent",
    )
    valuation_amount: Optional[int] = None
    commission_percent_applied: Optional[float] = None
    verified: bool = False
    verified_at: Optional[datetime] = None
    verification_requested: bool = False
    verification_video_url: Optional[str] = None
    verification_status: VentureVerificationStatus = VentureVerificationStatus.NONE
    verification_rejection_reason: Optional[str] = None
    verification_documents: List[VentureVerificationDocumentResponse] = Field(default_factory=list)
    gstin_verified: bool = False
    gstin_legal_name: Optional[str] = None
    listing_approval_status: VentureListingApprovalStatus = (
        VentureListingApprovalStatus.PENDING_APPROVAL
    )
    listing_rejection_reason: Optional[str] = None
    listing_approved_at: Optional[datetime] = None
    featured: bool = False
    created_at: datetime
    updated_at: datetime
    brand_details: Optional[BrandDetailsResponse] = None
    contact_info: Optional[ContactInfoResponse] = None
    agreement: Optional[AgreementResponse] = None
    listed_by: Optional[OwnerUserSummaryResponse] = None
    roles: List[VentureRoleResponse] = Field(default_factory=list)

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        alias_generator=_to_camel,
    )


def _resolve_verification_status(venture: Venture) -> VentureVerificationStatus:
    status = getattr(venture, "verification_status", None)
    if status is None:
        return VentureVerificationStatus.NONE
    return status


def _serialize_roles(venture: Venture) -> list[VentureRoleResponse]:
    roles: list[VentureRoleResponse] = []
    for role in venture.roles:
        base = VentureRoleResponse.model_validate(role)
        equity = role.equity_min if role.equity_min is not None else role.equity_max
        investment = role.investment_min if role.investment_min is not None else role.investment_max
        roles.append(
            base.model_copy(
                update={
                    "title": role.title,
                    "equity_min": equity,
                    "investment_min": investment,
                    "investment_seeking": investment,
                }
            )
        )
    return roles


def _resolve_media_url(value: str | None) -> str | None:
    if not value:
        return None
    return resolve_media_url(value)


def _serialize_verification_documents(venture: Venture) -> list[VentureVerificationDocumentResponse]:
    docs = getattr(venture, "verification_documents", None) or []
    return [
        VentureVerificationDocumentResponse(
            id=doc.id,
            file_url=_resolve_media_url(doc.file_url),
            file_name=doc.file_name,
            created_at=doc.created_at,
        )
        for doc in docs
    ]


def _brand_details_response(brand) -> BrandDetailsResponse | None:
    if brand is None:
        return None
    data = BrandDetailsResponse.model_validate(brand)
    if not data.venture_image_url:
        return data
    return data.model_copy(
        update={"venture_image_url": resolve_media_url(data.venture_image_url)}
    )


def _public_company_profile(venture: Venture) -> PublicCompanyProfileResponse | None:
    profile = getattr(venture, "company_profile", None)
    if profile is None:
        return None
    return PublicCompanyProfileResponse.model_validate(profile)


def _owner_company_profile(venture: Venture) -> CompanyProfileResponse | None:
    profile = getattr(venture, "company_profile", None)
    if profile is None:
        return None
    return CompanyProfileResponse(
        company_name=profile.company_name,
        industry=profile.industry,
        website=profile.website,
        business_description=profile.business_description,
        products_services=profile.products_services,
        target_market=profile.target_market,
        business_model=profile.business_model,
        annual_revenue_inr=profile.annual_revenue_inr or profile.current_year_revenue_inr,
        current_year_revenue_inr=profile.current_year_revenue_inr,
        previous_year_revenue_inr=profile.previous_year_revenue_inr,
        two_years_ago_revenue_inr=profile.two_years_ago_revenue_inr,
        profitability_status=profile.profitability_status,
        profitability_amount_inr=profile.profitability_amount_inr,
        funding_raised_summary=profile.funding_raised_summary,
        valuation_inr=profile.valuation_inr,
        market_cap_inr=profile.market_cap_inr,
        founder_name=profile.founder_name,
        team_size=profile.team_size,
        key_team_members=profile.key_team_members,
        team_members=profile.team_members,
        customer_count=profile.customer_count,
        user_base=profile.user_base,
        growth_metrics=profile.growth_metrics,
        market_reach=profile.market_reach,
        public_contact_person=profile.public_contact_person,
        public_email=profile.public_email,
        public_phone_number=profile.public_phone_number,
        legal_entity_name=profile.legal_entity_name,
        registration_number=profile.registration_number,
        incorporation_date=(
            profile.incorporation_date.isoformat() if profile.incorporation_date else None
        ),
        company_type=profile.company_type,
        is_complete=profile.is_complete,
        completed_at=profile.completed_at,
    )


def serialize_public_venture(
    venture: Venture,
    *,
    pitch_application_count: int | None = None,
) -> PublicVentureResponse:
    """Public marketplace shape — never includes contact email/phone or owner email."""
    pitch_count = pitch_application_count if pitch_application_count is not None else 0
    return PublicVentureResponse(
        id=venture.id,
        status=venture.status,
        views=venture.views,
        co_venture_application_count=venture.co_venture_application_count,
        pitch_application_count=pitch_count,
        stage=venture.stage,
        current_problem=venture.current_problem,
        looking_for=venture.looking_for,
        sale_type=venture.sale_type,
        listing_mode=venture.listing_mode or VentureListingMode.VENTURE,
        venture_listing_status=venture.venture_listing_status or VentureListingStatus.ACTIVE,
        deal_type=venture.deal_type,
        acquisition_flow=venture.acquisition_flow,
        company_profile=_public_company_profile(venture),
        equity_percent_offered=normalize_equity_percent(venture.equity_percent_offered),
        investment_seeking=_resolve_coventure_investment_seeking(venture),
        ownership_liquidation_percent=normalize_equity_percent(venture.equity_percent_offered),
        valuation_amount=venture.valuation_amount,
        verified=venture.verified,
        verified_at=venture.verified_at,
        verification_requested=bool(getattr(venture, "verification_requested", False)),
        verification_video_url=getattr(venture, "verification_video_url", None),
        verification_status=_resolve_verification_status(venture),
        gstin_verified=venture.gstin_verified,
        listing_approval_status=venture.listing_approval_status,
        listing_rejection_reason=venture.listing_rejection_reason,
        featured=venture.featured,
        created_at=venture.created_at,
        updated_at=venture.updated_at,
        brand_details=_brand_details_response(venture.brand_details),
        listed_by=to_public_user(venture.listed_by) if venture.listed_by else None,
        roles=_serialize_roles(venture),
    )


def serialize_owner_venture(
    venture: Venture,
    *,
    lister: AppUser | None = None,
    pitch_application_count: int | None = None,
) -> VentureResponse:
    """Owner/admin shape — full venture; listed_by always via to_owner_user (never ORM dump)."""
    owner_user = venture.listed_by or lister
    pitch_count = pitch_application_count if pitch_application_count is not None else 0
    return VentureResponse(
        id=venture.id,
        status=venture.status,
        views=venture.views,
        co_venture_application_count=venture.co_venture_application_count,
        pitch_application_count=pitch_count,
        stage=venture.stage,
        current_problem=venture.current_problem,
        looking_for=venture.looking_for,
        sale_type=venture.sale_type,
        listing_mode=venture.listing_mode or VentureListingMode.VENTURE,
        venture_listing_status=venture.venture_listing_status or VentureListingStatus.ACTIVE,
        deal_type=venture.deal_type,
        acquisition_flow=venture.acquisition_flow,
        company_profile=_owner_company_profile(venture),
        equity_percent_offered=normalize_equity_percent(venture.equity_percent_offered),
        ownership_liquidation_percent=normalize_equity_percent(venture.equity_percent_offered),
        valuation_amount=venture.valuation_amount,
        commission_percent_applied=venture.commission_percent_applied,
        verified=venture.verified,
        verified_at=venture.verified_at,
        verification_requested=bool(getattr(venture, "verification_requested", False)),
        verification_video_url=getattr(venture, "verification_video_url", None),
        verification_status=_resolve_verification_status(venture),
        verification_rejection_reason=getattr(venture, "verification_rejection_reason", None),
        verification_documents=_serialize_verification_documents(venture),
        gstin_verified=venture.gstin_verified,
        gstin_legal_name=venture.gstin_legal_name,
        listing_approval_status=venture.listing_approval_status,
        listing_rejection_reason=venture.listing_rejection_reason,
        listing_approved_at=venture.listing_approved_at,
        featured=venture.featured,
        created_at=venture.created_at,
        updated_at=venture.updated_at,
        brand_details=_brand_details_response(venture.brand_details),
        contact_info=(
            ContactInfoResponse.model_validate(venture.contact_info)
            if venture.contact_info
            else None
        ),
        agreement=(
            AgreementResponse.model_validate(venture.agreement)
            if venture.agreement
            else None
        ),
        listed_by=to_owner_user(owner_user) if owner_user else None,
        roles=_serialize_roles(venture),
    )


class PublicVentureListResponse(BaseModel):
    items: List[PublicVentureResponse]
    total: int | None = None
    page: int | None = None
    page_size: int | None = Field(None, serialization_alias="pageSize")
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)


class VentureListResponse(BaseModel):
    items: List[VentureResponse]
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)


class CoVentureStatusResponse(BaseModel):
    applied: bool
    status: Optional[str] = None


class CoVentureVentureBrandSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    brand_name: Optional[str] = Field(None, serialization_alias="brandName")
    industry: Optional[Industry] = None
    venture_type: Optional[VentureType] = Field(None, serialization_alias="ventureType")
    equity_percent_offered: Optional[float] = Field(
        None, serialization_alias="equityPercentOffered",
    )
    venture_image_url: Optional[str] = Field(None, serialization_alias="ventureImageUrl")


class CoVentureVentureSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: uuid.UUID
    brand_details: Optional[CoVentureVentureBrandSummary] = Field(
        None,
        serialization_alias="brandDetails",
    )


class CoVentureResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: uuid.UUID
    venture_id: uuid.UUID
    applicant_user_id: uuid.UUID
    full_name: Optional[str] = Field(None, serialization_alias="fullName")
    phone: Optional[str] = None
    location: Optional[str] = None
    gstin: Optional[str] = Field(None, serialization_alias="gstNo")
    description: Optional[str] = None
    experience_summary: Optional[str] = Field(
        None, serialization_alias="experienceSummary",
    )
    skills: Optional[str] = None
    portfolio_url: Optional[str] = Field(None, serialization_alias="portfolioUrl")
    linkedin_url: Optional[str] = Field(None, serialization_alias="linkedinUrl")
    previous_ventures: Optional[str] = Field(
        None, serialization_alias="previousVentures",
    )
    relevant_experience: Optional[str] = Field(
        None, serialization_alias="relevantExperience",
    )
    motivation: Optional[str] = None
    contribution_plan: Optional[str] = Field(
        None, serialization_alias="contributionPlan",
    )
    video_introduction_url: Optional[str] = Field(
        None, serialization_alias="videoIntroductionUrl",
    )
    status: str
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    venture: Optional[CoVentureVentureSummary] = None


class GstinVerifyResponse(BaseModel):
    verified: bool
    message: Optional[str] = None
    legal_name: Optional[str] = Field(None, alias="legalName")
    trade_name: Optional[str] = Field(None, alias="tradeName")
    error: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)
