"""Merge domain transfer head with restored legacy merge revision.

Revision ID: m2n3o4p5q6r7
Revises: l1m2n3o4p5q6, 4997a97074a7
Create Date: 2026-06-10 13:00:00
"""

from typing import Sequence, Union

revision: str = "m2n3o4p5q6r7"
down_revision: Union[str, Sequence[str], None] = ("l1m2n3o4p5q6", "4997a97074a7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
