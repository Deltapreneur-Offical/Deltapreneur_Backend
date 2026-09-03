"""OpenProvider registry managed acquisition (> ₹5L payable) — not marketplace."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.entity.user.app_user import AppUser


class OpenProviderManagedAcquisition(
    UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base
):
    __tablename__ = "openprovider_managed_acquisitions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    domain_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tld: Mapped[str] = mapped_column(String(64), nullable=False)
    period_years: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Snapshot at submit — never re-quote OpenProvider for display/audit.
    quoted_price_inr: Mapped[float] = mapped_column(Float, nullable=False)
    payable_inr: Mapped[float] = mapped_column(Float, nullable=False)
    gst_inr: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    gst_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_per_year_inr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    provider_unit_price_inr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    commission_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    registry_tier: Mapped[str] = mapped_column(String(16), nullable=False, default="standard")
    is_registry_premium: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pricing_snapshot_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False, index=True)
    admin_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    in_progress_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    declined_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["AppUser"] = relationship(
        "AppUser",
        foreign_keys=[user_id],
        lazy="joined",
    )
