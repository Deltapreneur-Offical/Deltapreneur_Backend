"""add access_email_sent to technology_subscriptions

Revision ID: tech_sub_access_email_sent_001
Revises: ops_req_contact_status_001
Create Date: 2026-09-11 14:00:00.000000

Must not reuse the historical revision id ``tech_access_email_sent_001``,
which already exists as the legacy ``email_sent`` compatibility shim.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "tech_sub_access_email_sent_001"
down_revision: Union[str, Sequence[str], None] = "ops_req_contact_status_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "technology_subscriptions"
COLUMN = "access_email_sent"


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return set()
    return {col["name"] for col in inspector.get_columns(TABLE)}


def upgrade() -> None:
    columns = _existing_columns()
    if not columns or COLUMN in columns:
        return
    op.add_column(
        TABLE,
        sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    columns = _existing_columns()
    if COLUMN in columns:
        op.drop_column(TABLE, COLUMN)
