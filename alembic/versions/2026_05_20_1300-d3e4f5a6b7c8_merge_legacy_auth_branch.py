"""merge legacy auth branch back into current head

Revision ID: d3e4f5a6b7c8
Revises: c4e8f1a2b3d6, a2b3c4d5e6f7
Create Date: 2026-05-20 13:00:00.000000
"""

from typing import Sequence, Union


revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, Sequence[str], None] = (
    "c4e8f1a2b3d6",
    "a2b3c4d5e6f7",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
