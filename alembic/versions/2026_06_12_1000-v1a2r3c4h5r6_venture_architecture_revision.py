"""Venture / Co-Venture architecture revision — pitches, deals, listing modes.

Revision ID: v1a2r3c4h5r6
Revises: f2253fceaea2
Create Date: 2026-06-12 10:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v1a2r3c4h5r6"
down_revision: Union[str, Sequence[str], None] = "f2253fceaea2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE venture_listing_mode_enum AS ENUM ('VENTURE', 'CO_VENTURE');
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE venture_listing_status_enum AS ENUM (
                'ACTIVE', 'CLOSED', 'DEAL_FINALIZED', 'COMPLETED'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE venture_deal_kind_enum AS ENUM ('VENTURE_SALE', 'CO_VENTURE');
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE venture_deal_status_enum AS ENUM (
                'PENDING_PAYMENT', 'PAYMENT_HELD', 'IN_PROGRESS', 'COMPLETED',
                'CANCELLED', 'REFUNDED'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE venture_deal_event_type_enum AS ENUM (
                'CREATED', 'PAYMENT_INITIATED', 'PAYMENT_RECEIVED', 'ESCROW_RELEASED',
                'DEAL_COMPLETED', 'DEAL_CANCELLED', 'ADMIN_NOTE'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )

    op.execute(
        "ALTER TYPE venture_acquisition_application_status_enum "
        "ADD VALUE IF NOT EXISTS 'SHORTLISTED'"
    )
    op.execute(
        "ALTER TYPE venture_acquisition_application_status_enum "
        "ADD VALUE IF NOT EXISTS 'DEAL_SELECTED'"
    )

    op.add_column(
        "ventures",
        sa.Column(
            "listing_mode",
            postgresql.ENUM(
                "VENTURE",
                "CO_VENTURE",
                name="venture_listing_mode_enum",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "ventures",
        sa.Column(
            "venture_listing_status",
            postgresql.ENUM(
                "ACTIVE",
                "CLOSED",
                "DEAL_FINALIZED",
                "COMPLETED",
                name="venture_listing_status_enum",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column("ventures", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ventures", sa.Column("closed_by_user_id", sa.UUID(), nullable=True))
    op.add_column("ventures", sa.Column("selected_pitch_id", sa.UUID(), nullable=True))
    op.add_column("ventures", sa.Column("selected_coventure_id", sa.UUID(), nullable=True))

    op.execute(
        """
        UPDATE ventures SET listing_mode = 'VENTURE'
        WHERE sale_type = 'REGULAR' OR sale_type IS NULL
        """
    )
    op.execute(
        """
        UPDATE ventures SET listing_mode = 'CO_VENTURE'
        WHERE listing_mode IS NULL AND id IN (
            SELECT DISTINCT venture_id FROM venture_roles
        )
        """
    )
    op.execute(
        """
        UPDATE ventures SET listing_mode = 'VENTURE' WHERE listing_mode IS NULL
        """
    )
    op.execute(
        """
        UPDATE ventures SET venture_listing_status = 'ACTIVE'
        WHERE venture_listing_status IS NULL
        """
    )
    op.execute(
        """
        UPDATE ventures SET status = false, venture_listing_status = 'CLOSED'
        WHERE sale_type = 'AUCTION'
        """
    )

    op.alter_column("ventures", "listing_mode", nullable=False)
    op.alter_column("ventures", "venture_listing_status", nullable=False)

    op.create_foreign_key(
        "fk_ventures_closed_by_user",
        "ventures",
        "users",
        ["closed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_ventures_selected_pitch",
        "ventures",
        "venture_acquisition_applications",
        ["selected_pitch_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_ventures_selected_coventure",
        "ventures",
        "co_ventures",
        ["selected_coventure_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "venture_acquisition_applications",
        sa.Column("investment_proposal", sa.Text(), nullable=True),
    )
    op.add_column(
        "venture_acquisition_applications",
        sa.Column("additional_notes", sa.Text(), nullable=True),
    )

    op.add_column("co_ventures", sa.Column("experience_summary", sa.Text(), nullable=True))
    op.add_column("co_ventures", sa.Column("portfolio_url", sa.String(512), nullable=True))
    op.add_column("co_ventures", sa.Column("linkedin_url", sa.String(512), nullable=True))
    op.add_column("co_ventures", sa.Column("skills", sa.Text(), nullable=True))
    op.add_column("co_ventures", sa.Column("previous_ventures", sa.Text(), nullable=True))
    op.add_column("co_ventures", sa.Column("resume_url", sa.String(1024), nullable=True))
    op.add_column("co_ventures", sa.Column("motivation", sa.Text(), nullable=True))
    op.add_column("co_ventures", sa.Column("relevant_experience", sa.Text(), nullable=True))
    op.add_column("co_ventures", sa.Column("contribution_plan", sa.Text(), nullable=True))

    op.create_table(
        "venture_financial_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("venture_id", sa.UUID(), nullable=False),
        sa.Column("registration_number", sa.String(128), nullable=True),
        sa.Column("company_type", sa.String(64), nullable=True),
        sa.Column("market_cap_inr", sa.BigInteger(), nullable=True),
        sa.Column("current_revenue_inr", sa.BigInteger(), nullable=True),
        sa.Column("profitability_status", sa.String(64), nullable=True),
        sa.Column("profitability_amount_inr", sa.BigInteger(), nullable=True),
        sa.Column("funding_info", sa.Text(), nullable=True),
        sa.Column("desired_investment_inr", sa.BigInteger(), nullable=True),
        sa.Column("desired_valuation_inr", sa.BigInteger(), nullable=True),
        sa.Column("minimum_acceptable_offer_inr", sa.BigInteger(), nullable=True),
        sa.Column("team_size", sa.BigInteger(), nullable=True),
        sa.Column("traction_metrics", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["venture_id"], ["ventures.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("venture_id"),
    )

    op.create_table(
        "venture_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("venture_id", sa.UUID(), nullable=False),
        sa.Column("document_type", sa.String(64), nullable=False),
        sa.Column("file_url", sa.String(1024), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["venture_id"], ["ventures.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_venture_documents_venture_id", "venture_documents", ["venture_id"])

    op.create_table(
        "venture_deal_transactions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("venture_id", sa.UUID(), nullable=False),
        sa.Column("buyer_id", sa.UUID(), nullable=False),
        sa.Column("seller_id", sa.UUID(), nullable=False),
        sa.Column("pitch_id", sa.UUID(), nullable=True),
        sa.Column("co_venture_application_id", sa.UUID(), nullable=True),
        sa.Column(
            "deal_kind",
            postgresql.ENUM(
                "VENTURE_SALE",
                "CO_VENTURE",
                name="venture_deal_kind_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "deal_status",
            postgresql.ENUM(
                "PENDING_PAYMENT",
                "PAYMENT_HELD",
                "IN_PROGRESS",
                "COMPLETED",
                "CANCELLED",
                "REFUNDED",
                name="venture_deal_status_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "escrow_status",
            postgresql.ENUM(
                "HELD",
                "RELEASED",
                "REFUNDED",
                name="marketplace_escrow_status_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("gross_amount_inr", sa.Float(), nullable=False),
        sa.Column("platform_fee_inr", sa.Float(), nullable=False),
        sa.Column("seller_payout_inr", sa.Float(), nullable=False),
        sa.Column("equity_percent", sa.Float(), nullable=True),
        sa.Column("razorpay_order_id", sa.String(128), nullable=True),
        sa.Column("razorpay_payment_id", sa.String(128), nullable=True),
        sa.Column("razorpay_refund_id", sa.String(128), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["buyer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["co_venture_application_id"], ["co_ventures.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pitch_id"], ["venture_acquisition_applications.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["seller_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["venture_id"], ["ventures.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("razorpay_payment_id"),
    )
    op.create_index("idx_vdt_seller_status", "venture_deal_transactions", ["seller_id", "deal_status"])
    op.create_index("idx_vdt_buyer_status", "venture_deal_transactions", ["buyer_id", "deal_status"])
    op.create_index("idx_vdt_venture", "venture_deal_transactions", ["venture_id"])

    op.create_table(
        "venture_deal_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column(
            "event_type",
            postgresql.ENUM(
                "CREATED",
                "PAYMENT_INITIATED",
                "PAYMENT_RECEIVED",
                "ESCROW_RELEASED",
                "DEAL_COMPLETED",
                "DEAL_CANCELLED",
                "ADMIN_NOTE",
                name="venture_deal_event_type_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.String(4096), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["transaction_id"], ["venture_deal_transactions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_vde_transaction", "venture_deal_events", ["transaction_id"])

    op.execute(
        """
        UPDATE venture_auctions SET status = 'CANCELLED'
        WHERE status IN ('ACTIVE', 'DRAFT', 'EXTENDED', 'ENDED', 'PAYMENT_PENDING')
        """
    )


def downgrade() -> None:
    op.drop_index("idx_vde_transaction", table_name="venture_deal_events")
    op.drop_table("venture_deal_events")
    op.drop_index("idx_vdt_venture", table_name="venture_deal_transactions")
    op.drop_index("idx_vdt_buyer_status", table_name="venture_deal_transactions")
    op.drop_index("idx_vdt_seller_status", table_name="venture_deal_transactions")
    op.drop_table("venture_deal_transactions")
    op.drop_index("idx_venture_documents_venture_id", table_name="venture_documents")
    op.drop_table("venture_documents")
    op.drop_table("venture_financial_profiles")

    for col in (
        "contribution_plan",
        "relevant_experience",
        "motivation",
        "resume_url",
        "previous_ventures",
        "skills",
        "linkedin_url",
        "portfolio_url",
        "experience_summary",
    ):
        op.drop_column("co_ventures", col)

    op.drop_column("venture_acquisition_applications", "additional_notes")
    op.drop_column("venture_acquisition_applications", "investment_proposal")

    op.drop_constraint("fk_ventures_selected_coventure", "ventures", type_="foreignkey")
    op.drop_constraint("fk_ventures_selected_pitch", "ventures", type_="foreignkey")
    op.drop_constraint("fk_ventures_closed_by_user", "ventures", type_="foreignkey")
    op.drop_column("ventures", "selected_coventure_id")
    op.drop_column("ventures", "selected_pitch_id")
    op.drop_column("ventures", "closed_by_user_id")
    op.drop_column("ventures", "closed_at")
    op.drop_column("ventures", "venture_listing_status")
    op.drop_column("ventures", "listing_mode")

    op.execute("DROP TYPE IF EXISTS venture_deal_event_type_enum")
    op.execute("DROP TYPE IF EXISTS venture_deal_status_enum")
    op.execute("DROP TYPE IF EXISTS venture_deal_kind_enum")
    op.execute("DROP TYPE IF EXISTS venture_listing_status_enum")
    op.execute("DROP TYPE IF EXISTS venture_listing_mode_enum")
