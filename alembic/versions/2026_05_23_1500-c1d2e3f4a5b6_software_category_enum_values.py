"""Extend software_category_enum for UI categories

Revision ID: c1d2e3f4a5b6
Revises: b9c0d1e2f3a4
Create Date: 2026-05-23 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_CATEGORY_VALUES = (
    "DESKTOP",
    "API_TOOL",
    "AUTOMATION",
    "ECOMMERCE",
    "EDUCATION",
)


def upgrade() -> None:
    for value in _NEW_CATEGORY_VALUES:
        op.execute(
            f"ALTER TYPE software_category_enum ADD VALUE IF NOT EXISTS '{value}'"
        )


def downgrade() -> None:
    # PostgreSQL cannot remove enum values safely; no-op.
    pass
