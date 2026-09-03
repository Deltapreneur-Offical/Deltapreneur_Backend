"""Technology pricing plan (CoCreation marketplace)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Float, ForeignKey, Index
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.cocreation_enums import TechnologyPricingPlanDuration

if TYPE_CHECKING:
    from app.entity.cocreation.software_entity import Software


class TechnologyPricingPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "software_pricing_plans"
    __table_args__ = (
        Index("idx_software_pricing_plans_listing_id", "listing_id"),
    )

    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("software_listings.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_duration: Mapped[TechnologyPricingPlanDuration] = mapped_column(
        SAEnum(TechnologyPricingPlanDuration, name="technology_pricing_plan_duration_enum", create_constraint=False),
        nullable=False,
    )
    price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    listing: Mapped["Software"] = relationship("Software", back_populates="pricing_plans")
