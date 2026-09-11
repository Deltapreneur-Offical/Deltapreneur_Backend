"""add access_email_sent to technology_subscriptions

Revision ID: tech_access_email_sent_001
Revises: ops_req_contact_status_001
Create Date: 2026-09-11 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "tech_access_email_sent_001"
down_revision: Union[str, Sequence[str], None] = "ops_req_contact_status_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "technology_subscriptions",
        sa.Column("access_email_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("technology_subscriptions", "access_email_sent")
