"""Software purchase record (Razorpay)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String
import sqlalchemy
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.cocreation_enums import (
    SoftwarePaymentStatus,
    SoftwarePurchaseCompletionStatus,
    TechnologyPricingPlanDuration,
)

if TYPE_CHECKING:
    from app.entity.cocreation.software_entity import Software
    from app.entity.user.app_user import AppUser


class SoftwarePurchase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "software_purchases"
    __table_args__ = (
        Index("idx_software_purchases_buyer", "buyer_id"),
        Index("idx_software_purchases_rzp_order", "razorpay_order_id"),
    )

    software_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("software_listings.id", ondelete="CASCADE"),
        nullable=False,
    )
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    buyer_full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    buyer_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    buyer_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    purchase_addon_services: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    razorpay_order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    cobrother_help_razorpay_order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    payment_status: Mapped[SoftwarePaymentStatus] = mapped_column(
        SAEnum(SoftwarePaymentStatus, name="software_payment_status_enum", create_constraint=False),
        default=SoftwarePaymentStatus.CREATED,
        nullable=False,
    )
    completion_status: Mapped[SoftwarePurchaseCompletionStatus] = mapped_column(
        SAEnum(
            SoftwarePurchaseCompletionStatus,
            name="software_purchase_completion_status_enum",
            create_constraint=False,
        ),
        default=SoftwarePurchaseCompletionStatus.PENDING,
        nullable=False,
    )
    co_brother_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    co_brother_help_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sold_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Payout Tracking
    gross_amount_inr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    platform_fee_inr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    seller_payout_inr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    payout_approved_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    payout_approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    seller_paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    payout_reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    payout_reminder_count: Mapped[int] = mapped_column(
        sqlalchemy.SmallInteger, default=0, nullable=False
    )

    selected_plan: Mapped[Optional[TechnologyPricingPlanDuration]] = mapped_column(
        SAEnum(TechnologyPricingPlanDuration, name="technology_pricing_plan_duration_enum", create_constraint=False),
        nullable=True,
    )
    expiry_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry_reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    software: Mapped["Software"] = relationship("Software", foreign_keys=[software_id])
    buyer: Mapped["AppUser"] = relationship("AppUser", foreign_keys=[buyer_id], lazy="selectin")
