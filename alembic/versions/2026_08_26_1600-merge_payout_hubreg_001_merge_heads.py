"""Merge the dp_snapshot_payout_001 and hubreg005 heads.

No schema changes — this revision only joins the two parallel branches
(seller payout snapshot on main, Hub Registrar migrations) into a single
Alembic head so deploy tooling sees exactly one head.

Revision ID: merge_payout_hubreg_001
Revises: dp_snapshot_payout_001, hubreg005
Create Date: 2026-08-26 16:00:00.000000

SAFETY: no-op — creates/alters/drops nothing.
"""
from typing import Sequence, Union

revision: str = "merge_payout_hubreg_001"
down_revision: Union[str, Sequence[str], None] = ("dp_snapshot_payout_001", "hubreg005")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
