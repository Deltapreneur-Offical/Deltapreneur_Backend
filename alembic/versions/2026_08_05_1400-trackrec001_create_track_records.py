"""Create track_records admin audit table.

Revision ID: trackrec001
Revises: softcur001
Create Date: 2026-08-05 14:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "trackrec001"
down_revision: Union[str, Sequence[str], None] = "softcur001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "track_records" in inspect(op.get_bind()).get_table_names():
        return

    op.create_table(
        "track_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("internal_order_id", sa.String(length=100), nullable=False),
        sa.Column("cart_batch_id", sa.String(length=100), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("provider_subcategory", sa.String(length=100), nullable=True),
        sa.Column("item_name", sa.String(length=255), nullable=False),
        sa.Column("item_id", sa.String(length=255), nullable=True),
        sa.Column("quantity_years", sa.Integer(), nullable=False),
        sa.Column("buyer_name", sa.String(length=255), nullable=True),
        sa.Column("buyer_email", sa.String(length=255), nullable=True),
        sa.Column("buyer_phone", sa.String(length=100), nullable=True),
        sa.Column("buyer_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("amount_charged", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("subtotal_ex_gst", sa.Numeric(12, 2), nullable=True),
        sa.Column("gst_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("payment_status", sa.String(length=50), nullable=False),
        sa.Column("razorpay_order_id", sa.String(length=100), nullable=True),
        sa.Column("razorpay_payment_id", sa.String(length=100), nullable=True),
        sa.Column("razorpay_refund_id", sa.String(length=100), nullable=True),
        sa.Column("fulfillment_status", sa.String(length=50), nullable=False),
        sa.Column("overall_status", sa.String(length=50), nullable=False),
        sa.Column("openprovider_domain_id", sa.String(length=100), nullable=True),
        sa.Column("provision_attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_source", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("admin_deep_link", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_track_records")),
        sa.UniqueConstraint("internal_order_id", name=op.f("uq_track_records_internal_order_id")),
    )
    op.create_index("idx_track_records_created_at", "track_records", ["created_at"], unique=False)
    op.create_index("idx_track_records_category", "track_records", ["category"], unique=False)
    op.create_index("idx_track_records_overall_status", "track_records", ["overall_status"], unique=False)
    op.create_index("idx_track_records_buyer_email", "track_records", ["buyer_email"], unique=False)
    op.create_index(
        "idx_track_records_razorpay_payment_id",
        "track_records",
        ["razorpay_payment_id"],
        unique=False,
    )
    op.create_index(
        "idx_track_records_razorpay_order_id",
        "track_records",
        ["razorpay_order_id"],
        unique=False,
    )
    op.create_index(
        "idx_track_records_internal_order_id",
        "track_records",
        ["internal_order_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_track_records_internal_order_id", table_name="track_records")
    op.drop_index("idx_track_records_razorpay_order_id", table_name="track_records")
    op.drop_index("idx_track_records_razorpay_payment_id", table_name="track_records")
    op.drop_index("idx_track_records_buyer_email", table_name="track_records")
    op.drop_index("idx_track_records_overall_status", table_name="track_records")
    op.drop_index("idx_track_records_category", table_name="track_records")
    op.drop_index("idx_track_records_created_at", table_name="track_records")
    op.drop_table("track_records")
