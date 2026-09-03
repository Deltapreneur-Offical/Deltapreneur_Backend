"""community profile expected rate text field

Revision ID: a1b2c3d4e5f9
Revises: a4b5c6d7e8f9
Create Date: 2026-06-10 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "a1b2c3d4e5f9"
down_revision: Union[str, Sequence[str], None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"]: col for col in inspector.get_columns("community")}

    if "rate_type" in columns:
        op.drop_column("community", "rate_type")

    if "expected_rate" not in columns:
        op.add_column(
            "community",
            sa.Column("expected_rate", sa.String(length=100), nullable=True),
        )
        return

    col_type = str(columns["expected_rate"]["type"]).upper()
    if "NUMERIC" in col_type or "DECIMAL" in col_type:
        op.alter_column(
            "community",
            "expected_rate",
            existing_type=sa.Numeric(12, 2),
            type_=sa.String(length=100),
            postgresql_using="expected_rate::text",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"]: col for col in inspector.get_columns("community")}

    if "expected_rate" not in columns:
        return

    col_type = str(columns["expected_rate"]["type"]).upper()
    if "VARCHAR" in col_type or "CHARACTER VARYING" in col_type:
        op.alter_column(
            "community",
            "expected_rate",
            existing_type=sa.String(length=100),
            type_=sa.Numeric(12, 2),
            postgresql_using="NULLIF(expected_rate, '')::numeric",
        )
