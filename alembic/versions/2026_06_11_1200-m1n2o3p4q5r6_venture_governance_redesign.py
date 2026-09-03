"""Venture governance redesign — acquisition applications, auction seller outcome.

Revision ID: m1n2o3p4q5r6
Revises: l1m2n3o4p5q6
Create Date: 2026-06-11 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "m1n2o3p4q5r6"
down_revision: Union[str, Sequence[str], None] = "l1m2n3o4p5q6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE venture_deal_type_enum AS ENUM (
                'FULL_ACQUISITION', 'EQUITY_SALE'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE venture_acquisition_application_status_enum AS ENUM (
                'PENDING', 'SELLER_ACCEPTED', 'SELLER_REJECTED', 'CANCELLED', 'COMPLETED'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE venture_acquisition_application_source_enum AS ENUM (
                'REGULAR_APPLY', 'AUCTION_WINNER'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE venture_auction_seller_outcome_enum AS ENUM (
                'PENDING', 'ACCEPTED', 'REJECTED'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )

    op.add_column(
        "ventures",
        sa.Column(
            "deal_type",
            postgresql.ENUM(
                "FULL_ACQUISITION",
                "EQUITY_SALE",
                name="venture_deal_type_enum",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column("ventures", sa.Column("equity_percent_offered", sa.Float(), nullable=True))
    op.add_column("ventures", sa.Column("valuation_amount", sa.BigInteger(), nullable=True))
    op.add_column("ventures", sa.Column("commission_percent_applied", sa.Float(), nullable=True))

    op.add_column(
        "venture_auctions",
        sa.Column(
            "seller_outcome",
            postgresql.ENUM(
                "PENDING",
                "ACCEPTED",
                "REJECTED",
                name="venture_auction_seller_outcome_enum",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "venture_auctions",
        sa.Column("seller_decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "venture_auctions",
        sa.Column("seller_decision_by_user_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_venture_auctions_seller_decision_by",
        "venture_auctions",
        "users",
        ["seller_decision_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "venture_acquisition_applications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("venture_id", sa.UUID(), nullable=False),
        sa.Column("buyer_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "PENDING",
                "SELLER_ACCEPTED",
                "SELLER_REJECTED",
                "CANCELLED",
                "COMPLETED",
                name="venture_acquisition_application_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "source",
            postgresql.ENUM(
                "REGULAR_APPLY",
                "AUCTION_WINNER",
                name="venture_acquisition_application_source_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="REGULAR_APPLY",
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("offer_amount", sa.Float(), nullable=True),
        sa.Column("equity_percent_sought", sa.Float(), nullable=True),
        sa.Column("venture_auction_id", sa.UUID(), nullable=True),
        sa.Column("winning_bid_id", sa.UUID(), nullable=True),
        sa.Column("seller_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_completed_by_user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["admin_completed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["buyer_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["venture_auction_id"], ["venture_auctions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["venture_id"], ["ventures.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["winning_bid_id"], ["venture_auction_bids.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("venture_id", "buyer_user_id", name="uq_vaa_venture_buyer"),
    )
    op.create_index("idx_vaa_venture_id", "venture_acquisition_applications", ["venture_id"])
    op.create_index("idx_vaa_buyer_user_id", "venture_acquisition_applications", ["buyer_user_id"])
    op.create_index("idx_vaa_status", "venture_acquisition_applications", ["status"])

    op.execute(
        """
        UPDATE venture_auctions
        SET approval_status = 'PENDING_APPROVAL'
        WHERE approval_status = 'AWAITING_GSTIN'
        """
    )


def downgrade() -> None:
    op.drop_index("idx_vaa_status", table_name="venture_acquisition_applications")
    op.drop_index("idx_vaa_buyer_user_id", table_name="venture_acquisition_applications")
    op.drop_index("idx_vaa_venture_id", table_name="venture_acquisition_applications")
    op.drop_table("venture_acquisition_applications")

    op.drop_constraint("fk_venture_auctions_seller_decision_by", "venture_auctions", type_="foreignkey")
    op.drop_column("venture_auctions", "seller_decision_by_user_id")
    op.drop_column("venture_auctions", "seller_decided_at")
    op.drop_column("venture_auctions", "seller_outcome")

    op.drop_column("ventures", "commission_percent_applied")
    op.drop_column("ventures", "valuation_amount")
    op.drop_column("ventures", "equity_percent_offered")
    op.drop_column("ventures", "deal_type")

    op.execute("DROP TYPE IF EXISTS venture_auction_seller_outcome_enum")
    op.execute("DROP TYPE IF EXISTS venture_acquisition_application_source_enum")
    op.execute("DROP TYPE IF EXISTS venture_acquisition_application_status_enum")
    op.execute("DROP TYPE IF EXISTS venture_deal_type_enum")
