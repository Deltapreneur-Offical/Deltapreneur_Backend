"""add retry/state fields to technology_subscriptions.

Adds the fields required for the production-safe Technology Services
provisioning lifecycle:

  payment_status          payment state (CAPTURED / PENDING / FAILED / REFUNDED)
  idempotency_key         local idempotency reference for provisioning attempts
  provision_attempts      number of provisioning attempts made
  last_provision_attempt_at  when the last attempt happened
  last_provider_status    last provider-returned status
  last_provider_error     last provider/validation error message
  next_retry_at           when the retry worker may try again (backoff)
  confirmation_sent       whether the ACTIVE confirmation email was sent
  razorpay_order_id       Razorpay order id that paid for this subscription
  razorpay_payment_id     Razorpay payment id that paid for this subscription
  needs_review            admin/customer attention required (needs input, retries exhausted)
  provision_input         JSON blob of customer-provided provisioning input
                          (e.g. {"areaCode": "415"} or {"primaryDomain": "example.com"})

Revision ID: rp_tech_sub_retry_fields_001
Revises: share001
Create Date: 2026-08-14 18:00:00.000000

SAFETY: additive only — no column is dropped or renamed and no row is
deleted or modified.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "rp_tech_sub_retry_fields_001"
# Chain after the showcase001 head (both originally branched from share001) so
# the graph has a single linear head instead of two independent branches.
down_revision: Union[str, Sequence[str], None] = "showcase001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("technology_subscriptions")}
    return cols


def upgrade() -> None:
    cols = _existing_columns()

    def _add(name: str, column: sa.Column) -> None:
        if name not in cols:
            op.add_column("technology_subscriptions", column)

    _add("payment_status", sa.Column("payment_status", sa.String(length=32), nullable=False, server_default=sa.text("'CAPTURED'")))
    _add("idempotency_key", sa.Column("idempotency_key", sa.String(length=64), nullable=True))
    _add("provision_attempts", sa.Column("provision_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")))
    _add("last_provision_attempt_at", sa.Column("last_provision_attempt_at", sa.DateTime(timezone=True), nullable=True))
    _add("last_provider_status", sa.Column("last_provider_status", sa.String(length=64), nullable=True))
    _add("last_provider_error", sa.Column("last_provider_error", sa.Text(), nullable=True))
    _add("next_retry_at", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
    _add("confirmation_sent", sa.Column("confirmation_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    _add("razorpay_order_id", sa.Column("razorpay_order_id", sa.String(length=64), nullable=True))
    _add("razorpay_payment_id", sa.Column("razorpay_payment_id", sa.String(length=64), nullable=True))
    _add("needs_review", sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    _add("provision_input", sa.Column("provision_input", sa.Text(), nullable=True))

    # Index creation guarded so this migration is idempotent when the columns
    # have already been applied out-of-band (e.g. on a shared database where
    # an unrelated intermediate migration cannot be run).
    inspector = sa.inspect(op.get_bind())
    indexes = {ix["name"] for ix in inspector.get_indexes("technology_subscriptions")}
    if "idx_tech_subs_retry" not in indexes:
        op.create_index(
            "idx_tech_subs_retry",
            "technology_subscriptions",
            ["status", "payment_status", "next_retry_at"],
            unique=False,
        )
    if "uq_tech_subs_idempotency" not in indexes:
        op.create_index("uq_tech_subs_idempotency", "technology_subscriptions", ["idempotency_key"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {ix["name"] for ix in inspector.get_indexes("technology_subscriptions")}
    if "uq_tech_subs_idempotency" in indexes:
        op.drop_index("uq_tech_subs_idempotency", table_name="technology_subscriptions")
    if "idx_tech_subs_retry" in indexes:
        op.drop_index("idx_tech_subs_retry", table_name="technology_subscriptions")

    cols = _existing_columns()
    for name in (
        "provision_input",
        "needs_review",
        "razorpay_payment_id",
        "razorpay_order_id",
        "confirmation_sent",
        "next_retry_at",
        "last_provider_error",
        "last_provider_status",
        "last_provision_attempt_at",
        "provision_attempts",
        "idempotency_key",
        "payment_status",
    ):
        if name in cols:
            op.drop_column("technology_subscriptions", name)
