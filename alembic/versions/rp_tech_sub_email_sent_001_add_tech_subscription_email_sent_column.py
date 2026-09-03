"""add_tech_subscription_email_sent_column

Revision ID: rp_tech_sub_email_sent_001
Revises: rp_seed_provider_keys_001
Create Date: 2026-08-13 12:20:00.000000

Add email_sent tracking column to technology_subscriptions for
idempotent technology purchase notification emails.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "rp_tech_sub_email_sent_001"
down_revision: Union[str, Sequence[str], None] = "rp_seed_provider_keys_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "technology_subscriptions",
        sa.Column("email_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("technology_subscriptions", "email_sent")
