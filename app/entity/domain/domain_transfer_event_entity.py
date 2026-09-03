"""Audit timeline for domain marketplace transfers."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.transfer_enums import TransferEventType


class DomainTransferEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "domain_transfer_events"
    __table_args__ = (
        Index("idx_dte_transaction", "transaction_id", "created_at"),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("domain_marketplace_transactions.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[TransferEventType] = mapped_column(
        SAEnum(TransferEventType, name="transfer_event_type_enum", create_constraint=False),
        nullable=False,
    )
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    actor_role: Mapped[str] = mapped_column(String(16), nullable=False)
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
