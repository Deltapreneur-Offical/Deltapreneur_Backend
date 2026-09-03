"""Venture API request schemas."""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.utils.field_validators import (
    blank_to_none,
    normalize_e164_phone,
    normalize_gstin,
    normalize_http_url,
    normalize_optional_email,
    normalize_optional_non_whitespace,
    normalize_profile_phone,
)
from app.utils.money import round_inr
from app.utils.venture_enums import (
    Industry,
    VentureAcquisitionFlow,
    VentureDealType,
    VentureListingMode,
    VentureSaleType,
    VentureStage,
    VentureType,
    VentureVerificationStatus,
)


def _to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


class BrandDetailsRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        populate_by_name=True,
    )

    description: Optional[str] = Field(None, max_length=2000)
    brand_name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        validation_alias=AliasChoices("brand_name", "brandName"),
    )
    website: Optional[str] = Field(None, max_length=512)
    video_url: Optional[str] = Field(
        None,
        max_length=512,
        validation_alias=AliasChoices("video_url", "videoUrl"),
    )
    venture_image_url: Optional[str] = Field(
        None,
        max_length=1024,
        validation_alias=AliasChoices(
            "venture_image_url",
            "ventureImageUrl",
            "reference_image_url",
            "referenceImageUrl",
        ),
    )
    industry: Optional[Industry] = None
    deal_value: Optional[int] = Field(
        None,
        ge=0,
        validation_alias=AliasChoices("deal_value", "dealValue"),
    )
    currency: Optional[str] = None

    @field_validator("deal_value", mode="before")
    @classmethod
    def _round_deal_value(cls, v: object) -> int | None:
        if v is None or v == "":
            return None
        try:
            return round_inr(v)
        except (TypeError, ValueError):
            return None

    venture_type: Optional[VentureType] = Field(
        None,
        validation_alias=AliasChoices("venture_type", "ventureType"),
    )

    @field_validator("brand_name")
    @classmethod
    def _brand_name_non_empty(cls, v: str | None) -> str | None:
        return normalize_optional_non_whitespace(v, field="brand_name")

    @field_validator("description")
    @classmethod
    def _description_non_empty_if_set(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None

    @field_validator("website", "video_url", "venture_image_url")
    @classmethod
    def _http_urls(cls, v: str | None) -> str | None:
        if v is None:
            return None
        raw = str(v).strip()
        if not raw:
            return None
        return normalize_http_url(raw)


class ContactInfoRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        populate_by_name=True,
        alias_generator=_to_camel,
    )

    email: str | None = Field(None, max_length=255)
    phone_number: str | None = Field(
        None,
        max_length=16,
        validation_alias=AliasChoices("phone_number", "phoneNumber"),
    )

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return normalize_optional_email(v)

    @field_validator("phone_number", mode="before")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        from app.utils.field_validators import normalize_profile_phone

        return normalize_profile_phone(v)


class AgreementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terms: bool = False


class _BlankOptionalStringsMixin(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _blank_optional_strings(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        return {
            key: (
                blank_to_none(val)
                if isinstance(val, str) and not isinstance(val, Enum)
                else val
            )
            for key, val in data.items()
        }


class TeamMemberRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        populate_by_name=True,
        alias_generator=_to_camel,
    )

    name: str = Field(..., min_length=1, max_length=255)
    role: str = Field(..., min_length=1, max_length=255)
    equity_percent: float = Field(..., gt=0, le=100)
    linkedin_url: Optional[str] = Field(None, max_length=512)

    @field_validator("linkedin_url")
    @classmethod
    def _linkedin(cls, v: str | None) -> str | None:
        return normalize_http_url(blank_to_none(v))


class VentureRoleRequest(_BlankOptionalStringsMixin):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        populate_by_name=True,
        alias_generator=_to_camel,
    )

    type: Optional[str] = Field(None, max_length=100)
    title: Optional[str] = Field(
        None,
        max_length=255,
        validation_alias=AliasChoices("title", "roleOffer"),
    )
    role_offer: Optional[str] = Field(
        None,
        max_length=255,
        validation_alias=AliasChoices("role_offer", "roleOffer"),
    )
    equity_offer: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        validation_alias=AliasChoices("equity_offer", "equityOffer"),
    )
    investment_seeking: Optional[float] = Field(
        None,
        ge=0,
        validation_alias=AliasChoices("investment_seeking", "investmentSeeking"),
    )
    skill_domain: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    commitment: Optional[str] = Field(None, max_length=255)
    location: Optional[str] = Field(None, max_length=255)
    experience_level: Optional[str] = Field(None, max_length=100)
    equity_min: Optional[float] = Field(None, ge=0)
    equity_max: Optional[float] = Field(None, ge=0)
    vesting_terms: Optional[str] = Field(None, max_length=2000)
    salary_min: Optional[float] = Field(None, ge=0)
    salary_max: Optional[float] = Field(None, ge=0)
    budget_min: Optional[float] = Field(None, ge=0)
    budget_max: Optional[float] = Field(None, ge=0)
    investment_min: Optional[float] = Field(None, ge=0)
    investment_max: Optional[float] = Field(None, ge=0)


