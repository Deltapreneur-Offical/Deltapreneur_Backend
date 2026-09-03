"""merge analytics and auction migration heads

Revision ID: c7d8e9f0a123
Revises: 0bc2e7fda635, b2c3d4e5f601
Create Date: 2026-05-16 18:25:00.000000
"""

from typing import Sequence, Union


revision: str = "c7d8e9f0a123"
down_revision: Union[str, Sequence[str], None] = (
    "0bc2e7fda635",
    "b2c3d4e5f601",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
