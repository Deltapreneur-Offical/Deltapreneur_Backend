from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.entity.community.community_industry import CommunityIndustry
from app.entity.community.community_role import CommunityRole
from app.utils.field_validators import blank_to_none, normalize_http_url


class CommunityUpdateRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
        extra="ignore",
    )

    role: Optional[CommunityRole] = None

    skills: Optional[str] = Field(default=None, max_length=1000)

    industry: Optional[CommunityIndustry] = None

    @field_validator("role", "industry", mode="before")
    @classmethod
    def _empty_enum_to_none(cls, v):
        if v is None or v == "":
            return None
        return v

    location: Optional[str] = Field(default=None, max_length=255)

    why_im_here: Optional[str] = Field(
        default=None,
        max_length=2000,
        alias="whyImHere",
    )

    about: Optional[str] = Field(
        default=None,
        max_length=2000,
    )

    linked_in_profile_url: Optional[str] = Field(
        default=None,
        max_length=1000,
        alias="linkedInProfileUrl",
    )

    expected_rate: Optional[str] = Field(
        default=None,
        max_length=100,
        alias="expectedRate",
    )
    introduction_video_link: Optional[str] = Field(
        default=None,
        max_length=1000,
        alias="introductionVideoLink",
    )
    resume_drive_link: Optional[str] = Field(
        default=None,
        max_length=1000,
        alias="resumeDriveLink",
    )
    portfolio_website_link: Optional[str] = Field(
        default=None,
        max_length=1000,
        alias="portfolioWebsiteLink",
    )
    preferred_work_type: Optional[str] = Field(
        default=None,
        max_length=100,
        alias="preferredWorkType",
    )
    industry_expertise: Optional[str] = Field(
        default=None,
        max_length=500,
        alias="industryExpertise",
    )
    languages_known: Optional[str] = Field(
        default=None,
        max_length=500,
        alias="languagesKnown",
    )
    pitch_deck_link: Optional[str] = Field(
        default=None,
        max_length=1000,
        alias="pitchDeckLink",
    )
    youtube_video_link: Optional[str] = Field(
        default=None,
        max_length=1000,
        alias="youtubeVideoLink",
    )

    headline: Optional[str] = Field(
        default=None,
        max_length=255,
        alias="headline",
    )

    education: Optional[str] = Field(
        default=None,
        max_length=500,
        alias="education",
    )

    graduation_year: Optional[str] = Field(
        default=None,
        max_length=10,
        alias="graduationYear",
    )

    experience: Optional[str] = Field(
        default=None,
        max_length=100,
        alias="experience",
    )

    github_profile: Optional[str] = Field(
        default=None,
        max_length=1000,
        alias="githubProfile",
    )

    social_media_profile: Optional[str] = Field(
        default=None,
        max_length=1000,
        alias="socialMediaProfile",
    )

    current_company: Optional[str] = Field(
        default=None,
        max_length=255,
        alias="currentCompany",
    )

    designation: Optional[str] = Field(
        default=None,
        max_length=255,
        alias="designation",
    )

    role_description: Optional[str] = Field(
        default=None,
        max_length=2000,
        alias="roleDescription",
    )

    company_name: Optional[str] = Field(
        default=None,
        max_length=255,
        alias="companyName",
    )

    company_website: Optional[str] = Field(
        default=None,
        max_length=1000,
        alias="companyWebsite",
    )

    availability: Optional[str] = Field(
        default=None,
        max_length=255,
        alias="availability",
    )

    hiring_for: Optional[str] = Field(
        default=None,
        max_length=2000,
        alias="hiringFor",
    )

    mentorship_topics: Optional[str] = Field(
        default=None,
        max_length=2000,
        alias="mentorshipTopics",
    )

    investment_focus: Optional[str] = Field(
        default=None,
        max_length=2000,
        alias="investmentFocus",
    )

    investment_stage: Optional[str] = Field(
        default=None,
        max_length=255,
        alias="investmentStage",
    )

    ticket_size: Optional[str] = Field(
        default=None,
        max_length=255,
        alias="ticketSize",
    )

    startup_stage: Optional[str] = Field(
        default=None,
        max_length=255,
        alias="startupStage",
    )

    co_founder_needs: Optional[str] = Field(
        default=None,
        max_length=2000,
        alias="coFounderNeeds",
    )

    incubation_programs: Optional[str] = Field(
        default=None,
        max_length=2000,
        alias="incubationPrograms",
    )

    support_offered: Optional[str] = Field(
        default=None,
        max_length=2000,
        alias="supportOffered",
    )

    @field_validator("expected_rate", mode="before")
    @classmethod
    def _normalize_expected_rate(cls, v: str | None) -> str | None:
        return blank_to_none(v)

    @field_validator(
        "preferred_work_type",
        "industry_expertise",
        "languages_known",
        "about",
        mode="before",
    )
    @classmethod
    def _normalize_optional_text(cls, v: str | None) -> str | None:
        return blank_to_none(v)

    @field_validator("linked_in_profile_url", mode="before")
    @classmethod
    def _linkedin_url(cls, v: str | None) -> str | None:
        raw = blank_to_none(v)
        if raw is None:
            return None
        return normalize_http_url(raw)

    @field_validator(
        "introduction_video_link",
        "resume_drive_link",
        "portfolio_website_link",
        "pitch_deck_link",
        "youtube_video_link",
        mode="before",
    )
    @classmethod
    def _optional_http_urls(cls, v: str | None) -> str | None:
        raw = blank_to_none(v)
        if raw is None:
            return None
        return normalize_http_url(raw)

    @field_validator(
        "headline",
        "education",
        "graduation_year",
        "experience",
        "current_company",
        "designation",
        "role_description",
        "company_name",
        "availability",
        "hiring_for",
        "mentorship_topics",
        "investment_focus",
        "investment_stage",
        "ticket_size",
        "startup_stage",
        "co_founder_needs",
        "incubation_programs",
        "support_offered",
        mode="before",
    )
    @classmethod
    def _normalize_extra_text(cls, v: str | None) -> str | None:
        return blank_to_none(v)

    @field_validator(
        "github_profile",
        "social_media_profile",
        "company_website",
        mode="before",
    )
    @classmethod
    def _optional_extra_http_urls(cls, v: str | None) -> str | None:
        raw = blank_to_none(v)
        if raw is None:
            return None
        return normalize_http_url(raw)
