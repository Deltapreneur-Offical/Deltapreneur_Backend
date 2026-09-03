"""Meetings, domain enquiries, fee columns, cobrother help order id.

Revision ID: e4f5a6b7c8d9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-27 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL: add enum value for fee workflow (idempotent)
    op.execute(
        sa.text(
            """
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_enum e
                JOIN pg_type t ON e.enumtypid = t.oid
                WHERE t.typname = 'cobrother_request_status_enum'
                  AND e.enumlabel = 'PAYMENT_PENDING'
              ) THEN
                ALTER TYPE cobrother_request_status_enum ADD VALUE 'PAYMENT_PENDING';
              END IF;
            END $$;
            """
        )
    )

    op.add_column(
        "cobrother_requests",
        sa.Column("lister_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "cobrother_requests",
        sa.Column("razorpay_order_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "cobrother_requests",
        sa.Column("razorpay_payment_id", sa.String(length=128), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_cobrother_requests_lister_id_users"),
        "cobrother_requests",
        "users",
        ["lister_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "software_purchases",
        sa.Column("cobrother_help_razorpay_order_id", sa.String(length=128), nullable=True),
    )

    op.create_table(
        "meeting_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("auction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lister_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("meeting_link", sa.Text(), nullable=True),
        sa.Column("google_calendar_event_id", sa.String(length=512), nullable=True),
        sa.Column("calendar_event_link", sa.String(length=1024), nullable=True),
        sa.Column("topic", sa.String(length=500), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("cancelled_by", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["auction_id"], ["community_auctions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lister_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meeting_schedules")),
    )
    op.create_index(
        "ix_meeting_schedules_auction_id",
        "meeting_schedules",
        ["auction_id"],
    )
    op.create_index(
        "ix_meeting_schedules_lister_id",
        "meeting_schedules",
        ["lister_id"],
    )
    op.create_index(
        "ix_meeting_schedules_requester_id",
        "meeting_schedules",
        ["requester_id"],
    )

    op.create_table(
        "domain_enquiries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("domain_listing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enquirer_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.ForeignKeyConstraint(
            ["domain_listing_id"],
            ["domain_listings.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["enquirer_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_domain_enquiries")),
    )
    op.create_index(
        "ix_domain_enquiries_domain_listing_id",
        "domain_enquiries",
        ["domain_listing_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_domain_enquiries_domain_listing_id", table_name="domain_enquiries")
    op.drop_table("domain_enquiries")
    op.drop_index("ix_meeting_schedules_requester_id", table_name="meeting_schedules")
    op.drop_index("ix_meeting_schedules_lister_id", table_name="meeting_schedules")
    op.drop_index("ix_meeting_schedules_auction_id", table_name="meeting_schedules")
    op.drop_table("meeting_schedules")
    op.drop_column("software_purchases", "cobrother_help_razorpay_order_id")
    op.drop_constraint(
        op.f("fk_cobrother_requests_lister_id_users"),
        "cobrother_requests",
        type_="foreignkey",
    )
    op.drop_column("cobrother_requests", "razorpay_payment_id")
    op.drop_column("cobrother_requests", "razorpay_order_id")
    op.drop_column("cobrother_requests", "lister_id")
    # Cannot remove enum value PAYMENT_PENDING safely on PG
