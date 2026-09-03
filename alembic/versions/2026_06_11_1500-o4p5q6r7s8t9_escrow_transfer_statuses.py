"""Add escrow transfer workflow statuses.

Revision ID: o4p5q6r7s8t9
Revises: n3o4p5q6r7s8
Create Date: 2026-06-11 15:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "o4p5q6r7s8t9"
down_revision: Union[str, Sequence[str], None] = "n3o4p5q6r7s8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE marketplace_transfer_status_enum ADD VALUE IF NOT EXISTS 'AUTH_CODE_AVAILABLE'")
    op.execute("ALTER TYPE marketplace_transfer_status_enum ADD VALUE IF NOT EXISTS 'PAYOUT_APPROVED'")
    op.execute("ALTER TYPE marketplace_transfer_status_enum ADD VALUE IF NOT EXISTS 'PAYOUT_RELEASED'")
    op.execute("ALTER TYPE marketplace_transfer_status_enum ADD VALUE IF NOT EXISTS 'COMPLETED'")
    op.execute("ALTER TYPE transfer_event_type_enum ADD VALUE IF NOT EXISTS 'PAYOUT_APPROVED'")


def downgrade() -> None:
    pass
