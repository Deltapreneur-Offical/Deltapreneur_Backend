"""Domain marketplace listing (resale), distinct from auction `domains` table."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.marketplace_enums import (
    DomainCategory,
    DomainListingStatus,
    DomainListingVerificationStatus,
    MarketplacePaymentStatus,
    PricingDemand,
    SaleType,
    VerificationMethod,
)

if TYPE_CHECKING:
    from app.entity.coventure.agreement_entity import Agreement
    from app.entity.coventure.contact_info_entity import ContactInfo
    from app.entity.user.app_user import AppUser


class DomainListing(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "domain_listings"
    __table_args__ = (
        Index("idx_domain_listings_listed_by", "listed_by_user_id"),
        Index("idx_domain_listings_name", "domain_name"),
        Index(
            "idx_domain_listings_public_browse",
            "is_deleted",
            "taken_down",
            "status",
            "domain_status",
            "created_at",
        ),
    )

    domain_name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain_extension: Mapped[str] = mapped_column(String(32), nullable=False, default=".com")
    domain_category: Mapped[Optional[DomainCategory]] = mapped_column(
        SAEnum(DomainCategory, name="domain_category_enum", create_constraint=False),
        nullable=True,
    )
    asking_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    seller_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    listing_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    commission_percentage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    commission_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    seller_payout_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pricing_demand: Mapped[Optional[PricingDemand]] = mapped_column(
        SAEnum(PricingDemand, name="pricing_demand_enum", create_constraint=False),
        nullable=True,
    )
    domain_status: Mapped[DomainListingStatus] = mapped_column(
        SAEnum(DomainListingStatus, name="domain_listing_status_enum", create_constraint=False),
        default=DomainListingStatus.AVAILABLE,
        nullable=False,
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

    logo: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    logo_text: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Text content for logo generation
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    views: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    razorpay_order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    payment_status: Mapped[Optional[MarketplacePaymentStatus]] = mapped_column(
        SAEnum(MarketplacePaymentStatus, name="marketplace_payment_status_enum", create_constraint=False),
        nullable=True,
    )

    listed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    purchased_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    sold_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_token: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    verification_method: Mapped[Optional[VerificationMethod]] = mapped_column(
        SAEnum(VerificationMethod, name="verification_method_enum", create_constraint=False),
        nullable=True,
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    whois_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    verification_status: Mapped[DomainListingVerificationStatus] = mapped_column(
        SAEnum(
            DomainListingVerificationStatus,
            name="domain_listing_verification_status_enum",
            create_constraint=False,
        ),
        default=DomainListingVerificationStatus.PENDING,
        nullable=False,
    )
    verified_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    verification_rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verification_admin_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    taken_down: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    take_down_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sale_type: Mapped[SaleType] = mapped_column(
        SAEnum(SaleType, name="sale_type_enum", create_constraint=False),
        default=SaleType.ONE_TIME,
        nullable=False,
    )
    featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    purchase_addon_services: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    purchase_buyer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    purchase_buyer_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    purchase_buyer_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    active_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("domain_marketplace_transactions.id", ondelete="SET NULL"),
        nullable=True,
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
    purchased_by: Mapped[Optional["AppUser"]] = relationship(
        "AppUser",
        foreign_keys=[purchased_by_user_id],
        lazy="selectin",
    )
    verified_by: Mapped[Optional["AppUser"]] = relationship(
        "AppUser",
        foreign_keys=[verified_by_user_id],
        lazy="selectin",
    )
