"""Co-venture application (partnership request)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.venture_enums import CoVentureStatus

if TYPE_CHECKING:
    from app.entity.coventure.venture_entity import Venture
    from app.entity.user.app_user import AppUser


class CoVenture(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "co_ventures"
    __table_args__ = (
        UniqueConstraint(
            "venture_id",
            "applicant_user_id",
            name="uq_coventure_venture_applicant",
        ),
        Index("idx_co_ventures_venture_id", "venture_id"),
        Index("idx_co_ventures_applicant_user_id", "applicant_user_id"),
    )

    venture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ventures.id", ondelete="CASCADE"),
        nullable=False,
    )
    applicant_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gstin: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    experience_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    portfolio_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    skills: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    previous_ventures: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resume_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    motivation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    relevant_experience: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    contribution_plan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    video_introduction_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[CoVentureStatus] = mapped_column(
        SAEnum(CoVentureStatus, name="co_venture_status_enum", create_constraint=False),
        default=CoVentureStatus.PENDING,
        nullable=False,
    )

    venture: Mapped["Venture"] = relationship(
        "Venture",
        back_populates="co_venture_applications",
        foreign_keys=[venture_id],
        lazy="selectin",
    )
    applicant: Mapped["AppUser"] = relationship(
        "AppUser",
        foreign_keys=[applicant_user_id],
        lazy="selectin",
    )
