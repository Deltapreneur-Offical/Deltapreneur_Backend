"""Add Virtual Assistant profile view tracking.

Revision ID: va29views001
Revises: va25email0001
Create Date: 2026-07-29 17:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "va29views001"
down_revision: Union[str, Sequence[str], None] = "va25email0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "virtual_assistant_views",
        sa.Column("application_id", sa.UUID(), nullable=False),
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
            name=op.f("fk_virtual_assistant_views_viewer_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_virtual_assistant_views")),
    )
    op.create_index(
        "idx_va_views_application_id",
        "virtual_assistant_views",
        ["application_id"],
        unique=False,
    )
    op.create_index(
        "idx_va_views_viewer_id",
        "virtual_assistant_views",
        ["viewer_id"],
        unique=False,
    )
    op.create_index(
        "idx_va_views_viewed_at",
        "virtual_assistant_views",
        ["viewed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_va_views_viewed_at", table_name="virtual_assistant_views")
    op.drop_index("idx_va_views_viewer_id", table_name="virtual_assistant_views")
    op.drop_index("idx_va_views_application_id", table_name="virtual_assistant_views")
    op.drop_table("virtual_assistant_views")
