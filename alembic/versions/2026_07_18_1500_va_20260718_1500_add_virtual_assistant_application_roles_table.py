"""Create virtual_assistant_application_roles table."""

from alembic import op
import sqlalchemy as sa


revision = "va_20260718_1500"
down_revision = "va_20260718_1400"
branch_labels = None
depends_on = None

_TABLE = "virtual_assistant_application_roles"
_INDEX = "ix_va_app_role_application_id"


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    # Fresh DBs do not have this table yet — never call get_columns() first.
    if not inspector.has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
            sa.Column("application_id", sa.UUID(as_uuid=True), nullable=False),
            sa.Column("role_name", sa.String(length=100), nullable=False),
            sa.Column(
                "status",
                sa.Enum("pending", "approved", "rejected", name="role_status_enum"),
                nullable=False,
            ),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reviewed_by_id", sa.String(length=36), nullable=True),
            sa.Column("rejection_note", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(
                ["application_id"],
                ["virtual_assistant_applications.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(conn)
    indexes = {idx["name"] for idx in inspector.get_indexes(_TABLE)}
    if _INDEX not in indexes:
        op.create_index(_INDEX, _TABLE, ["application_id"])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table(_TABLE):
        return
    indexes = {idx["name"] for idx in inspector.get_indexes(_TABLE)}
    if _INDEX in indexes:
        op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
