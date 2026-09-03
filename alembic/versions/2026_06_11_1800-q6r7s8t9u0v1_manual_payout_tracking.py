"""Manual payout tracking and reminder counters.

Revision ID: q6r7s8t9u0v1
Revises: p5q6r7s8t9u0
Create Date: 2026-06-11 18:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "q6r7s8t9u0v1"
down_revision: Union[str, Sequence[str], None] = "p5q6r7s8t9u0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE seller_payout_profiles "
        "ADD COLUMN IF NOT EXISTS is_complete BOOLEAN DEFAULT false NOT NULL"
    )
    op.add_column(
        "domain_marketplace_transactions",
        sa.Column("payout_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "domain_marketplace_transactions",
        sa.Column("payout_reminder_count", sa.SmallInteger(), server_default="0", nullable=False),
    )
    op.add_column(
        "seller_payouts",
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("seller_payouts", sa.Column("method_used", sa.String(length=32), nullable=True))
    op.add_column(
        "seller_payouts",
        sa.Column("reference_number", sa.String(length=128), nullable=True),
    )
    op.add_column("seller_payouts", sa.Column("notes", sa.String(length=1024), nullable=True))
    op.add_column(
        "seller_payouts",
        sa.Column("released_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "seller_payouts",
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_seller_payouts_seller_id_users",
        "seller_payouts",
        "users",
        ["seller_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_seller_payouts_released_by_users",
        "seller_payouts",
        "users",
        ["released_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_seller_payouts_released_by_users", "seller_payouts", type_="foreignkey")
    op.drop_constraint("fk_seller_payouts_seller_id_users", "seller_payouts", type_="foreignkey")
    op.drop_column("seller_payouts", "released_at")
    op.drop_column("seller_payouts", "released_by_user_id")
    op.drop_column("seller_payouts", "notes")
    op.drop_column("seller_payouts", "reference_number")
    op.drop_column("seller_payouts", "method_used")
    op.drop_column("seller_payouts", "seller_id")
    op.drop_column("domain_marketplace_transactions", "payout_reminder_count")
    op.drop_column("domain_marketplace_transactions", "payout_reminder_sent_at")
    op.drop_column("seller_payout_profiles", "is_complete")
