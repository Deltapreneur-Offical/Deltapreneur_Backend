"""Timeline events for venture deal transactions."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.venture_enums import VentureDealEventType

if TYPE_CHECKING:
    from app.entity.coventure.venture_deal_transaction_entity import VentureDealTransaction
    from app.entity.user.app_user import AppUser


class VentureDealEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venture_deal_events"
    __table_args__ = (
        Index("idx_vde_transaction", "transaction_id"),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("venture_deal_transactions.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[VentureDealEventType] = mapped_column(
        SAEnum(VentureDealEventType, name="venture_deal_event_type_enum", create_constraint=False),
        nullable=False,
    )
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[str]] = mapped_column(String(4096), nullable=True)

    transaction: Mapped["VentureDealTransaction"] = relationship(
        "VentureDealTransaction",
        back_populates="events",
        foreign_keys=[transaction_id],
    )
