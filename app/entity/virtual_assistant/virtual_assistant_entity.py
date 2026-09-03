"""Virtual Assistant public application entity."""

from __future__ import annotations

from sqlalchemy import Boolean, DateTime, Integer, String, Enum, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from .application_role_entity import ApplicationRole


class VirtualAssistantApplication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "virtual_assistant_applications"

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone_number: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    profile_photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    profile_photo_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    profile_photo_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profile_photo_mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    profile_photo_size: Mapped[int | None] = mapped_column(nullable=True)
    short_bio: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    roles: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    skills: Mapped[str | None] = mapped_column(String(500), nullable=True)
    years_experience: Mapped[str | None] = mapped_column(String(50), nullable=True)
    languages_known: Mapped[str | None] = mapped_column(String(300), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    portfolio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resume_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resume_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resume_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resume_mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resume_size: Mapped[int | None] = mapped_column(nullable=True)
    availability: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hours_per_week: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expected_compensation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    consent_accurate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consent_terms: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consent_adult: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    application_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    reference_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    overall_status: Mapped[str] = mapped_column(
        Enum("pending", "partially_approved", "approved", "rejected", name="overall_status_enum"),
        default="pending",
        nullable=False,
    )
    workspace_locked: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_client_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    public_monthly_price_inr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pricing_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    pricing_updated_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pricing_updated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    publish_status: Mapped[str] = mapped_column(
        Enum("draft", "published", "unpublished", name="va_publish_status_enum"),
        default="draft",
        nullable=False,
    )
    published_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    published_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    application_roles: Mapped[list[ApplicationRole]] = relationship(
        "ApplicationRole",
        back_populates="application",
        cascade="all, delete-orphan",
    )
    assignments: Mapped[list["VAAssignment"]] = relationship(
        "VAAssignment",
        back_populates="application",
        cascade="all, delete-orphan",
    )
    clients: Mapped[list["VAClient"]] = relationship(
        "VAClient",
        back_populates="application",
        cascade="all, delete-orphan",
    )
