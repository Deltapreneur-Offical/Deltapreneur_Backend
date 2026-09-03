"""Venture pitch (buyer offer on a venture sale listing)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.venture_enums import (
    VentureAcquisitionApplicationSource,
    VentureAcquisitionApplicationStatus,
)

if TYPE_CHECKING:
    from app.entity.coventure.venture_entity import Venture
    from app.entity.user.app_user import AppUser


class VenturePitch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venture_pitches"
    __table_args__ = (
        Index("idx_venture_pitches_venture_id", "venture_id"),
        Index("idx_venture_pitches_buyer_user_id", "buyer_user_id"),
        Index("idx_venture_pitches_status", "status"),
        UniqueConstraint(
            "venture_id",
            "buyer_user_id",
            name="uq_venture_pitches_venture_buyer",
        ),
    )

    venture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ventures.id", ondelete="CASCADE"),
        nullable=False,
    )
    buyer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[VentureAcquisitionApplicationStatus] = mapped_column(
        SAEnum(
            VentureAcquisitionApplicationStatus,
            name="venture_acquisition_application_status_enum",
            create_constraint=False,
        ),
        default=VentureAcquisitionApplicationStatus.PENDING,
        nullable=False,
    )
    source: Mapped[VentureAcquisitionApplicationSource] = mapped_column(
        SAEnum(
            VentureAcquisitionApplicationSource,
            name="venture_acquisition_application_source_enum",
            create_constraint=False,
        ),
        default=VentureAcquisitionApplicationSource.REGULAR_APPLY,
        nullable=False,
    )
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    investment_proposal: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    additional_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    offer_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    equity_percent_sought: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    seller_accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    admin_completed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    venture: Mapped["Venture"] = relationship(
        "Venture",
        back_populates="pitches",
        foreign_keys=[venture_id],
        lazy="selectin",
    )
    buyer: Mapped["AppUser"] = relationship(
        "AppUser",
        foreign_keys=[buyer_user_id],
        lazy="selectin",
    )


VentureAcquisitionApplication = VenturePitch
