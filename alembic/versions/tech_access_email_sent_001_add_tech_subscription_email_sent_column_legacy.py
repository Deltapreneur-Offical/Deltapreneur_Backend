"""legacy technology subscription email_sent revision compatibility shim.

Revision ID: tech_access_email_sent_001
Revises: rp_seed_provider_keys_001
Create Date: 2026-08-13 12:20:00.000000

Render production still references this historical revision id in some
databases. Keep an idempotent copy in the graph so those databases can upgrade
forward to the current head without manual stamping.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "tech_access_email_sent_001"
down_revision: Union[str, Sequence[str], None] = "rp_seed_provider_keys_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("technology_subscriptions")}
    if "email_sent" not in cols:
        op.add_column(
            "technology_subscriptions",
            sa.Column("email_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("technology_subscriptions")}
    if "email_sent" in cols:
        op.drop_column("technology_subscriptions", "email_sent")
