"""create analytics view tables (no-op: tables created in a4606a3fab70 + b1d2c3e4f5a6)

Revision ID: 0bc2e7fda635
Revises: b1d2c3e4f5a6
Create Date: 2026-05-14 14:31:09.922366

This revision originally duplicated ``venture_views`` and ``profile_views``.
Those tables are created by ``a4606a3fab70`` and ``b1d2c3e4f5a6``; this file
remains only to preserve the revision chain for environments that already
referenced it.
"""
from typing import Sequence, Union


revision: str = "0bc2e7fda635"
down_revision: Union[str, Sequence[str], None] = "b1d2c3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op: analytics view tables are created in earlier revisions."""
    pass


def downgrade() -> None:
    """No-op: do not drop tables owned by a4606a3fab70 / b1d2c3e4f5a6."""
    pass
