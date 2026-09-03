"""Company profile attached to a venture / co-venture listing.

Field visibility tiers (enforced in serializers, never here):
- Public: company_name, industry, website, business_description, products_services,
  target_market, business_model, public_contact_person, public_email
- Optional Public: public_phone_number, founder_name, team_size, key_team_members,
  financial and traction fields, PUBLIC documents
- Private (owner): legal_entity_name, registration_number, incorporation_date,
  company_type, BUYER_GATED documents, completion metadata
- Admin-only: GST artifacts (on ventures), OWNER_ADMIN documents, moderation notes
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.entity.coventure.venture_entity import Venture


class VentureCompanyProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venture_company_profiles"

    venture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ventures.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Company details
    company_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    legal_entity_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    registration_number: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    incorporation_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    company_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Business details
    business_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    products_services: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_market: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    business_model: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Financial details (optional public)
    annual_revenue_inr: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    current_year_revenue_inr: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    previous_year_revenue_inr: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    two_years_ago_revenue_inr: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    profitability_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    profitability_amount_inr: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    funding_raised_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    valuation_inr: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    market_cap_inr: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Team details (optional public)
    founder_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    team_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    key_team_members: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    team_members: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    # Traction details (optional public)
    customer_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    user_base: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    growth_metrics: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    market_reach: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Public contact (replaces owner contact on public views)
    public_contact_person: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    public_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    public_phone_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # Completion gating
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    venture: Mapped["Venture"] = relationship(
        "Venture",
        back_populates="company_profile",
        foreign_keys=[venture_id],
    )
    documents: Mapped[List["VentureCompanyProfileDocument"]] = relationship(
        "VentureCompanyProfileDocument",
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="VentureCompanyProfileDocument.sort_order",
        lazy="selectin",
    )


class VentureCompanyProfileDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venture_company_profile_documents"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("venture_company_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # PUBLIC | BUYER_GATED | OWNER_ADMIN
    visibility: Mapped[str] = mapped_column(String(32), default="PUBLIC", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    profile: Mapped["VentureCompanyProfile"] = relationship(
        "VentureCompanyProfile",
        back_populates="documents",
        foreign_keys=[profile_id],
    )
