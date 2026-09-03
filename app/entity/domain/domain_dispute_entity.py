"""Disputes for domain marketplace transfers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.transfer_enums import DisputeReason


class DomainDispute(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "domain_disputes"
    __table_args__ = (
        Index("idx_domain_disputes_tx", "transaction_id"),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("domain_marketplace_transactions.id", ondelete="CASCADE"),
        nullable=False,
    )
    opened_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    reason: Mapped[DisputeReason] = mapped_column(
        SAEnum(DisputeReason, name="dispute_reason_enum", create_constraint=False),
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", nullable=False)
    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    evidence: Mapped[list["DomainDisputeEvidence"]] = relationship(
        "DomainDisputeEvidence",
        back_populates="dispute",
        lazy="selectin",
    )


class DomainDisputeEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "domain_dispute_evidence"

    dispute_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("domain_disputes.id", ondelete="CASCADE"),
        nullable=False,
    )
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    dispute: Mapped["DomainDispute"] = relationship(
        "DomainDispute",
        back_populates="evidence",
    )
