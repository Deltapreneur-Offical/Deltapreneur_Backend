"""Create hub_registrar_offices table.

Revision ID: hubreg001
Revises: rp_tech_sub_retry_fields_001
Create Date: 2026-08-19 12:00:00.000000

SAFETY: additive only — new table, no existing data affected.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "hubreg001"
down_revision: Union[str, Sequence[str], None] = "rp_tech_sub_retry_fields_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hub_registrar_offices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("office_name", sa.String(length=255), nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False, server_default=sa.text("''")),
        sa.Column("full_address", sa.Text(), nullable=False),
        sa.Column("map_link", sa.String(length=500), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hub_registrar_offices")),
    )
    op.create_index(
        "idx_hub_registrar_offices_public_browse",
        "hub_registrar_offices",
        ["is_deleted", "is_active", "display_order"],
        unique=False,
    )
    op.create_index(
        "idx_hub_registrar_offices_active",
        "hub_registrar_offices",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        "idx_hub_registrar_offices_city",
        "hub_registrar_offices",
        ["city"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_hub_registrar_offices_city", table_name="hub_registrar_offices")
    op.drop_index("idx_hub_registrar_offices_active", table_name="hub_registrar_offices")
    op.drop_index("idx_hub_registrar_offices_public_browse", table_name="hub_registrar_offices")
    op.drop_table("hub_registrar_offices")