class CreateVentureRequest(_BlankOptionalStringsMixin):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="ignore",
        populate_by_name=True,
    )

    brand_details: Optional[BrandDetailsRequest] = Field(
        None,
        validation_alias=AliasChoices("brand_details", "brandDetails"),
    )
    contact_info: Optional[ContactInfoRequest] = Field(
        None,
        validation_alias=AliasChoices("contact_info", "contactInfo"),
    )
    agreement: Optional[AgreementRequest] = None
    status: bool = True
    stage: Optional[VentureStage] = None
    current_problem: Optional[str] = Field(
        None,
        max_length=2000,
        validation_alias=AliasChoices("current_problem", "currentProblem"),
    )
    looking_for: Optional[str] = Field(
        None,
        max_length=2000,
        validation_alias=AliasChoices("looking_for", "lookingFor"),
    )

    @field_validator("current_problem", mode="before")
    @classmethod
    def _current_problem(cls, v: str | None) -> str | None:
        return blank_to_none(v)

    @field_validator("looking_for", mode="before")
    @classmethod
    def _looking_for_create(cls, v: str | None) -> str | None:
        return blank_to_none(v)
    sale_type: VentureSaleType = Field(
        VentureSaleType.REGULAR,
        validation_alias=AliasChoices("sale_type", "saleType"),
    )
    listing_mode: VentureListingMode = Field(
        VentureListingMode.VENTURE,
        validation_alias=AliasChoices("listing_mode", "listingMode"),
    )
    creation_fee_order_id: Optional[str] = Field(
        None,
        min_length=1,
        validation_alias=AliasChoices("creation_fee_order_id", "creationFeeOrderId"),
    )
    roles: List[VentureRoleRequest] = Field(default_factory=list)
    deal_type: VentureDealType | None = Field(
        None,
        validation_alias=AliasChoices("deal_type", "dealType"),
    )
    equity_percent_offered: float | None = Field(
        None,
        ge=0,
        le=100,
        validation_alias=AliasChoices("equity_percent_offered", "equityPercentOffered"),
    )
    valuation_amount: int | None = Field(
        None,
        ge=0,
        validation_alias=AliasChoices("valuation_amount", "valuationAmount"),
    )
    acquisition_flow: VentureAcquisitionFlow | None = Field(
        None,
        validation_alias=AliasChoices("acquisition_flow", "acquisitionFlow"),
    )
    company_profile: Optional["CompanyProfileRequest"] = Field(
        None,
        validation_alias=AliasChoices("company_profile", "companyProfile"),
    )
    verification_requested: bool = Field(
        False,
        validation_alias=AliasChoices("verification_requested", "verificationRequested"),
    )
    verification_video_url: Optional[str] = Field(
        None,
        max_length=512,
        validation_alias=AliasChoices("verification_video_url", "verificationVideoUrl"),
    )

    @field_validator("verification_video_url")
    @classmethod
    def _verification_video(cls, v: str | None) -> str | None:
        return normalize_http_url(blank_to_none(v))

    @model_validator(mode="after")
    def _validate_listing(self) -> "CreateVentureRequest":
        if self.listing_mode == VentureListingMode.VENTURE:
            ownership_pct = self.equity_percent_offered
            if ownership_pct is None and self.deal_type is not None:
                if self.deal_type == VentureDealType.FULL_ACQUISITION:
                    ownership_pct = 100.0
                elif self.deal_type == VentureDealType.EQUITY_SALE:
                    ownership_pct = self.equity_percent_offered
            if ownership_pct is None or ownership_pct <= 0 or ownership_pct > 100:
                raise ValueError(
                    "equity_percent_offered (ownership liquidation %) is required "
                    "for venture listings and must be > 0 and <= 100."
                )
            object.__setattr__(self, "equity_percent_offered", ownership_pct)
            object.__setattr__(self, "acquisition_flow", VentureAcquisitionFlow.SELLER_SELECTS)
        elif self.listing_mode == VentureListingMode.CO_VENTURE:
            object.__setattr__(self, "acquisition_flow", None)
            if not self.roles:
                raise ValueError("At least one partnership role is required for co-venture listings.")
            for role in self.roles:
                role_title = (role.title or role.role_offer or "").strip()
                if not role_title:
                    raise ValueError("Each partnership role must include a role offer.")
                equity = role.equity_offer if role.equity_offer is not None else role.equity_min
                if equity is None or equity < 0 or equity > 100:
                    raise ValueError("Each partnership role must include equity offer between 0 and 100.")
                investment = (
                    role.investment_seeking
                    if role.investment_seeking is not None
                    else role.investment_min
                )
                if investment is None or investment < 0:
                    raise ValueError(
                        "Each partnership role must include investment seeking (0 or more)."
                    )
        else:
            object.__setattr__(self, "acquisition_flow", None)
        return self


