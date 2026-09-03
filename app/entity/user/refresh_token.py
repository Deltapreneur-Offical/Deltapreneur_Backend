import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String
)

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.entity.base import (
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
)

from app.entity.user.app_user import AppUser


class RevocationReason(str, enum.Enum):
    ROTATED = "ROTATED"
    LOGOUT = "LOGOUT"
    ADMIN_REVOKED = "ADMIN_REVOKED"
    REUSE_DETECTED = "REUSE_DETECTED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    USER_DELETED = "USER_DELETED"


class RefreshToken(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    Base,
):

    __tablename__ = "refresh_tokens"

    __table_args__ = (
        Index("idx_refresh_token_hash", "token_hash"),
        Index("idx_refresh_user_id", "user_id"),
        Index("idx_refresh_session_public_id", "session_public_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # HMAC/SHA256 hashed refresh token
    token_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )

    # Shared across token rotation chain
    session_public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=uuid.uuid4,
        nullable=False,
    )

    # Rotation lineage
    parent_token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )

    replaced_by_token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    revoked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    revocation_reason: Mapped[
        RevocationReason | None
    ] = mapped_column(
        Enum(
            RevocationReason,
            name="refresh_token_revocation_reason_enum",
        ),
        nullable=True,
    )

    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Session/device metadata
    ip_address: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    user_agent: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    device_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # Pepper versioning readiness
    pepper_kid: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    user = relationship(
        "AppUser",
        back_populates="refresh_tokens",
        foreign_keys=[user_id],
    )

    parent_token = relationship(
        "RefreshToken",
        remote_side="RefreshToken.id",
        foreign_keys=[parent_token_id],
        post_update=True,
    )

    replaced_by_token = relationship(
        "RefreshToken",
        remote_side="RefreshToken.id",
        foreign_keys=[replaced_by_token_id],
        post_update=True,
    )