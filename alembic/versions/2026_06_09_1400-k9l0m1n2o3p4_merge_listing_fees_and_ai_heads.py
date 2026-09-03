"""Merge listing-fees branch and cobrother-ai branch heads.

Revision ID: k9l0m1n2o3p4
Revises: j1k2l3m4n5o6, a9b8c7d6e5f4
Create Date: 2026-06-09 14:00:00
"""

from typing import Sequence, Union

revision: str = "k9l0m1n2o3p4"
down_revision: Union[str, Sequence[str], None] = ("j1k2l3m4n5o6", "a9b8c7d6e5f4")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
