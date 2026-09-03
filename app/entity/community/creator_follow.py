from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class CreatorFollow(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    SoftDeleteMixin,
    Base,
):
    __tablename__ = "creator_follows"

    __table_args__ = (
        UniqueConstraint(
            "follower_user_id",
            "community_id",
            name="uq_creator_follow_user_community",
        ),
    )

    follower_user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    community_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("community.id"),
        nullable=False,
        index=True,
    )

    follower = relationship(
        "AppUser",
        foreign_keys=[follower_user_id],
        backref="creator_follows",
    )

    community = relationship(
        "Community",
        foreign_keys=[community_id],
        backref="followers",
    )
