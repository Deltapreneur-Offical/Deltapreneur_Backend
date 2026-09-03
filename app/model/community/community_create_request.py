from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.entity.community.community_industry import CommunityIndustry
from app.entity.community.community_role import CommunityRole
from app.utils.field_validators import blank_to_none, normalize_http_url


class CommunityCreateRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
        extra="ignore",
    )
    linked_in_id: Optional[str] = Field(
        default=None,
        max_length=255,
    )

    name: Optional[str] = Field(
        default=None,
        max_length=255,
    )

    image_url: Optional[str] = Field(
        default=None,
        max_length=1000,
    )

    linked_in_profile_url: Optional[str] = Field(
        default=None,
        max_length=1000,
        alias="linkedInProfileUrl",
    )

    role: Optional[CommunityRole] = None

    skills: Optional[str] = Field(
        default=None,
        max_length=1000,
    )

    industry: Optional[CommunityIndustry] = None

    location: Optional[str] = Field(
        default=None,
        max_length=255,
    )

    why_im_here: Optional[str] = Field(
        default=None,
        max_length=2000,
        alias="whyImHere",
    )

    about: Optional[str] = Field(
        default=None,
        max_length=2000,
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
