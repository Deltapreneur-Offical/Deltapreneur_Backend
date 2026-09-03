"""Add contacted_by tracking to operations_service_requests.

Revision ID: v2w3x4y5z6a7
Revises: u1v2w3x4y5z6
Create Date: 2026-06-13 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2w3x4y5z6a7"
down_revision: Union[str, Sequence[str], None] = "u1v2w3x4y5z6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "operations_service_requests",
        sa.Column("contacted_by_user_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "operations_service_requests",
        sa.Column("contacted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_operations_service_requests_contacted_by_user_id_users"),
        "operations_service_requests",
        "users",
        ["contacted_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_operations_service_requests_contacted_by_user_id"),
        "operations_service_requests",
        ["contacted_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_operations_service_requests_contacted_by_user_id"),
        table_name="operations_service_requests",
    )
    op.drop_constraint(
        op.f("fk_operations_service_requests_contacted_by_user_id_users"),
        "operations_service_requests",
        type_="foreignkey",
    )
    op.drop_column("operations_service_requests", "contacted_at")
    op.drop_column("operations_service_requests", "contacted_by_user_id")
