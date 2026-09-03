"""Venture listing entity."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.entity.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.venture_enums import (
    VentureAcquisitionFlow,
    VentureDealType,
    VentureListingApprovalStatus,
    VentureListingMode,
    VentureListingStatus,
    VentureSaleType,
    VentureStage,
    VentureVerificationStatus,
)

if TYPE_CHECKING:
    from app.entity.coventure.agreement_entity import Agreement
    from app.entity.coventure.brand_details_entity import BrandDetails
    from app.entity.coventure.contact_info_entity import ContactInfo
    from app.entity.coventure.partner_entity import CoVenture
    from app.entity.coventure.venture_pitch_entity import VenturePitch
    from app.entity.coventure.venture_company_profile_entity import VentureCompanyProfile
    from app.entity.coventure.venture_document_entity import VentureDocument
    from app.entity.coventure.venture_financial_profile_entity import VentureFinancialProfile
    from app.entity.coventure.venture_role_entity import VentureRole
    from app.entity.coventure.venture_verification_document_entity import VentureVerificationDocument
    from app.entity.user.app_user import AppUser


class Venture(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "ventures"
    __table_args__ = (
        Index("idx_ventures_listed_by_user_id", "listed_by_user_id"),
        Index("idx_ventures_stage", "stage"),
        Index("idx_ventures_sale_type", "sale_type"),
        Index(
            "idx_ventures_public_browse",
            "is_deleted",
            "taken_down",
            "created_at",
        ),
    )

    brand_details_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("brand_details.id", ondelete="SET NULL"),
        nullable=True,
    )
    contact_info_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contact_info.id", ondelete="SET NULL"),
        nullable=True,
    )
    agreement_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agreement.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    views: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    co_venture_application_count: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False,
    )

    listed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    purchased_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    stage: Mapped[Optional[VentureStage]] = mapped_column(
        SAEnum(VentureStage, name="venture_stage_enum", create_constraint=False),
        nullable=True,
    )
    current_problem: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    looking_for: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    taken_down: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    take_down_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    sale_type: Mapped[VentureSaleType] = mapped_column(
        SAEnum(VentureSaleType, name="venture_sale_type_enum", create_constraint=False),
        default=VentureSaleType.REGULAR,
        nullable=False,
    )
    listing_mode: Mapped[VentureListingMode] = mapped_column(
        SAEnum(VentureListingMode, name="venture_listing_mode_enum", create_constraint=False),
        default=VentureListingMode.VENTURE,
        nullable=False,
    )
    venture_listing_status: Mapped[VentureListingStatus] = mapped_column(
        SAEnum(VentureListingStatus, name="venture_listing_status_enum", create_constraint=False),
        default=VentureListingStatus.ACTIVE,
        nullable=False,
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    selected_pitch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("venture_pitches.id", ondelete="SET NULL"),
        nullable=True,
    )
    selected_coventure_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("co_ventures.id", ondelete="SET NULL"),
        nullable=True,
    )
    deal_type: Mapped[Optional[VentureDealType]] = mapped_column(
        SAEnum(VentureDealType, name="venture_deal_type_enum", create_constraint=False),
        nullable=True,
    )
    acquisition_flow: Mapped[Optional[VentureAcquisitionFlow]] = mapped_column(
        SAEnum(
            VentureAcquisitionFlow,
            name="venture_acquisition_flow_enum",
            create_constraint=False,
        ),
        nullable=True,
    )
    equity_percent_offered: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    valuation_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    commission_percent_applied: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    gstin: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    gstin_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    gstin_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    gstin_legal_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    verification_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_video_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    verification_status: Mapped[VentureVerificationStatus] = mapped_column(
        SAEnum(
            VentureVerificationStatus,
            name="venture_verification_status_enum",
            create_constraint=False,
            native_enum=False,
        ),
        default=VentureVerificationStatus.NONE,
        nullable=False,
    )
    verification_rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verification_reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    verification_reviewed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    listing_approval_status: Mapped[VentureListingApprovalStatus] = mapped_column(
        SAEnum(
            VentureListingApprovalStatus,
            name="venture_listing_approval_status_enum",
            create_constraint=False,
        ),
        default=VentureListingApprovalStatus.PENDING_APPROVAL,
        nullable=False,
    )
    listing_rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    listing_approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    listing_approved_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    brand_details: Mapped[Optional["BrandDetails"]] = relationship(
        "BrandDetails",
        foreign_keys=[brand_details_id],
        lazy="selectin",
    )
    contact_info: Mapped[Optional["ContactInfo"]] = relationship(
        "ContactInfo",
        foreign_keys=[contact_info_id],
        lazy="selectin",
    )
    agreement: Mapped[Optional["Agreement"]] = relationship(
        "Agreement",
        foreign_keys=[agreement_id],
        lazy="selectin",
    )
    listed_by: Mapped[Optional["AppUser"]] = relationship(
        "AppUser",
        foreign_keys=[listed_by_user_id],
        lazy="selectin",
    )
    roles: Mapped[List["VentureRole"]] = relationship(
        "VentureRole",
        back_populates="venture",
        cascade="all, delete-orphan",
        order_by="VentureRole.sort_order",
        lazy="selectin",
    )
    co_venture_applications: Mapped[List["CoVenture"]] = relationship(
        "CoVenture",
        back_populates="venture",
        cascade="all, delete-orphan",
        foreign_keys="CoVenture.venture_id",
        lazy="selectin",
    )
    pitches: Mapped[List["VenturePitch"]] = relationship(
        "VenturePitch",
        back_populates="venture",
        cascade="all, delete-orphan",
        foreign_keys="VenturePitch.venture_id",
        lazy="selectin",
    )
    acquisition_applications = synonym("pitches")
    financial_profile: Mapped[Optional["VentureFinancialProfile"]] = relationship(
        "VentureFinancialProfile",
        back_populates="venture",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    documents: Mapped[List["VentureDocument"]] = relationship(
        "VentureDocument",
        back_populates="venture",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    company_profile: Mapped[Optional["VentureCompanyProfile"]] = relationship(
        "VentureCompanyProfile",
        back_populates="venture",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    verification_documents: Mapped[List["VentureVerificationDocument"]] = relationship(
        "VentureVerificationDocument",
        back_populates="venture",
        cascade="all, delete-orphan",
        order_by="VentureVerificationDocument.created_at",
        lazy="selectin",
    )


# Register related mappers for SQLAlchemy relationship resolution.
from app.entity.coventure.venture_document_entity import VentureDocument  # noqa: E402, F401
from app.entity.coventure.venture_financial_profile_entity import VentureFinancialProfile  # noqa: E402, F401
from app.entity.coventure.venture_company_profile_entity import VentureCompanyProfile  # noqa: E402, F401
from app.entity.coventure.venture_verification_document_entity import VentureVerificationDocument  # noqa: E402, F401


from app.entity.coventure.venture_pitch_entity import VenturePitch as _VenturePitch  # noqa: F401
