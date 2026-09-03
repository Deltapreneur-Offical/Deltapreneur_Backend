"""CoBrother assigned request workflow."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.marketplace_enums import CoBrotherRequestStatus, CoBrotherRequestType

if TYPE_CHECKING:
    from app.entity.user.app_user import AppUser


class CoBrotherRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cobrother_requests"
    __table_args__ = (
        Index("idx_cobrother_requests_assignee", "assigned_cobrother_id"),
        Index("idx_cobrother_requests_entity", "request_type", "entity_id"),
    )

    request_type: Mapped[CoBrotherRequestType] = mapped_column(
        SAEnum(CoBrotherRequestType, name="cobrother_request_type_enum", create_constraint=False),
        nullable=False,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entity_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    assigned_cobrother_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    admin_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[CoBrotherRequestStatus] = mapped_column(
        SAEnum(CoBrotherRequestStatus, name="cobrother_request_status_enum", create_constraint=False),
        default=CoBrotherRequestStatus.PENDING,
        nullable=False,
    )
    response_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    lister_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    razorpay_order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    lister: Mapped[Optional["AppUser"]] = relationship(
        "AppUser",
        foreign_keys=[lister_id],
        lazy="selectin",
    )

    assigned_cobrother: Mapped[Optional["AppUser"]] = relationship(
        "AppUser",
        foreign_keys=[assigned_cobrother_id],
        lazy="selectin",
    )
