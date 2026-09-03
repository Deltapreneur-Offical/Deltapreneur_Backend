from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, backref, mapped_column, relationship

from app.entity.base import (
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    SoftDeleteMixin,
)


class Community(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    SoftDeleteMixin,
    Base,
):
    __tablename__ = "community"

    linked_in_id: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
    )

    name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    image_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    cover_image_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    linked_in_profile_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    role: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    views: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    skills: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    industry: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    location: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    why_im_here: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    about: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    expected_rate: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    introduction_video_link: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    resume_drive_link: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    portfolio_website_link: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    preferred_work_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    industry_expertise: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    languages_known: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    pitch_deck_link: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    youtube_video_link: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    headline: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    education: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    graduation_year: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
    )

    experience: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    github_profile: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    social_media_profile: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    current_company: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    designation: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    role_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    company_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    company_website: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    availability: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    hiring_for: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    mentorship_topics: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    investment_focus: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    investment_stage: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    ticket_size: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    startup_stage: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    co_founder_needs: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    incubation_programs: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    support_offered: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )


    is_approved: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    featured: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    app_user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        unique=True,
        nullable=False,
    )

    app_user = relationship(
        "AppUser",
        lazy="selectin",
        backref=backref("community_profile", lazy="selectin"),
    )
