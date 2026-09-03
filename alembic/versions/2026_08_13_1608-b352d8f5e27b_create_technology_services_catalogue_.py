"""create technology_services_catalogue table

Revision ID: b352d8f5e27b
Revises: None
Create Date: 2026-08-13 16:08:11.972065

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b352d8f5e27b'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "technology_services_catalogue" not in tables:
        op.create_table(
            "technology_services_catalogue",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), nullable=False),
            sa.Column("slug", sa.String(length=100), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("category", sa.String(length=64), nullable=False),
            sa.Column("short_description", sa.Text(), nullable=False),
            sa.Column("long_description", sa.Text(), nullable=True),
            sa.Column("badge", sa.String(length=64), nullable=True),
            sa.Column("icon", sa.String(length=64), nullable=True),
            sa.Column("is_featured", sa.Boolean(), nullable=False),
            sa.Column("is_available", sa.Boolean(), nullable=False),
            sa.Column("features_json", sa.Text(), nullable=True),
            sa.Column("plans_json", sa.Text(), nullable=True),
            sa.Column("faqs_json", sa.Text(), nullable=True),
            sa.Column("display_order", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_technology_services_catalogue")),
            sa.UniqueConstraint("slug", name="uq_tech_services_slug"),
        )
        op.create_index(
            "idx_tech_services_slug",
            "technology_services_catalogue",
            ["slug"],
            unique=True,
        )
        op.create_index(
            "idx_tech_services_category",
            "technology_services_catalogue",
            ["category"],
            unique=False,
        )
        op.create_index(
            "idx_tech_services_featured",
            "technology_services_catalogue",
            ["is_featured"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "technology_services_catalogue" in tables:
        op.drop_index("idx_tech_services_featured", table_name="technology_services_catalogue")
        op.drop_index("idx_tech_services_category", table_name="technology_services_catalogue")
        op.drop_index("idx_tech_services_slug", table_name="technology_services_catalogue")
        op.drop_table("technology_services_catalogue")
