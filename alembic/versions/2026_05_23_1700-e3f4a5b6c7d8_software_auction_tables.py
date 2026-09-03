"""Software auction tables and purchase_type AUCTION

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-05-23 17:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE software_purchase_type_enum ADD VALUE IF NOT EXISTS 'AUCTION'"
    )

    software_auction_duration = postgresql.ENUM(
        "ONE_DAY",
        "THREE_DAYS",
        "FIVE_DAYS",
        "SEVEN_DAYS",
        "FOURTEEN_DAYS",
        "THIRTY_DAYS",
        name="software_auction_duration_enum",
        create_type=False,
    )
    software_auction_approval = postgresql.ENUM(
        "PENDING_APPROVAL",
        "APPROVED",
        "REJECTED",
        name="software_auction_approval_status_enum",
        create_type=False,
    )

    bind = op.get_bind()
    postgresql.ENUM(
        "ONE_DAY",
        "THREE_DAYS",
        "FIVE_DAYS",
        "SEVEN_DAYS",
        "FOURTEEN_DAYS",
        "THIRTY_DAYS",
        name="software_auction_duration_enum",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "PENDING_APPROVAL",
        "APPROVED",
        "REJECTED",
        name="software_auction_approval_status_enum",
    ).create(bind, checkfirst=True)

    auction_status = postgresql.ENUM(name="auction_status_enum", create_type=False)

    if "software_auctions" in inspect(op.get_bind()).get_table_names():
        return

    op.create_table(
        "software_auctions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("software_id", sa.UUID(), nullable=False),
        sa.Column("status", auction_status, nullable=False),
        sa.Column("approval_status", software_auction_approval, nullable=False),
        sa.Column("duration", software_auction_duration, nullable=False),
        sa.Column("min_bid_price", sa.Float(), nullable=False),
        sa.Column("current_highest_bid", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_bids", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("auction_rationale", sa.Text(), nullable=True),
        sa.Column("source_code_included", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("support_included", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("support_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transfer_details", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("current_winner_id", sa.UUID(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("original_end_time", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["software_id"], ["software_listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_winner_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("software_id", name="uq_software_auctions_software_id"),
    )
    op.create_index("idx_software_auctions_status", "software_auctions", ["status"])
    op.create_index("idx_software_auctions_approval", "software_auctions", ["approval_status"])
    op.create_index("idx_software_auctions_end_time", "software_auctions", ["end_time"])

    op.create_table(
        "software_auction_bids",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("software_auction_id", sa.UUID(), nullable=False),
        sa.Column("bidder_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("bidder_name", sa.String(255), nullable=True),
        sa.Column("bid_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_winning_bid", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(
            ["software_auction_id"], ["software_auctions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["bidder_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_software_auction_bids_auction_id",
        "software_auction_bids",
        ["software_auction_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_software_auction_bids_auction_id", table_name="software_auction_bids")
    op.drop_table("software_auction_bids")
    op.drop_index("idx_software_auctions_end_time", table_name="software_auctions")
    op.drop_index("idx_software_auctions_approval", table_name="software_auctions")
    op.drop_index("idx_software_auctions_status", table_name="software_auctions")
    op.drop_table("software_auctions")
    op.execute("DROP TYPE IF EXISTS software_auction_approval_status_enum")
    op.execute("DROP TYPE IF EXISTS software_auction_duration_enum")
