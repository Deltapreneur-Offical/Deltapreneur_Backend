"""Software listing (CoCreation marketplace)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String, Text, Float, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.cocreation_enums import (
    SoftwareCategory,
    SoftwarePricingDemand,
    SoftwarePurchaseType,
    SoftwareStatus,
    TechnologyType,
)

if TYPE_CHECKING:
    from app.entity.cocreation.software_auction import SoftwareAuction
    from app.entity.coventure.agreement_entity import Agreement
    from app.entity.user.app_user import AppUser
    from app.entity.cocreation.technology_pricing_plan_entity import TechnologyPricingPlan


class Software(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "software_listings"
    __table_args__ = (
        Index("idx_software_listings_listed_by", "listed_by_user_id"),
        Index("idx_software_listings_name", "name"),
        Index(
            "idx_software_listings_public_browse",
            "is_deleted",
            "taken_down",
            "status",
            "created_at",
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    video_link: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    what_it_does: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    how_it_helps: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    github_link: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    documentation_urls: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    download_urls: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    live_demo_link: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    tech_stack: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    technology_type: Mapped[TechnologyType] = mapped_column(
        SAEnum(TechnologyType, name="technology_type_enum", create_constraint=False),
        default=TechnologyType.SOFTWARE,
        nullable=False,
    )

    category: Mapped[Optional[SoftwareCategory]] = mapped_column(
        SAEnum(SoftwareCategory, name="software_category_enum", create_constraint=False),
        nullable=True,
    )
    pricing_demand: Mapped[Optional[SoftwarePricingDemand]] = mapped_column(
        SAEnum(SoftwarePricingDemand, name="software_pricing_demand_enum", create_constraint=False),
        nullable=True,
    )
    price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    seller_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Listing display/preference currency; monetary amounts are always stored in INR.
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    software_status: Mapped[SoftwareStatus] = mapped_column(
        SAEnum(SoftwareStatus, name="software_status_enum", create_constraint=False),
        default=SoftwareStatus.AVAILABLE,
        nullable=False,
    )
    purchase_type: Mapped[SoftwarePurchaseType] = mapped_column(
        SAEnum(SoftwarePurchaseType, name="software_purchase_type_enum", create_constraint=False),
        default=SoftwarePurchaseType.ONE_TIME,
        nullable=False,
    )

    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    views: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    taken_down: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    take_down_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    official: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    agreement_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agreement.id", ondelete="SET NULL"),
        nullable=True,
    )
    listed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
    auction: Mapped[Optional["SoftwareAuction"]] = relationship(
        "SoftwareAuction",
        back_populates="software",
        uselist=False,
        lazy="selectin",
    )
    pricing_plans: Mapped[list["TechnologyPricingPlan"]] = relationship(
        "TechnologyPricingPlan",
        back_populates="listing",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
