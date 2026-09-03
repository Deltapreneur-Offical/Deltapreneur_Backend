"""Add Virtual Assistant publish status fields."""

from alembic import op
import sqlalchemy as sa


revision = "va_20260718_1400"
down_revision = "va_20260718_1300"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = {c["name"] for c in inspector.get_columns("virtual_assistant_applications")}
    if "publish_status" not in existing:
        op.add_column(
            "virtual_assistant_applications",
            sa.Column("publish_status", sa.String(length=20), nullable=False, server_default="draft"),
        )
    if "published_at" not in existing:
        op.add_column(
            "virtual_assistant_applications",
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "published_by_id" not in existing:
        op.add_column(
            "virtual_assistant_applications",
            sa.Column("published_by_id", sa.String(length=36), nullable=True),
        )
    if "published_by_name" not in existing:
        op.add_column(
            "virtual_assistant_applications",
            sa.Column("published_by_name", sa.String(length=255), nullable=True),
        )
    conn.execute(
        sa.text("UPDATE virtual_assistant_applications SET publish_status = 'draft' WHERE publish_status IS NULL")
    )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = {c["name"] for c in inspector.get_columns("virtual_assistant_applications")}
    if "published_by_name" in existing:
        op.drop_column("virtual_assistant_applications", "published_by_name")
    if "published_by_id" in existing:
        op.drop_column("virtual_assistant_applications", "published_by_id")
    if "published_at" in existing:
        op.drop_column("virtual_assistant_applications", "published_at")
    if "publish_status" in existing:
        op.drop_column("virtual_assistant_applications", "publish_status")
