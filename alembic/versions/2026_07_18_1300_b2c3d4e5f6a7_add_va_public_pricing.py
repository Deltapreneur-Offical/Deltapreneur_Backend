"""Add Virtual Assistant public pricing fields."""

from alembic import op
import sqlalchemy as sa


revision = "va_20260718_1300"
down_revision = "va_20260718_1200"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = {c["name"] for c in inspector.get_columns("virtual_assistant_applications")}
    if "public_monthly_price_inr" not in existing:
        op.add_column(
            "virtual_assistant_applications",
            sa.Column("public_monthly_price_inr", sa.Integer(), nullable=True),
        )
    if "pricing_currency" not in existing:
        op.add_column(
            "virtual_assistant_applications",
            sa.Column("pricing_currency", sa.String(length=3), nullable=True),
        )
    if "pricing_updated_by_id" not in existing:
        op.add_column(
            "virtual_assistant_applications",
            sa.Column("pricing_updated_by_id", sa.String(length=36), nullable=True),
        )
    if "pricing_updated_at" not in existing:
        op.add_column(
            "virtual_assistant_applications",
            sa.Column("pricing_updated_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = {c["name"] for c in inspector.get_columns("virtual_assistant_applications")}
    if "pricing_updated_at" in existing:
        op.drop_column("virtual_assistant_applications", "pricing_updated_at")
    if "pricing_updated_by_id" in existing:
        op.drop_column("virtual_assistant_applications", "pricing_updated_by_id")
    if "pricing_currency" in existing:
        op.drop_column("virtual_assistant_applications", "pricing_currency")
    if "public_monthly_price_inr" in existing:
        op.drop_column("virtual_assistant_applications", "public_monthly_price_inr")
