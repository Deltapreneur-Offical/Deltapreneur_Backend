"""registration auction payments tables

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-05-20 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    postgresql.ENUM(
        "CREATED", "PAYMENT_COMPLETED", "ACTIVE", "PAYMENT_FAILED",
        "EXPIRED", "FAILED", "PROVISION_FAILED", "REFUNDED",
        name="registration_order_status_enum",
    ).create(bind, checkfirst=True)

    postgresql.ENUM(
        "CREATED", "COMPLETED", "FAILED",
        name="software_payment_status_enum",
    ).create(bind, checkfirst=True)

    postgresql.ENUM(
        "ONE_DAY", "SEVEN_DAYS", "FIFTEEN_DAYS", "THIRTY_DAYS",
        name="venture_auction_duration_enum",
    ).create(bind, checkfirst=True)

    op.create_table(
        "domain_registration_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("domain_name", sa.String(255), nullable=False),
        sa.Column("domain_extension", sa.String(32), nullable=False),
        sa.Column("buyer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("buyer_full_name", sa.String(255), nullable=True),
        sa.Column("buyer_email", sa.String(255), nullable=True),
        sa.Column("buyer_phone", sa.String(32), nullable=True),
        sa.Column("street", sa.String(512), nullable=True),
        sa.Column("city", sa.String(128), nullable=True),
        sa.Column("state", sa.String(128), nullable=True),
        sa.Column("zip_code", sa.String(32), nullable=True),
        sa.Column("country", sa.String(8), nullable=False),
        sa.Column("period_years", sa.Integer(), nullable=False),
        sa.Column("price_inr", sa.Float(), nullable=False),
        sa.Column("razorpay_order_id", sa.String(128), nullable=True),
        sa.Column("razorpay_payment_id", sa.String(128), nullable=True),
        sa.Column("razorpay_refund_id", sa.String(128), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="registration_order_status_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("open_provider_handle", sa.String(128), nullable=True),
        sa.Column("open_provider_domain_id", sa.String(128), nullable=True),
        sa.Column("open_provider_status", sa.String(64), nullable=True),
        sa.Column("provision_message", sa.Text(), nullable=True),
        sa.Column("provision_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transfer_auth_code", sa.String(64), nullable=True),
        sa.Column("transfer_status", sa.String(64), nullable=False, server_default="NONE"),
        sa.Column("renewal_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_renewal_razorpay_order_id", sa.String(128), nullable=True),
        sa.Column("pending_renewal_years", sa.Integer(), nullable=True),
        sa.Column("pending_renewal_amount_inr", sa.Float(), nullable=True),
        sa.Column("last_renewal_payment_id", sa.String(128), nullable=True),
        sa.Column("registrar_lock", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("whois_privacy", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("icann_verification_status", sa.String(32), nullable=False, server_default="UNKNOWN"),
        sa.Column("auto_renew_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("custom_nameservers", sa.Text(), nullable=True),
        sa.Column("dns_records_json", sa.Text(), nullable=True),
        sa.Column("last_expiry_reminder_days", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["buyer_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "software_purchases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("software_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("buyer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("buyer_full_name", sa.String(255), nullable=True),
        sa.Column("buyer_email", sa.String(255), nullable=True),
        sa.Column("buyer_phone", sa.String(32), nullable=True),
        sa.Column("razorpay_order_id", sa.String(128), nullable=True),
        sa.Column("razorpay_payment_id", sa.String(128), nullable=True),
        sa.Column(
            "payment_status",
            postgresql.ENUM(name="software_payment_status_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("co_brother_opt_in", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("co_brother_help_paid", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["software_id"], ["software_listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["buyer_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "venture_auctions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("venture_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="auction_status_enum", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "duration",
            postgresql.ENUM(name="venture_auction_duration_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("min_bid_price", sa.Float(), nullable=False),
        sa.Column("current_highest_bid", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_bids", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_winner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("original_end_time", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["venture_id"], ["ventures.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_winner_id"], ["users.id"]),
        sa.UniqueConstraint("venture_id"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "venture_auction_bids",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("venture_auction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bidder_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("bidder_name", sa.String(255), nullable=True),
        sa.Column("bid_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_winning_bid", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["venture_auction_id"], ["venture_auctions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bidder_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("venture_auction_bids")
    op.drop_table("venture_auctions")
    op.drop_table("software_purchases")
    op.drop_table("domain_registration_orders")
