"""add contact_status to operations_service_requests

Revision ID: ops_req_contact_status_001
Revises: a1c7f4e9d2b8
Create Date: 2026-09-07 17:00:00.000000

OperationsServiceRequest maps contact_status, but no Alembic revision ever
added the column. Production SELECTs then fail with UndefinedColumnError and
GET /api/v1/admin/operations-requests returns 500.

Additive and idempotent: add the missing NOT NULL column with a server default
so existing rows become CONTACT_PENDING. Does not drop or rewrite data.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ops_req_contact_status_001"
down_revision: Union[str, Sequence[str], None] = "a1c7f4e9d2b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "operations_service_requests"
COLUMN = "contact_status"


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
        sa.Column(
            COLUMN,
            sa.String(32),
            nullable=False,
            server_default="CONTACT_PENDING",
        ),
    )


def downgrade() -> None:
    columns = _existing_columns()
    if COLUMN in columns:
        op.drop_column(TABLE, COLUMN)
