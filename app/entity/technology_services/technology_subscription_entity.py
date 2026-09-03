"""Technology user subscription model."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class TechnologySubscriptionEntity(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "technology_subscriptions"
    __table_args__ = (
        Index("idx_tech_subs_user", "user_id"),
        Index("idx_tech_subs_service", "service_slug"),
        Index("idx_tech_subs_status", "status"),
        Index("idx_tech_subs_retry", "status", "payment_status", "next_retry_at"),
    )

    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    service_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    service_name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_code: Mapped[str] = mapped_column(String(64), nullable=False)
    billing_cycle: Mapped[str] = mapped_column(String(32), default="monthly", nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    # PAYMENT_CAPTURED, PROVISIONING, ACTIVE, PENDING, PROVISIONING_FAILED, CANCELLED, SUSPENDED
    payment_status: Mapped[str] = mapped_column(String(32), default="CAPTURED", nullable=False)
    provider_subscription_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    provider_order_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    credentials_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirmation_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    provision_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_provision_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_provider_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_provider_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    razorpay_order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provision_input: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: customer-provided areaCode / primaryDomain etc.
