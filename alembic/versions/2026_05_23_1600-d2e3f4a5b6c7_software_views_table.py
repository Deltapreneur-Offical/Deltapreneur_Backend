"""Create software_views analytics table

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-05-23 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "software_views" in inspect(op.get_bind()).get_table_names():
        return

    op.create_table(
        "software_views",
        sa.Column("software_id", sa.UUID(), nullable=False),
        sa.Column("viewer_id", sa.UUID(), nullable=True),
        sa.Column("viewer_industry", sa.String(length=100), nullable=True),
        sa.Column("viewer_role", sa.String(length=100), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["viewer_id"],
            ["users.id"],
            name=op.f("fk_software_views_viewer_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_software_views")),
    )
    op.create_index(
        "idx_software_views_software_id",
        "software_views",
        ["software_id"],
        unique=False,
    )
    op.create_index(
        "idx_software_views_viewed_at",
        "software_views",
        ["viewed_at"],
        unique=False,
    )
    op.create_index(
        "idx_software_views_viewer_id",
        "software_views",
        ["viewer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_software_views_viewer_id", table_name="software_views")
    op.drop_index("idx_software_views_viewed_at", table_name="software_views")
    op.drop_index("idx_software_views_software_id", table_name="software_views")
    op.drop_table("software_views")
