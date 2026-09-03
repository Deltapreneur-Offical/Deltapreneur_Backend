"""create auction tables

Adds domains registry + auction module: auctions, bids, payments, transactions.

Revision ID: a1f4d8c9b201
Revises: 07803b6e2462
Create Date: 2026-05-12 14:10:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1f4d8c9b201"
down_revision: Union[str, Sequence[str], None] = "07803b6e2462"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_AUCTION_STATUS_VALUES = (
    "DRAFT",
    "ACTIVE",
    "EXTENDED",
    "ENDED",
    "UNSOLD",
    "CANCELLED",
    "PAYMENT_PENDING",
    "COMPLETED",
)

_AUCTION_DURATION_VALUES = (
    "ONE_HOUR",
    "SIX_HOURS",
    "TWELVE_HOURS",
    "ONE_DAY",
    "THREE_DAYS",
    "SEVEN_DAYS",
)

_PAYMENT_STATUS_VALUES = ("PENDING", "SUCCESS", "FAILED", "REFUNDED")

_TRANSACTION_STATUS_VALUES = ("INITIATED", "SUCCESS", "FAILED", "VERIFIED")

auction_status_enum = postgresql.ENUM(
    *_AUCTION_STATUS_VALUES, name="auction_status_enum", create_type=False,
)
auction_duration_enum = postgresql.ENUM(
    *_AUCTION_DURATION_VALUES, name="auction_duration_enum", create_type=False,
)
payment_status_enum = postgresql.ENUM(
    *_PAYMENT_STATUS_VALUES, name="payment_status_enum", create_type=False,
)
transaction_status_enum = postgresql.ENUM(
    *_TRANSACTION_STATUS_VALUES, name="transaction_status_enum", create_type=False,
)


def _soft_delete_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
    ]


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    try:
        return {idx["name"] for idx in inspector.get_indexes(table_name)}
    except sa.exc.NoSuchTableError:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    auction_status_enum.create(bind, checkfirst=True)
    auction_duration_enum.create(bind, checkfirst=True)
    payment_status_enum.create(bind, checkfirst=True)
    transaction_status_enum.create(bind, checkfirst=True)

    if "domains" in existing_tables:
        pass
    else:
        op.create_table(
        "domains",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        *_soft_delete_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_domains"),
        )
        if "idx_domains_owner_user_id" not in _index_names(inspector, "domains"):
            op.create_index("idx_domains_owner_user_id", "domains", ["owner_user_id"])

    if "auctions" not in existing_tables:
        op.create_table(
        "auctions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "domain_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "status",
            auction_status_enum,
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column("duration", auction_duration_enum, nullable=False),
        sa.Column("min_bid_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("current_highest_bid", sa.Numeric(18, 2), nullable=True),
        sa.Column(
            "total_bids",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "current_winner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "original_end_time",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        *_soft_delete_columns(),
        sa.ForeignKeyConstraint(
            ["domain_id"],
            ["domains.id"],
            name="auctions_domain_id_fkey",
            ondelete="RESTRICT",
        ),
        )
        auction_indexes = (
            ("idx_auction_status_end_time", ["status", "end_time"]),
            ("idx_auction_domain_id", ["domain_id"]),
            ("idx_auction_created_by", ["created_by"]),
            ("ix_auctions_status", ["status"]),
            ("ix_auctions_end_time", ["end_time"]),
            ("ix_auctions_current_winner_id", ["current_winner_id"]),
        )
        auction_idx_existing = _index_names(inspector, "auctions")
        for index_name, columns in auction_indexes:
            if index_name not in auction_idx_existing:
                op.create_index(index_name, "auctions", columns)

    if "bids" not in existing_tables:
        op.create_table(
        "bids",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "auction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("auctions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "bidder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("bidder_name", sa.String(length=255), nullable=False),
        sa.Column(
            "is_winning_bid",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        *_soft_delete_columns(),
        )
        bid_indexes = (
            ("idx_bid_auction_created_at", ["auction_id", "created_at"]),
            ("idx_bid_auction_amount", ["auction_id", "amount"]),
            ("idx_bid_bidder_id", ["bidder_id"]),
            ("ix_bids_created_at", ["created_at"]),
        )
        bid_idx_existing = _index_names(inspector, "bids")
        for index_name, columns in bid_indexes:
            if index_name not in bid_idx_existing:
                op.create_index(index_name, "bids", columns)

    if "payments" not in existing_tables:
        op.create_table(
        "payments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "auction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("auctions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "razorpay_order_id",
            sa.String(length=255),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "payment_status",
            payment_status_enum,
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        *_soft_delete_columns(),
        )
        payment_indexes = (
            ("idx_payment_auction_id", ["auction_id"]),
            ("idx_payment_user_id", ["user_id"]),
            ("idx_payment_status", ["payment_status"]),
            ("ix_payments_razorpay_order_id", ["razorpay_order_id"]),
        )
        payment_idx_existing = _index_names(inspector, "payments")
        for index_name, columns in payment_indexes:
            if index_name not in payment_idx_existing:
                op.create_index(index_name, "payments", columns)

    if "transactions" not in existing_tables:
        op.create_table(
        "transactions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "payment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "transaction_reference", sa.String(length=255), nullable=True,
        ),
        sa.Column(
            "gateway_response",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "transaction_status",
            transaction_status_enum,
            nullable=False,
            server_default=sa.text("'INITIATED'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        *_soft_delete_columns(),
        )
        transaction_indexes = (
            ("idx_transaction_payment_id", ["payment_id"]),
            ("idx_transaction_status", ["transaction_status"]),
            ("ix_transactions_transaction_reference", ["transaction_reference"]),
        )
        txn_idx_existing = _index_names(inspector, "transactions")
        for index_name, columns in transaction_indexes:
            if index_name not in txn_idx_existing:
                op.create_index(index_name, "transactions", columns)


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index("ix_transactions_transaction_reference", table_name="transactions")
    op.drop_index("idx_transaction_status", table_name="transactions")
    op.drop_index("idx_transaction_payment_id", table_name="transactions")
    op.drop_table("transactions")

    op.drop_index("ix_payments_razorpay_order_id", table_name="payments")
    op.drop_index("idx_payment_status", table_name="payments")
    op.drop_index("idx_payment_user_id", table_name="payments")
    op.drop_index("idx_payment_auction_id", table_name="payments")
    op.drop_table("payments")

    op.drop_index("ix_bids_created_at", table_name="bids")
    op.drop_index("idx_bid_bidder_id", table_name="bids")
    op.drop_index("idx_bid_auction_amount", table_name="bids")
    op.drop_index("idx_bid_auction_created_at", table_name="bids")
    op.drop_table("bids")

    op.drop_index("ix_auctions_current_winner_id", table_name="auctions")
    op.drop_index("ix_auctions_end_time", table_name="auctions")
    op.drop_index("ix_auctions_status", table_name="auctions")
    op.drop_index("idx_auction_created_by", table_name="auctions")
    op.drop_index("idx_auction_domain_id", table_name="auctions")
    op.drop_index("idx_auction_status_end_time", table_name="auctions")
    op.drop_table("auctions")

    op.drop_index("idx_domains_owner_user_id", table_name="domains")
    op.drop_table("domains")

    transaction_status_enum.drop(bind, checkfirst=True)
    payment_status_enum.drop(bind, checkfirst=True)
    auction_duration_enum.drop(bind, checkfirst=True)
    auction_status_enum.drop(bind, checkfirst=True)
