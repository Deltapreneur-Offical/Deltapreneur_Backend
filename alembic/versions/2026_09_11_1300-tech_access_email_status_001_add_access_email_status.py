"""add access_email_status to technology_subscriptions

Revision ID: tech_access_email_status_001
Revises: tech_sub_access_email_sent_001
Create Date: 2026-09-11 13:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "tech_access_email_status_001"
down_revision: Union[str, Sequence[str], None] = "tech_sub_access_email_sent_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "technology_subscriptions"
COLUMN = "access_email_status"


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return set()
    return {col["name"] for col in inspector.get_columns(TABLE)}


def upgrade() -> None:
    columns = _existing_columns()
    if not columns:
        return
    if COLUMN not in columns:
        op.add_column(
            TABLE,
            sa.Column(
                COLUMN,
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'PENDING'"),
            ),
        )
    if "access_email_sent" in _existing_columns():
        op.execute(
            "UPDATE technology_subscriptions "
            "SET access_email_status = 'SENT' "
            "WHERE access_email_sent IS TRUE"
        )


def downgrade() -> None:
    columns = _existing_columns()
    if COLUMN in columns:
        op.drop_column(TABLE, COLUMN)
