"""Post-deal escrow transaction for venture sale or co-venture placement."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.transfer_enums import MarketplaceEscrowStatus
from app.utils.venture_enums import VentureDealKind, VentureDealStatus

if TYPE_CHECKING:
    from app.entity.coventure.partner_entity import CoVenture
    from app.entity.coventure.venture_pitch_entity import VenturePitch
    from app.entity.coventure.venture_entity import Venture
    from app.entity.user.app_user import AppUser


class VentureDealTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venture_deal_transactions"
    __table_args__ = (
        Index("idx_vdt_seller_status", "seller_id", "deal_status"),
        Index("idx_vdt_buyer_status", "buyer_id", "deal_status"),
        Index("idx_vdt_venture", "venture_id"),
    )

    venture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ventures.id", ondelete="CASCADE"),
        nullable=False,
    )
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    pitch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("venture_pitches.id", ondelete="SET NULL"),
        nullable=True,
    )
    co_venture_application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("co_ventures.id", ondelete="SET NULL"),
        nullable=True,
    )

    deal_kind: Mapped[VentureDealKind] = mapped_column(
        SAEnum(VentureDealKind, name="venture_deal_kind_enum", create_constraint=False),
        nullable=False,
    )
    deal_status: Mapped[VentureDealStatus] = mapped_column(
        SAEnum(VentureDealStatus, name="venture_deal_status_enum", create_constraint=False),
        default=VentureDealStatus.PENDING_PAYMENT,
        nullable=False,
    )
    escrow_status: Mapped[MarketplaceEscrowStatus] = mapped_column(
        SAEnum(MarketplaceEscrowStatus, name="marketplace_escrow_status_enum", create_constraint=False),
        default=MarketplaceEscrowStatus.HELD,
        nullable=False,
    )

    gross_amount_inr: Mapped[float] = mapped_column(Float, nullable=False)
    platform_fee_inr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    seller_payout_inr: Mapped[float] = mapped_column(Float, nullable=False)
    equity_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    razorpay_order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, unique=True)
    razorpay_refund_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    events: Mapped[list["VentureDealEvent"]] = relationship(
        "VentureDealEvent",
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="VentureDealEvent.created_at",
    )
    venture: Mapped["Venture"] = relationship("Venture", foreign_keys=[venture_id])
    buyer: Mapped["AppUser"] = relationship("AppUser", foreign_keys=[buyer_id])
    seller: Mapped["AppUser"] = relationship("AppUser", foreign_keys=[seller_id])
    pitch: Mapped[Optional["VenturePitch"]] = relationship(
        "VenturePitch",
        foreign_keys=[pitch_id],
    )
    co_venture_application: Mapped[Optional["CoVenture"]] = relationship(
        "CoVenture",
        foreign_keys=[co_venture_application_id],
    )
