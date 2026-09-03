"""Franchise Application entity."""

from __future__ import annotations

from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class FranchiseApplication(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "franchise_applications"
    __table_args__ = (
        Index("idx_franchise_app_status", "status"),
        Index("idx_franchise_app_blacklisted", "is_blacklisted"),
        Index("idx_franchise_app_email", "email"),
        Index("idx_franchise_app_mobile", "mobile_number"),
    )

    # Applicant info
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mobile_number: Mapped[str] = mapped_column(String(20), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    full_address: Mapped[str] = mapped_column(Text, nullable=False)

    # Business info
    existing_business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    preferred_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    existing_office_availability: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Open-ended fields
    relevant_experience: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_for_applying: Mapped[str | None] = mapped_column(Text, nullable=True)
    additional_information: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Location
    map_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Status management
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    blacklist_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