class UpdateVentureRequest(_BlankOptionalStringsMixin):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="ignore",
        populate_by_name=True,
    )

    brand_details: Optional[BrandDetailsRequest] = Field(
        None,
        validation_alias=AliasChoices("brand_details", "brandDetails"),
    )
    contact_info: Optional[ContactInfoRequest] = Field(
        None,
        validation_alias=AliasChoices("contact_info", "contactInfo"),
    )
    agreement: Optional[AgreementRequest] = None
    status: Optional[bool] = None
    stage: Optional[VentureStage] = None
    current_problem: Optional[str] = Field(
        None,
        max_length=2000,
        validation_alias=AliasChoices("current_problem", "currentProblem"),
    )
    looking_for: Optional[str] = Field(
        None,
        max_length=2000,
        validation_alias=AliasChoices("looking_for", "lookingFor"),
    )

    @field_validator("current_problem", mode="before")
    @classmethod
    def _current_problem(cls, v: str | None) -> str | None:
        return blank_to_none(v)

    @field_validator("looking_for", mode="before")
    @classmethod
    def _looking_for(cls, v: str | None) -> str | None:
        return blank_to_none(v)
    sale_type: Optional[VentureSaleType] = Field(
        None,
        validation_alias=AliasChoices("sale_type", "saleType"),
    )
    roles: Optional[List[VentureRoleRequest]] = None
    equity_percent_offered: float | None = Field(
        None,
        ge=0,
        le=100,
        validation_alias=AliasChoices("equity_percent_offered", "equityPercentOffered"),
    )
    acquisition_flow: Optional[VentureAcquisitionFlow] = Field(
        None,
        validation_alias=AliasChoices("acquisition_flow", "acquisitionFlow"),
    )
    company_profile: Optional["CompanyProfileRequest"] = Field(
        None,
        validation_alias=AliasChoices("company_profile", "companyProfile"),
    )
    verification_requested: Optional[bool] = Field(
        None,
        validation_alias=AliasChoices("verification_requested", "verificationRequested"),
    )
    verification_video_url: Optional[str] = Field(
        None,
        max_length=512,
        validation_alias=AliasChoices("verification_video_url", "verificationVideoUrl"),
    )
    currency: Optional[str] = None

    @field_validator("verification_video_url")
    @classmethod
    def _verification_video_update(cls, v: str | None) -> str | None:
        return normalize_http_url(blank_to_none(v))

    @model_validator(mode="after")
    def _validate_update(self) -> "UpdateVentureRequest":
        return self


