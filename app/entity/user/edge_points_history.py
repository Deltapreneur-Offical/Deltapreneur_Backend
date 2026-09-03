import enum
from sqlalchemy import String, ForeignKey, Enum, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.entity.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

class EdgePointsTransactionType(str, enum.Enum):
    REFERRAL_EARN = "REFERRAL_EARN"
    CHECKOUT_REDEEM = "CHECKOUT_REDEEM"
    REDEEM_REVERT = "REDEEM_REVERT"

class EdgePointsHistory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "edge_points_history"

    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    points: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    transaction_type: Mapped[EdgePointsTransactionType] = mapped_column(
        Enum(EdgePointsTransactionType, name="edge_points_transaction_type_enum"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    user = relationship("AppUser", backref="points_history")
