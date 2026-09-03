"""Add government fee fields to operations_services.

Revision ID: hubreg003
Revises: hubreg002
Create Date: 2026-08-21 13:00:00.000000

SAFETY: additive only - adds two columns with safe defaults.
Existing rows receive government_fees_applicable=false and
government_fee_text='Government fees applicable'. No data modified.
downgrade() drops only these two columns.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "hubreg003"
down_revision: Union[str, Sequence[str], None] = "hubreg002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "operations_services",
        sa.Column(
            "government_fees_applicable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "operations_services",
        sa.Column(
            "government_fee_text",
            sa.String(length=255),
            nullable=False,
            server_default="Government fees applicable",
        ),
    )


def downgrade() -> None:
    op.drop_column("operations_services", "government_fee_text")
    op.drop_column("operations_services", "government_fees_applicable")
