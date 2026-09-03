"""add service_type to operations_services

Revision ID: p2q3r4s5t6u7
Revises: o1p2q3r4s5t6
Create Date: 2026-06-12 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p2q3r4s5t6u7"
down_revision: Union[str, Sequence[str], None] = "o1p2q3r4s5t6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "operations_services",
        sa.Column(
            "service_type",
            sa.String(length=32),
            nullable=False,
            server_default="virtual_assistance",
        ),
    )
    op.create_index(
        "idx_operations_services_service_type",
        "operations_services",
        ["service_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_operations_services_service_type", table_name="operations_services")
    op.drop_column("operations_services", "service_type")
