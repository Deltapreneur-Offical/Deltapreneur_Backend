"""Add openprovider_managed_acquisitions table.

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-07-23 12:40:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "openprovider_managed_acquisitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("domain_name", sa.String(length=255), nullable=False),
        sa.Column("tld", sa.String(length=64), nullable=False),
        sa.Column("period_years", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("quoted_price_inr", sa.Float(), nullable=False),
        sa.Column("payable_inr", sa.Float(), nullable=False),
        sa.Column("gst_inr", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gst_rate", sa.Float(), nullable=True),
        sa.Column("price_per_year_inr", sa.Float(), nullable=True),
        sa.Column("provider_unit_price_inr", sa.Float(), nullable=True),
        sa.Column("commission_rate", sa.Float(), nullable=True),
        sa.Column("price_source", sa.String(length=64), nullable=True),
        sa.Column("registry_tier", sa.String(length=16), nullable=False, server_default="standard"),
        sa.Column("is_registry_premium", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pricing_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column("in_progress_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_op_managed_acq_user_id",
        "openprovider_managed_acquisitions",
        ["user_id"],
    )
    op.create_index(
        "ix_op_managed_acq_status",
        "openprovider_managed_acquisitions",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_op_managed_acq_status", table_name="openprovider_managed_acquisitions")
    op.drop_index("ix_op_managed_acq_user_id", table_name="openprovider_managed_acquisitions")
    op.drop_table("openprovider_managed_acquisitions")
