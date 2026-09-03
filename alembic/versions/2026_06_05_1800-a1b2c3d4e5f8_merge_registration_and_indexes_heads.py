"""Merge domain registration follow-up and listing/auction index heads.

Revision ID: a1b2c3d4e5f8
Revises: c2d3e4f5a6b7, f2a3b4c5d6e7
Create Date: 2026-06-05 18:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5f8"
down_revision: Union[str, Sequence[str], None] = ("c2d3e4f5a6b7", "f2a3b4c5d6e7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
