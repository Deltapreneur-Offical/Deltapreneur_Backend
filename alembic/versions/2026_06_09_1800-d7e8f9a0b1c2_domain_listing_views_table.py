"""domain listing views table

Revision ID: d7e8f9a0b1c2
Revises: f1e2d3c4b5a6
Create Date: 2026-06-09 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "f1e2d3c4b5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "domain_listing_views",
        sa.Column("domain_listing_id", sa.UUID(), nullable=False),
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
            name=op.f("fk_domain_listing_views_viewer_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_domain_listing_views")),
    )
    op.create_index(
        "idx_domain_listing_views_listing_id",
        "domain_listing_views",
        ["domain_listing_id"],
        unique=False,
    )
    op.create_index(
        "idx_domain_listing_views_viewed_at",
        "domain_listing_views",
        ["viewed_at"],
        unique=False,
    )
    op.create_index(
        "idx_domain_listing_views_viewer_id",
        "domain_listing_views",
        ["viewer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_domain_listing_views_viewer_id", table_name="domain_listing_views")
    op.drop_index("idx_domain_listing_views_viewed_at", table_name="domain_listing_views")
    op.drop_index("idx_domain_listing_views_listing_id", table_name="domain_listing_views")
    op.drop_table("domain_listing_views")
