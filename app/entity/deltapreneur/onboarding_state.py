"""Per-user Deltapreneur onboarding eligibility state.

Separates *onboarding eligibility* (who may enter the creator LinkedIn flow)
from *profile completeness / public visibility* (`community.is_approved`).
"""

from sqlalchemy import (
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class DeltapreneurOnboardingState(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "deltapreneur_onboarding_state"

    app_user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    declared_revenue_inr: Mapped[float] = mapped_column(
        Numeric(14, 2),
        nullable=False,
    )

    # SELF_DECLARED (>= ₹40L direct route) | INVITATION (approved application)
    channel: Mapped[str] = mapped_column(
        String(32),
        default="SELF_DECLARED",
        nullable=False,
    )

    invitation_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("deltapreneur_invitations.id", ondelete="SET NULL"),
        nullable=True,
    )
