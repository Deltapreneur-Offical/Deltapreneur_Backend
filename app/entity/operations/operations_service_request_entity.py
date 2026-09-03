"""User hire/booking requests against operations catalog services."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.entity.operations.operations_service_entity import OperationsService
    from app.entity.user.app_user import AppUser


class OperationsServiceRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "operations_service_requests"
    __table_args__ = (
        Index(
            "idx_ops_service_requests_user_service",
            "user_id",
            "operations_service_id",
        ),
        Index(
            "idx_ops_service_requests_status_created",
            "status",
            "created_at",
        ),
    )

    operations_service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operations_services.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request_type: Mapped[str] = mapped_column(String(32), nullable=False)
    service_type: Mapped[str] = mapped_column(String(32), nullable=False)
    billing_period: Mapped[str] = mapped_column(String(32), nullable=False)
    service_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quoted_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(64), nullable=False)
    company_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    city_state: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preferred_timeline: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    # ── Razorpay payment fields ──
    razorpay_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    razorpay_signature: Mapped[str | None] = mapped_column(String(512), nullable=True)
    payment_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    payment_amount_inr: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    # ── Contact tracking (separate from payment status) ──
    contact_status: Mapped[str] = mapped_column(String(32), default="CONTACT_PENDING", nullable=False)
    contacted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    operations_service: Mapped["OperationsService"] = relationship(
        "OperationsService",
        foreign_keys=[operations_service_id],
        lazy="joined",
    )
    user: Mapped["AppUser"] = relationship(
        "AppUser",
        foreign_keys=[user_id],
        lazy="joined",
    )
