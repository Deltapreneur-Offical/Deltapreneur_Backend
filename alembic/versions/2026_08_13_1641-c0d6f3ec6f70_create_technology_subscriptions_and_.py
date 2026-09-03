"""create technology_subscriptions and technology_subscription_invoices tables

Revision ID: c0d6f3ec6f70
Revises: b352d8f5e27b
Create Date: 2026-08-13 16:41:23.113954

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c0d6f3ec6f70'
down_revision: Union[str, Sequence[str], None] = 'b352d8f5e27b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "technology_subscriptions" not in tables:
        op.create_table(
            "technology_subscriptions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("user_id", sa.String(length=100), nullable=False),
            sa.Column("service_slug", sa.String(length=100), nullable=False),
            sa.Column("service_name", sa.String(length=255), nullable=False),
            sa.Column("plan_code", sa.String(length=64), nullable=False),
            sa.Column("billing_cycle", sa.String(length=32), nullable=False, server_default="monthly"),
            sa.Column("price", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("currency", sa.String(length=10), nullable=False, server_default="USD"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
            sa.Column("provider_subscription_id", sa.String(length=255), nullable=True),
            sa.Column("provider_order_id", sa.String(length=255), nullable=True),
            sa.Column("credentials_json", sa.Text(), nullable=True),
            sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default="true"),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_technology_subscriptions")),
        )
        op.create_index("idx_tech_subs_user", "technology_subscriptions", ["user_id"], unique=False)
        op.create_index("idx_tech_subs_service", "technology_subscriptions", ["service_slug"], unique=False)
        op.create_index("idx_tech_subs_status", "technology_subscriptions", ["status"], unique=False)

    if "technology_subscription_invoices" not in tables:
        op.create_table(
            "technology_subscription_invoices",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("subscription_id", sa.String(length=100), nullable=False),
            sa.Column("user_id", sa.String(length=100), nullable=False),
            sa.Column("invoice_number", sa.String(length=100), nullable=False),
            sa.Column("amount", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("currency", sa.String(length=10), nullable=False, server_default="USD"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="PAID"),
            sa.Column("billing_period_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("billing_period_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("payment_method", sa.String(length=64), nullable=True, server_default="CoBrother Pay"),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_technology_subscription_invoices")),
            sa.UniqueConstraint("invoice_number", name="uq_tech_inv_number"),
        )
        op.create_index("idx_tech_inv_sub", "technology_subscription_invoices", ["subscription_id"], unique=False)
        op.create_index("idx_tech_inv_user", "technology_subscription_invoices", ["user_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "technology_subscription_invoices" in tables:
        op.drop_index("idx_tech_inv_user", table_name="technology_subscription_invoices")
        op.drop_index("idx_tech_inv_sub", table_name="technology_subscription_invoices")
        op.drop_table("technology_subscription_invoices")

    if "technology_subscriptions" in tables:
        op.drop_index("idx_tech_subs_status", table_name="technology_subscriptions")
        op.drop_index("idx_tech_subs_service", table_name="technology_subscriptions")
        op.drop_index("idx_tech_subs_user", table_name="technology_subscriptions")
        op.drop_table("technology_subscriptions")
