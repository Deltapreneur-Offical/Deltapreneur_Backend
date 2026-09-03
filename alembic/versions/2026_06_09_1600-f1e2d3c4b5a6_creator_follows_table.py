"""creator follows table

Revision ID: f1e2d3c4b5a6
Revises: l1m2n3o4p5q6
Create Date: 2026-06-09 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "f1e2d3c4b5a6"
down_revision: Union[str, Sequence[str], None] = "l1m2n3o4p5q6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "creator_follows" in inspector.get_table_names():
        return

    op.create_table(
        "creator_follows",
        sa.Column("follower_user_id", sa.UUID(), nullable=False),
        sa.Column("community_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["community_id"],
            ["community.id"],
            name=op.f("fk_creator_follows_community_id_community"),
        ),
        sa.ForeignKeyConstraint(
            ["follower_user_id"],
            ["users.id"],
            name=op.f("fk_creator_follows_follower_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_creator_follows")),
        sa.UniqueConstraint(
            "follower_user_id",
            "community_id",
            name="uq_creator_follow_user_community",
        ),
    )
    op.create_index(
        op.f("ix_creator_follows_community_id"),
        "creator_follows",
        ["community_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_creator_follows_follower_user_id"),
        "creator_follows",
        ["follower_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_creator_follows_follower_user_id"), table_name="creator_follows")
    op.drop_index(op.f("ix_creator_follows_community_id"), table_name="creator_follows")
    op.drop_table("creator_follows")
