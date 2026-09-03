"""Phase 1 seller payout profile fields and reminder event.

Revision ID: p5q6r7s8t9u0
Revises: o4p5q6r7s8t9
Create Date: 2026-06-11 17:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "p5q6r7s8t9u0"
down_revision: Union[str, Sequence[str], None] = "o4p5q6r7s8t9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("seller_payout_profiles", sa.Column("bank_name", sa.String(length=255), nullable=True))
    op.alter_column("seller_payout_profiles", "account_holder_name", existing_type=sa.String(length=255), nullable=True)
    op.execute("ALTER TYPE transfer_event_type_enum ADD VALUE IF NOT EXISTS 'PAYOUT_REMINDER_SENT'")


def downgrade() -> None:
    op.drop_column("seller_payout_profiles", "bank_name")
