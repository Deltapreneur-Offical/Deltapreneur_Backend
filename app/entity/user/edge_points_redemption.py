import enum
from sqlalchemy import String, ForeignKey, Enum, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.entity.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

class RedemptionStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class EdgePointsRedemption(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "edge_points_redemptions"

    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    razorpay_order_id: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        index=True,
        nullable=False,
    )
    edge_points_redeemed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    status: Mapped[RedemptionStatus] = mapped_column(
        Enum(RedemptionStatus, name="redemption_status_enum"),
        default=RedemptionStatus.PENDING,
        nullable=False,
    )

    user = relationship("AppUser", backref="redemptions")
