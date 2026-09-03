"""Expand VA notification types to cover all workspace events."""

from alembic import op
import sqlalchemy as sa

revision = "va_20260718_1700"
down_revision = "va_20260718_1600"
branch_labels = None
depends_on = None

_TABLE = "va_notifications"


def upgrade():
    # `va_notifications` is defined on the ORM entity but has no create-table
    # migration in this repo. On fresh CI databases the table does not exist, so
    # expanding its enum would fail — skip safely when missing.
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table(_TABLE):
        return

    conn.execute(
        sa.text(
            "DO $$ "
            "BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'va_notification_type_enum_new') THEN "
            "    CREATE TYPE va_notification_type_enum_new AS ENUM ( "
            "      'application_submitted', "
            "      'role_approval', "
            "      'role_rejected', "
            "      'workspace_unlocked', "
            "      'pricing_updated', "
            "      'profile_published', "
            "      'profile_unpublished', "
            "      'new_assignment', "
            "      'assignment_updated', "
            "      'assignment_completed', "
            "      'admin_message' "
            "    ); "
            "  END IF; "
            "END $$;"
        )
    )
    op.execute(
        """
        ALTER TABLE va_notifications
        ALTER COLUMN type TYPE va_notification_type_enum_new
        USING type::text::va_notification_type_enum_new
        """
    )
    op.execute("DROP TYPE IF EXISTS va_notification_type_enum")
    op.execute("ALTER TYPE va_notification_type_enum_new RENAME TO va_notification_type_enum")


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table(_TABLE):
        return

    conn.execute(
        sa.text(
            "DO $$ "
            "BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'va_notification_type_enum_old') THEN "
            "    CREATE TYPE va_notification_type_enum_old AS ENUM ( "
            "      'role_approval', "
            "      'new_assignment', "
            "      'assignment_update', "
            "      'admin_message' "
            "    ); "
            "  END IF; "
            "END $$;"
        )
    )
    op.execute(
        """
        ALTER TABLE va_notifications
        ALTER COLUMN type TYPE va_notification_type_enum_old
        USING type::text::va_notification_type_enum_old
        """
    )
    op.execute("DROP TYPE IF EXISTS va_notification_type_enum")
    op.execute("ALTER TYPE va_notification_type_enum_old RENAME TO va_notification_type_enum")
