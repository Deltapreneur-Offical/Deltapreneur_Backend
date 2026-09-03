"""Add max_client_capacity to virtual_assistant_applications."""

from alembic import op
import sqlalchemy as sa


revision = "va_20260718_1200"
down_revision = "z1y2x3w4v5u6"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = {c["name"] for c in inspector.get_columns("virtual_assistant_applications")}
    if "max_client_capacity" not in existing:
        op.add_column(
            "virtual_assistant_applications",
            sa.Column("max_client_capacity", sa.Integer(), nullable=True),
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = {c["name"] for c in inspector.get_columns("virtual_assistant_applications")}
    if "max_client_capacity" in existing:
        op.drop_column("virtual_assistant_applications", "max_client_capacity")
