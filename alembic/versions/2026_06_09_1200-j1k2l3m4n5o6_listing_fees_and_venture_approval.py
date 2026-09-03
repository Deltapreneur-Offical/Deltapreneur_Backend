"""Listing commission, auction fee payments, venture listing approval.

Revision ID: j1k2l3m4n5o6
Revises: a1b2c3d4e5f8
Create Date: 2026-06-09 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "j1k2l3m4n5o6"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "domain_listings",
        sa.Column("seller_price", sa.Float(), nullable=True),
    )
    op.add_column(
        "software_listings",
        sa.Column("seller_price", sa.Float(), nullable=True),
    )
    op.add_column(
        "brand_details",
        sa.Column("seller_deal_value", sa.BigInteger(), nullable=True),
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE venture_listing_approval_status_enum AS ENUM (
                'PENDING_APPROVAL', 'APPROVED', 'REJECTED'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.add_column(
        "ventures",
        sa.Column(
            "listing_approval_status",
            postgresql.ENUM(
                "PENDING_APPROVAL",
                "APPROVED",
                "REJECTED",
                name="venture_listing_approval_status_enum",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "ventures",
        sa.Column("listing_rejection_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "ventures",
        sa.Column("listing_approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ventures",
        sa.Column("listing_approved_by_user_id", sa.UUID(), nullable=True),
    )

    # Grandfather existing visible ventures — do not change stored prices.
    op.execute(
        """
        UPDATE ventures
        SET listing_approval_status = 'APPROVED'
        WHERE gstin_verified = true OR verified = true
        """
    )
    op.execute(
        """
        UPDATE ventures
        SET listing_approval_status = 'PENDING_APPROVAL'
        WHERE listing_approval_status IS NULL
        """
    )
    op.alter_column(
        "ventures",
        "listing_approval_status",
        nullable=False,
        server_default="PENDING_APPROVAL",
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE auction_fee_payment_kind_enum AS ENUM ('CREATION', 'BID');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE auction_fee_auction_type_enum AS ENUM (
                'DOMAIN', 'VENTURE', 'SOFTWARE', 'COMMUNITY'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE auction_fee_payment_status_enum AS ENUM (
                'CREATED', 'COMPLETED', 'CONSUMED'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )

    op.create_table(
        "auction_fee_payments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "payment_kind",
            postgresql.ENUM(
                "CREATION",
                "BID",
                name="auction_fee_payment_kind_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "auction_type",
            postgresql.ENUM(
                "DOMAIN",
                "VENTURE",
                "SOFTWARE",
                "COMMUNITY",
                name="auction_fee_auction_type_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("auction_id", sa.UUID(), nullable=True),
        sa.Column("reference_id", sa.UUID(), nullable=True),
        sa.Column("bid_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("fee_amount_inr", sa.Float(), nullable=False),
        sa.Column("razorpay_order_id", sa.String(length=64), nullable=False),
        sa.Column("razorpay_payment_id", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "CREATED",
                "COMPLETED",
                "CONSUMED",
                name="auction_fee_payment_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="CREATED",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("razorpay_order_id", name="uq_auction_fee_payments_order"),
    )
    op.create_index(
        "idx_auction_fee_payments_user_kind",
        "auction_fee_payments",
        ["user_id", "payment_kind"],
    )
    op.create_index(
        "idx_auction_fee_payments_order",
        "auction_fee_payments",
        ["razorpay_order_id"],
    )

    op.execute(
        """
        INSERT INTO platform_settings (setting_key, setting_value, updated_at)
        VALUES
            ('listing_commission_percent', '15', NOW()),
            ('auction_creation_fee_inr', '118', NOW()),
            ('auction_bid_fee_inr', '20', NOW())
        ON CONFLICT (setting_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("idx_auction_fee_payments_order", table_name="auction_fee_payments")
    op.drop_index("idx_auction_fee_payments_user_kind", table_name="auction_fee_payments")
    op.drop_table("auction_fee_payments")

    op.drop_column("ventures", "listing_approved_by_user_id")
    op.drop_column("ventures", "listing_approved_at")
    op.drop_column("ventures", "listing_rejection_reason")
    op.drop_column("ventures", "listing_approval_status")

    op.drop_column("brand_details", "seller_deal_value")
    op.drop_column("software_listings", "seller_price")
    op.drop_column("domain_listings", "seller_price")

    op.execute("DELETE FROM platform_settings WHERE setting_key IN ("
               "'listing_commission_percent', 'auction_creation_fee_inr', "
               "'auction_bid_fee_inr')")
