"""Add Razorpay payment fields to operations_service_requests. Revision ID: ops_req_rzpay_001
"""
from alembic import op
import sqlalchemy as sa

revision = "ops_req_rzpay_001"
down_revision = "ops_req_category_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "operations_service_requests",
        sa.Column("razorpay_order_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "operations_service_requests",
        sa.Column("razorpay_payment_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "operations_service_requests",
        sa.Column("razorpay_signature", sa.String(512), nullable=True),
    )
    op.add_column(
        "operations_service_requests",
        sa.Column("payment_status", sa.String(32), nullable=False, server_default="PENDING"),
    )
    op.add_column(
        "operations_service_requests",
        sa.Column("payment_amount_inr", sa.Numeric(12, 2), nullable=True),
    )
    op.create_index(
        "idx_ops_service_requests_rzp_order",
        "operations_service_requests",
        ["razorpay_order_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_ops_service_requests_rzp_order", table_name="operations_service_requests")
    op.drop_column("operations_service_requests", "payment_amount_inr")
    op.drop_column("operations_service_requests", "payment_status")
    op.drop_column("operations_service_requests", "razorpay_signature")
    op.drop_column("operations_service_requests", "razorpay_payment_id")
    op.drop_column("operations_service_requests", "razorpay_order_id")
