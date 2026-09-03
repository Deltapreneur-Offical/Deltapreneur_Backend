"""add_password_reset_tokens

Revision ID: b8f2a1c3d4e5
Revises: 07803b6e2462
Create Date: 2026-05-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8f2a1c3d4e5"
down_revision: Union[str, Sequence[str], None] = "07803b6e2462"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_table(
        "password_reset_tokens",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_ip", sa.String(length=100), nullable=True),
        sa.Column("user_agent", sa.String(length=1000), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_password_reset_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_password_reset_tokens"),
        ),
        sa.UniqueConstraint(
            "token_hash",
            name=op.f("uq_password_reset_tokens_token_hash"),
        ),
    )
    op.create_index(
        "idx_password_reset_user_created",
        "password_reset_tokens",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_password_reset_expires_at",
        "password_reset_tokens",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_password_reset_expires_at",
        table_name="password_reset_tokens",
    )
    op.drop_index(
        "idx_password_reset_user_created",
        table_name="password_reset_tokens",
    )
    op.drop_table("password_reset_tokens")
    op.drop_column("users", "password_changed_at")
