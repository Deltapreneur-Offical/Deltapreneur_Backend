"""initial_uuid_schema

Revision ID: 07803b6e2462
Revises:
Create Date: 2026-05-12 15:48:39.127381

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "07803b6e2462"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

user_role_enum = postgresql.ENUM(
    "USER",
    "GUEST",
    "ADMIN",
    "COBROTHER",
    name="user_role_enum",
    create_type=False,
)
auth_provider_enum = postgresql.ENUM(
    "OAUTH",
    "PHONE_OTP",
    "EMAIL",
    name="auth_provider_enum",
    create_type=False,
)
refresh_token_revocation_reason_enum = postgresql.ENUM(
    "ROTATED",
    "LOGOUT",
    "ADMIN_REVOKED",
    "REUSE_DETECTED",
    "PASSWORD_CHANGED",
    "USER_DELETED",
    name="refresh_token_revocation_reason_enum",
    create_type=False,
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    user_role_enum.create(bind, checkfirst=True)
    auth_provider_enum.create(bind, checkfirst=True)
    refresh_token_revocation_reason_enum.create(bind, checkfirst=True)

    if "users" not in existing_tables:
        op.create_table(
            "users",
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("firstname", sa.String(length=100), nullable=True),
            sa.Column("lastname", sa.String(length=100), nullable=True),
            sa.Column("username", sa.String(length=100), nullable=True),
            sa.Column("password", sa.String(length=255), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("email_verified", sa.Boolean(), nullable=False),
            sa.Column("role", user_role_enum, nullable=False),
            sa.Column("auth_provider", auth_provider_enum, nullable=False),
            sa.Column("oauth_provider", sa.String(length=100), nullable=True),
            sa.Column("oauth_provider_id", sa.String(length=255), nullable=True),
            sa.Column("profile_complete", sa.Boolean(), nullable=False),
            sa.Column("phone_number", sa.String(length=20), nullable=True),
            sa.Column("phone_verified", sa.Boolean(), nullable=False),
            sa.Column("otp", sa.String(length=10), nullable=True),
            sa.Column("otp_expiry", sa.DateTime(timezone=True), nullable=True),
            sa.Column("verification_token", sa.String(length=255), nullable=True),
            sa.Column(
                "verification_token_expiry",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("google_access_token", sa.String(length=2048), nullable=True),
            sa.Column("google_refresh_token", sa.String(length=2048), nullable=True),
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deleted_by", sa.UUID(), nullable=True),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
            sa.UniqueConstraint("username", name=op.f("uq_users_username")),
        )
        op.create_index("idx_user_email", "users", ["email"], unique=False)
        op.create_index(
            "idx_user_verification_token",
            "users",
            ["verification_token"],
            unique=False,
        )
        op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    if "refresh_tokens" not in existing_tables:
        op.create_table(
            "refresh_tokens",
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("token_hash", sa.String(length=255), nullable=False),
            sa.Column("session_public_id", sa.UUID(), nullable=False),
            sa.Column("parent_token_id", sa.UUID(), nullable=True),
            sa.Column("replaced_by_token_id", sa.UUID(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked", sa.Boolean(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "revocation_reason",
                refresh_token_revocation_reason_enum,
                nullable=True,
            ),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ip_address", sa.String(length=100), nullable=True),
            sa.Column("user_agent", sa.String(length=1000), nullable=True),
            sa.Column("device_name", sa.String(length=255), nullable=True),
            sa.Column("pepper_kid", sa.String(length=50), nullable=True),
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["parent_token_id"],
                ["refresh_tokens.id"],
                name=op.f("fk_refresh_tokens_parent_token_id_refresh_tokens"),
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["replaced_by_token_id"],
                ["refresh_tokens.id"],
                name=op.f("fk_refresh_tokens_replaced_by_token_id_refresh_tokens"),
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name=op.f("fk_refresh_tokens_user_id_users"),
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
            sa.UniqueConstraint(
                "token_hash",
                name=op.f("uq_refresh_tokens_token_hash"),
            ),
        )
        op.create_index(
            "idx_refresh_session_public_id",
            "refresh_tokens",
            ["session_public_id"],
            unique=False,
        )
        op.create_index(
            "idx_refresh_token_hash",
            "refresh_tokens",
            ["token_hash"],
            unique=False,
        )
        op.create_index(
            "idx_refresh_user_id",
            "refresh_tokens",
            ["user_id"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "refresh_tokens" in existing_tables:
        op.drop_index("idx_refresh_user_id", table_name="refresh_tokens")
        op.drop_index("idx_refresh_token_hash", table_name="refresh_tokens")
        op.drop_index("idx_refresh_session_public_id", table_name="refresh_tokens")
        op.drop_table("refresh_tokens")

    if "users" in existing_tables:
        op.drop_index(op.f("ix_users_email"), table_name="users")
        op.drop_index("idx_user_verification_token", table_name="users")
        op.drop_index("idx_user_email", table_name="users")
        op.drop_table("users")

    refresh_token_revocation_reason_enum.drop(bind, checkfirst=True)
    auth_provider_enum.drop(bind, checkfirst=True)
    user_role_enum.drop(bind, checkfirst=True)
