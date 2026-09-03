"""Add capacity fields to virtual_assistant_application_roles."""

from alembic import op
import sqlalchemy as sa


revision = "va_20260718_1600"
down_revision = "va_20260718_1500"
branch_labels = None
depends_on = None

_TABLE = "virtual_assistant_application_roles"


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table(_TABLE):
        return
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    if "max_clients" not in existing:
        op.add_column(_TABLE, sa.Column("max_clients", sa.Integer(), nullable=True))
    if "current_clients" not in existing:
        op.add_column(
            _TABLE,
            sa.Column("current_clients", sa.Integer(), nullable=False, server_default="0"),
        )
    if "is_active" not in existing:
        op.add_column(
            _TABLE,
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table(_TABLE):
        return
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    if "is_active" in existing:
        op.drop_column(_TABLE, "is_active")
    if "current_clients" in existing:
        op.drop_column(_TABLE, "current_clients")
    if "max_clients" in existing:
        op.drop_column(_TABLE, "max_clients")
