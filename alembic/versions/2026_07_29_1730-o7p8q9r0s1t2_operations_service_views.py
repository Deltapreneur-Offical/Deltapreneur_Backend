"""Add Operations service (Business Solutions) view tracking.

Revision ID: opsviews001
Revises: va29views001
Create Date: 2026-07-29 17:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "opsviews001"
down_revision: Union[str, Sequence[str], None] = "va29views001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operations_service_views",
        sa.Column("operations_service_id", sa.UUID(), nullable=False),
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
            name=op.f("fk_operations_service_views_viewer_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operations_service_views")),
    )
    op.create_index(
        "idx_ops_service_views_service_id",
        "operations_service_views",
        ["operations_service_id"],
        unique=False,
    )
    op.create_index(
        "idx_ops_service_views_viewer_id",
        "operations_service_views",
        ["viewer_id"],
        unique=False,
    )
    op.create_index(
        "idx_ops_service_views_viewed_at",
        "operations_service_views",
        ["viewed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_ops_service_views_viewed_at", table_name="operations_service_views")
    op.drop_index("idx_ops_service_views_viewer_id", table_name="operations_service_views")
    op.drop_index("idx_ops_service_views_service_id", table_name="operations_service_views")
    op.drop_table("operations_service_views")
