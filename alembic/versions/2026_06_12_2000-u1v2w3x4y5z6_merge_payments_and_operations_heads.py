"""Merge payments branch with operations/compliance branch.

Revision ID: u1v2w3x4y5z6
Revises: t9u0v1w2x3y4, r4s5t6u7v8w9
Create Date: 2026-06-12 20:00:00
"""

from typing import Sequence, Union

revision: str = "u1v2w3x4y5z6"
down_revision: Union[str, Sequence[str], None] = ("t9u0v1w2x3y4", "r4s5t6u7v8w9")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
