"""Ledger row for seller payout release."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.transfer_enums import SellerPayoutStatus


class SellerPayout(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "seller_payouts"

    transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("domain_marketplace_transactions.id", ondelete="CASCADE"),
        nullable=True,
    )
    software_purchase_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("software_purchases.id", ondelete="CASCADE"),
        nullable=True,
    )
    payout_profile_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("seller_payout_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    seller_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    amount_inr: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[SellerPayoutStatus] = mapped_column(
        SAEnum(SellerPayoutStatus, name="seller_payout_status_enum", create_constraint=False),
        default=SellerPayoutStatus.PENDING,
        nullable=False,
    )
    razorpay_payout_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    method_used: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    reference_number: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    released_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
