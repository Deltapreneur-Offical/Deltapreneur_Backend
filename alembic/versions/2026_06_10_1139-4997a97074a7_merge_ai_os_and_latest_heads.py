"""Merge ai os and latest heads.

Revision ID: 4997a97074a7
Revises: a9b8c7d6e5f4, a1b2c3d4e5f8
Create Date: 2026-06-10 11:39:50.432798
"""

from typing import Sequence, Union

revision: str = "4997a97074a7"
down_revision: Union[str, Sequence[str], None] = ("a9b8c7d6e5f4", "a1b2c3d4e5f8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
