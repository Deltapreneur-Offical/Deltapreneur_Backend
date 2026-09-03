"""operations_service_requests table

Revision ID: r4s5t6u7v8w9
Revises: q3r4s5t6u7v8
Create Date: 2026-06-12 18:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "r4s5t6u7v8w9"
down_revision: Union[str, Sequence[str], None] = "q3r4s5t6u7v8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operations_service_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operations_service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_type", sa.String(length=32), nullable=False),
        sa.Column("service_type", sa.String(length=32), nullable=False),
        sa.Column("billing_period", sa.String(length=32), nullable=False),
        sa.Column("service_name", sa.String(length=255), nullable=False),
        sa.Column("quoted_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=64), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("city_state", sa.String(length=255), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("preferred_timeline", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["operations_service_id"],
            ["operations_services.id"],
            name=op.f("fk_operations_service_requests_operations_service_id_operations_services"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_operations_service_requests_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operations_service_requests")),
    )
    op.create_index(
        op.f("ix_operations_service_requests_operations_service_id"),
        "operations_service_requests",
        ["operations_service_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_operations_service_requests_user_id"),
        "operations_service_requests",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "idx_ops_service_requests_user_service",
        "operations_service_requests",
        ["user_id", "operations_service_id"],
        unique=False,
    )
    op.create_index(
        "idx_ops_service_requests_status_created",
        "operations_service_requests",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_ops_service_requests_status_created", table_name="operations_service_requests")
    op.drop_index("idx_ops_service_requests_user_service", table_name="operations_service_requests")
    op.drop_index(
        op.f("ix_operations_service_requests_user_id"),
        table_name="operations_service_requests",
    )
    op.drop_index(
        op.f("ix_operations_service_requests_operations_service_id"),
        table_name="operations_service_requests",
    )
    op.drop_table("operations_service_requests")
