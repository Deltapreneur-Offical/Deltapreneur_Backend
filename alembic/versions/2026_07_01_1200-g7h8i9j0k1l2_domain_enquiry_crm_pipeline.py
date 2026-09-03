"""Add domain enquiry admin notes and status timestamps.

Revision ID: g7h8i9j0k1l2
Revises: c17c0e9165b5
Create Date: 2026-07-01 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, Sequence[str], None] = "c17c0e9165b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "domain_enquiries"

COLUMNS: list[tuple[str, sa.Column]] = [
    ("admin_notes", sa.Column("admin_notes", sa.Text(), nullable=True)),
    ("in_progress_at", sa.Column("in_progress_at", sa.DateTime(timezone=True), nullable=True)),
    ("completed_at", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)),
    ("declined_at", sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True)),
]


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    for column_name, column in COLUMNS:
        if not _column_exists(TABLE, column_name):
            op.add_column(TABLE, column)


def downgrade() -> None:
    for column_name, _ in reversed(COLUMNS):
        if _column_exists(TABLE, column_name):
            op.drop_column(TABLE, column_name)
