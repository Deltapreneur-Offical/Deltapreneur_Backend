"""community profile expected rate (numeric)

Revision ID: a4b5c6d7e8f9
Revises: e8f9a0b1c2d3
Create Date: 2026-06-10 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, Sequence[str], None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("community")}
    if "expected_rate" not in columns:
        op.add_column(
            "community",
            sa.Column("expected_rate", sa.Numeric(12, 2), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("community")}
    if "expected_rate" in columns:
        op.drop_column("community", "expected_rate")
