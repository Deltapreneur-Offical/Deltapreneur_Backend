from datetime import datetime
from app.entity.auction.domain_entity import Domain as _Domain  # noqa: F401, E402

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Index,
    String,
    Integer,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.entity.base import (
    Base,
    UUIDPrimaryKeyMixin,
    SoftDeleteMixin,
    TimestampMixin,
)

from app.entity.user.auth_provider import (
    AuthProvider,
)

from app.entity.user.user_role import (
    UserRole,
)

# Required for SQLAlchemy relationship resolution
from app.entity.auction.domain_entity import (
    Domain as _Domain,
)  # noqa: F401,E402


class AppUser(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    SoftDeleteMixin,
    Base,
):

    __tablename__ = "users"

    __table_args__ = (
        Index(
            "idx_user_email",
            "email",
        ),

        Index(
            "idx_user_verification_token",
            "verification_token",
        ),

        Index(
            "idx_user_phone_number",
            "phone_number",
        ),
    )

    # ─────────────────────────────────────────────────────────
    # BASIC INFO
    # ─────────────────────────────────────────────────────────

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    firstname: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    lastname: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    username: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
    )

    password: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # ─────────────────────────────────────────────────────────
    # ACCOUNT STATUS
    # ─────────────────────────────────────────────────────────

    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    profile_complete: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    edge_points: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # ─────────────────────────────────────────────────────────
    # ROLE + AUTH
    # ─────────────────────────────────────────────────────────

    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            name="user_role_enum",
        ),
        default=UserRole.GUEST,
        nullable=False,
    )

    auth_provider: Mapped[AuthProvider] = mapped_column(
        Enum(
            AuthProvider,
            name="auth_provider_enum",
        ),
        default=AuthProvider.OAUTH,
        nullable=False,
    )

    oauth_provider: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    oauth_provider_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # ─────────────────────────────────────────────────────────
    # PHONE
    # ─────────────────────────────────────────────────────────

    phone_number: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    @property
    def full_name(self) -> str:
        return f"{self.firstname or ''} {self.lastname or ''}".strip()

    @property
    def mobile_number(self) -> str | None:
        return self.phone_number

    phone_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    address: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    otp: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    otp_expiry: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ─────────────────────────────────────────────────────────
    # EMAIL VERIFICATION
    # ─────────────────────────────────────────────────────────

    verification_token: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    verification_token_expiry: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ─────────────────────────────────────────────────────────
    # GOOGLE AUTH
    # ─────────────────────────────────────────────────────────

    google_access_token: Mapped[
        str | None
    ] = mapped_column(
        String(2048),
        nullable=True,
    )

    google_refresh_token: Mapped[
        str | None
    ] = mapped_column(
        String(2048),
        nullable=True,
    )

    # ─────────────────────────────────────────────────────────
    # PASSWORD MANAGEMENT
    # ─────────────────────────────────────────────────────────

    password_changed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ─────────────────────────────────────────────────────────
    # RELATIONSHIPS
    # ─────────────────────────────────────────────────────────

    refresh_tokens = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    domains_owned = relationship(
        "Domain",
        back_populates="owner",
        foreign_keys="Domain.owner_id",
    )



    password_reset_tokens = relationship(
        "PasswordResetToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )

from app.entity.user.refresh_token import RefreshToken as _RefreshToken  # noqa: F401
from app.entity.user.password_reset_token import PasswordResetToken as _PasswordResetToken  # noqa: F401
from app.entity.auction.domain_entity import Domain as _Domain  # noqa: F401