class CompanyProfileRequest(BaseModel):
    """Company profile payload (nested in venture create/update or sent standalone).

    Required-for-completion fields: company_name, industry, website,
    business_description, products_services, target_market, business_model,
    public_contact_person, public_email. All fields are optional here so owners
    can save partial drafts; completion is computed server-side.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="ignore",
        populate_by_name=True,
        alias_generator=_to_camel,
    )

    company_name: Optional[str] = Field(None, max_length=255)
    legal_entity_name: Optional[str] = Field(None, max_length=512)
    registration_number: Optional[str] = Field(None, max_length=128)
    incorporation_date: Optional[str] = Field(None, max_length=10)
    company_type: Optional[str] = Field(None, max_length=64)
    industry: Optional[str] = Field(None, max_length=128)
    website: Optional[str] = Field(None, max_length=512)
    business_description: Optional[str] = Field(None, max_length=8000)
    products_services: Optional[str] = Field(None, max_length=8000)
    target_market: Optional[str] = Field(None, max_length=8000)
    business_model: Optional[str] = Field(None, max_length=8000)
    annual_revenue_inr: Optional[int] = Field(None, ge=0)
    current_year_revenue_inr: Optional[int] = Field(None, ge=0)
    previous_year_revenue_inr: Optional[int] = Field(None, ge=0)
    two_years_ago_revenue_inr: Optional[int] = Field(None, ge=0)
    profitability_status: Optional[str] = Field(None, max_length=64)
    profitability_amount_inr: Optional[int] = None
    funding_raised_summary: Optional[str] = Field(None, max_length=4000)
    valuation_inr: Optional[int] = Field(None, ge=0)
    market_cap_inr: Optional[int] = Field(None, ge=0)
    founder_name: Optional[str] = Field(None, max_length=255)
    team_size: Optional[int] = Field(None, ge=0)
    key_team_members: Optional[str] = Field(None, max_length=4000)
    team_members: Optional[List[TeamMemberRequest]] = None
    customer_count: Optional[int] = Field(None, ge=0)
    user_base: Optional[str] = Field(None, max_length=255)
    growth_metrics: Optional[str] = Field(None, max_length=4000)
    market_reach: Optional[str] = Field(None, max_length=4000)
    public_contact_person: Optional[str] = Field(None, max_length=255)
    public_email: Optional[str] = Field(None, max_length=320)
    public_phone_number: Optional[str] = Field(None, max_length=32)

    @field_validator("public_email")
    @classmethod
    def _public_email(cls, v: str | None) -> str | None:
        return normalize_optional_email(v)

    @field_validator("website")
    @classmethod
    def _website(cls, v: str | None) -> str | None:
        return normalize_http_url(blank_to_none(v))


class GstinVerifyRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    gstin: str = Field(..., min_length=15, max_length=15)

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v: str) -> str:
        return normalize_gstin(v)


class CoVentureApplyRequest(_BlankOptionalStringsMixin):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        populate_by_name=True,
    )

    full_name: str = Field(..., min_length=1, max_length=255, alias="fullName")
    phone: str = Field(..., min_length=1, max_length=20)
    location: Optional[str] = Field(None, max_length=255)
    description: str = Field(..., min_length=1, max_length=2000)
    gstin: Optional[str] = Field(None, min_length=15, max_length=15, alias="gstNo")
    # Partner profile (optional, partnership-centric application details)
    experience_summary: Optional[str] = Field(
        None, max_length=4000, alias="experienceSummary",
    )
    skills: Optional[str] = Field(None, max_length=2000)
    portfolio_url: Optional[str] = Field(None, max_length=512, alias="portfolioUrl")
    linkedin_url: Optional[str] = Field(None, max_length=512, alias="linkedinUrl")
    previous_ventures: Optional[str] = Field(
        None, max_length=4000, alias="previousVentures",
    )
    relevant_experience: Optional[str] = Field(
        None, max_length=4000, alias="relevantExperience",
    )
    motivation: Optional[str] = Field(None, max_length=4000)
    contribution_plan: Optional[str] = Field(
        None, max_length=4000, alias="contributionPlan",
    )
    video_introduction_url: Optional[str] = Field(
        None, max_length=512, alias="videoIntroductionUrl",
    )

    @field_validator("portfolio_url", "linkedin_url", "video_introduction_url")
    @classmethod
    def _urls(cls, v: str | None) -> str | None:
        return normalize_http_url(blank_to_none(v))

    @field_validator("phone", mode="before")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        normalized = normalize_profile_phone(v)
        if normalized is None:
            raise ValueError("Phone number is required.")
        return normalized

    @field_validator("full_name")
    @classmethod
    def _full_name(cls, v: str | None) -> str | None:
        return normalize_optional_non_whitespace(v, field="full_name")

    @field_validator("description")
    @classmethod
    def _description(cls, v: str | None) -> str | None:
        return normalize_optional_non_whitespace(v, field="description")

    @field_validator("gstin", mode="before")
    @classmethod
    def _gstin(cls, v: str | None) -> str | None:
        value = blank_to_none(v)
        if value is None:
            return None
        return normalize_gstin(value)


class CoVentureStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    status: str = Field(..., min_length=1, max_length=50)


# CompanyProfileRequest is referenced before its definition.
CreateVentureRequest.model_rebuild()
UpdateVentureRequest.model_rebuild()
