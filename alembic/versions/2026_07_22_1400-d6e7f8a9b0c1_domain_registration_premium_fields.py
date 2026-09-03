"""Add registry premium pricing fields to domain_registration_orders."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d6e7f8a9b0c1"
# Chain after the 2026-07-22 merge head (VA + domain batch), not the pre-merge parent.
down_revision = "1497a64dde10"
branch_labels = None
depends_on = None

_TABLE = "domain_registration_orders"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}

    if "is_premium" not in existing:
        op.add_column(
            _TABLE,
            sa.Column("is_premium", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "registry_tier" not in existing:
        op.add_column(
            _TABLE,
            sa.Column(
                "registry_tier",
                sa.String(length=16),
                nullable=False,
                server_default="standard",
            ),
        )
    if "provider_unit_price_inr" not in existing:
        op.add_column(
            _TABLE,
            sa.Column("provider_unit_price_inr", sa.Float(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    if "provider_unit_price_inr" in existing:
        op.drop_column(_TABLE, "provider_unit_price_inr")
    if "registry_tier" in existing:
        op.drop_column(_TABLE, "registry_tier")
    if "is_premium" in existing:
        op.drop_column(_TABLE, "is_premium")
