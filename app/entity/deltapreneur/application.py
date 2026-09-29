"""Apply-to-Become-Deltapreneur application (below ₹40L route).

Independent of Virtual Assistants — Deltapreneur-specific table only.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class DeltapreneurApplication(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "deltapreneur_applications"

    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    company_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    annual_revenue_inr: Mapped[float] = mapped_column(
        Numeric(14, 2),
        nullable=False,
    )

    linked_in_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    website_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    about: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    motivation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Admin-only lifecycle: PENDING_REVIEW | APPROVED | REJECTED | ONBOARDED
    status: Mapped[str] = mapped_column(
        String(32),
        default="PENDING_REVIEW",
        nullable=False,
        index=True,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    reviewed_by_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    onboarded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
