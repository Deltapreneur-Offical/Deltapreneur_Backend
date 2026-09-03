"""Open roles on a venture listing."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.entity.coventure.venture_entity import Venture


class VentureRole(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venture_roles"
    __table_args__ = (Index("idx_venture_roles_venture_id", "venture_id"),)

    venture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ventures.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    skill_domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    commitment: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    experience_level: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    equity_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    equity_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vesting_terms: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    salary_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    salary_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    budget_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    budget_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    investment_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    investment_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    venture: Mapped["Venture"] = relationship(
        "Venture",
        back_populates="roles",
        foreign_keys=[venture_id],
    )
