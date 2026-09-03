"""Technology subscription invoice model."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TechnologySubscriptionInvoiceEntity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "technology_subscription_invoices"
    __table_args__ = (
        Index("idx_tech_inv_sub", "subscription_id"),
        Index("idx_tech_inv_user", "user_id"),
        Index("idx_tech_inv_number", "invoice_number", unique=True),
    )

    subscription_id: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PAID", nullable=False)  # PAID, PENDING, REFUNDED
    billing_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    billing_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String(64), default="HubRegistrar Pay", nullable=True)
