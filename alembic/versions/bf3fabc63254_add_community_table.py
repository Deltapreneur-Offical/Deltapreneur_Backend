"""add community table

Revision ID: bf3fabc63254
Revises: 07803b6e2462
Create Date: 2026-05-13 16:55:28.812669

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "bf3fabc63254"
down_revision: Union[str, Sequence[str], None] = "07803b6e2462"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "community",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("linked_in_id", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("image_url", sa.String(length=1000), nullable=True),
        sa.Column("linked_in_profile_url", sa.String(length=1000), nullable=True),
        sa.Column("role", sa.String(length=100), nullable=True),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skills", sa.String(length=1000), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("why_im_here", sa.Text(), nullable=True),
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("app_user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["app_user_id"],
            ["users.id"],
            name=op.f("fk_community_app_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_community")),
        sa.UniqueConstraint("app_user_id", name=op.f("uq_community_app_user_id")),
        sa.UniqueConstraint("linked_in_id", name=op.f("uq_community_linked_in_id")),
    )

    op.create_index(
        op.f("ix_community_id"),
        "community",
        ["id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_community_id"),
        table_name="community",
    )
    op.drop_table("community")