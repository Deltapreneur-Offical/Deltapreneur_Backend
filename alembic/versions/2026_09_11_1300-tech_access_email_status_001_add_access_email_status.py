"""add access_email_status to technology_subscriptions

Revision ID: tech_access_email_status_001
Revises: tech_access_email_sent_001
Create Date: 2026-09-11 13:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "tech_access_email_status_001"
down_revision: Union[str, Sequence[str], None] = "tech_access_email_sent_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "technology_subscriptions",
        sa.Column(
            "access_email_status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
    )
    op.execute(
        "UPDATE technology_subscriptions "
        "SET access_email_status = 'SENT' "
        "WHERE access_email_sent IS TRUE"
    )


def downgrade() -> None:
    op.drop_column("technology_subscriptions", "access_email_status")
