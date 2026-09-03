"""Align VA schema with ORM + create missing workspace tables.

Revision ID: h0i1j2k3l4m5
Revises: g9h0i1j2k3l4
Create Date: 2026-07-23 18:00:00.000000

Coworker commit 5054b3c0 (Sushma) shipped a VirtualAssistantApplication ORM that
expects renamed/new columns (short_bio, consent_*, overall_status, …) and workspace
tables (va_assignments / va_clients / va_notifications), but the Alembic chain left
the DB on the older column names and never created the workspace tables.

Authenticated GET /api/v1/virtual-assistant/me then raises UndefinedColumnError →
500, which the browser reports as a CORS failure.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h0i1j2k3l4m5"
down_revision: Union[str, Sequence[str], None] = "g9h0i1j2k3l4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_APP = "virtual_assistant_applications"
_ROLES = "virtual_assistant_application_roles"


def _cols(table: str) -> set[str]:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t"
        ),
        {"t": table},
    ).fetchall()
    return {r[0] for r in rows}


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name=:t)"
            ),
            {"t": table},
        ).scalar()
    )


def _rename_if_needed(table: str, old: str, new: str) -> None:
    existing = _cols(table)
    if old in existing and new not in existing:
        op.alter_column(table, old, new_column_name=new)


def _add_if_missing(table: str, column: sa.Column) -> None:
    if column.name not in _cols(table):
        op.add_column(table, column)


def _ensure_enum(name: str, values: tuple[str, ...]) -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :n"),
        {"n": name},
    ).fetchone()
    if exists:
        return
    vals = ", ".join(f"'{v}'" for v in values)
    bind.execute(sa.text(f"CREATE TYPE {name} AS ENUM ({vals})"))


def upgrade() -> None:
    if not _has_table(_APP):
        return

    # --- rename legacy columns to match ORM ---
    _rename_if_needed(_APP, "bio", "short_bio")
    _rename_if_needed(_APP, "years_of_experience", "years_experience")
    _rename_if_needed(_APP, "languages", "languages_known")
    _rename_if_needed(_APP, "info_accurate", "consent_accurate")
    _rename_if_needed(_APP, "agree_terms", "consent_terms")
    _rename_if_needed(_APP, "is_adult", "consent_adult")

    # --- add missing ORM columns ---
    _add_if_missing(_APP, sa.Column("user_id", sa.String(length=36), nullable=True))
    _add_if_missing(_APP, sa.Column("short_bio", sa.String(length=1000), nullable=True))
    _add_if_missing(_APP, sa.Column("years_experience", sa.String(length=50), nullable=True))
    _add_if_missing(_APP, sa.Column("languages_known", sa.String(length=300), nullable=True))
    _add_if_missing(
        _APP,
        sa.Column("consent_accurate", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_if_missing(
        _APP,
        sa.Column("consent_terms", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_if_missing(
        _APP,
        sa.Column("consent_adult", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_if_missing(_APP, sa.Column("admin_notes", sa.Text(), nullable=True))
    _add_if_missing(_APP, sa.Column("profile_photo_key", sa.String(length=500), nullable=True))
    _add_if_missing(_APP, sa.Column("profile_photo_filename", sa.String(length=255), nullable=True))
    _add_if_missing(_APP, sa.Column("profile_photo_mime_type", sa.String(length=100), nullable=True))
    _add_if_missing(_APP, sa.Column("profile_photo_size", sa.Integer(), nullable=True))
    _add_if_missing(_APP, sa.Column("resume_key", sa.String(length=500), nullable=True))
    _add_if_missing(_APP, sa.Column("resume_filename", sa.String(length=255), nullable=True))
    _add_if_missing(_APP, sa.Column("resume_mime_type", sa.String(length=100), nullable=True))
    _add_if_missing(_APP, sa.Column("resume_size", sa.Integer(), nullable=True))
    _add_if_missing(_APP, sa.Column("reviewed_by_id", sa.String(length=36), nullable=True))
    _add_if_missing(_APP, sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    _add_if_missing(
        _APP,
        sa.Column("workspace_locked", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    _ensure_enum(
        "overall_status_enum",
        ("pending", "partially_approved", "approved", "rejected"),
    )
    if "overall_status" not in _cols(_APP):
        op.add_column(
            _APP,
            sa.Column(
                "overall_status",
                postgresql.ENUM(
                    "pending",
                    "partially_approved",
                    "approved",
                    "rejected",
                    name="overall_status_enum",
                    create_type=False,
                ),
                nullable=False,
                server_default="pending",
            ),
        )

    # Widen roles if still short
    existing = _cols(_APP)
    if "roles" in existing:
        op.alter_column(_APP, "roles", type_=sa.String(length=1024), existing_type=sa.String(length=500))

    # Index user_id
    bind = op.get_bind()
    idx = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes WHERE tablename=:t AND indexname=:i"
        ),
        {"t": _APP, "i": "ix_virtual_assistant_applications_user_id"},
    ).fetchone()
    if not idx and "user_id" in _cols(_APP):
        op.create_index(
            "ix_virtual_assistant_applications_user_id",
            _APP,
            ["user_id"],
            unique=False,
        )

    # --- roles table timestamps ---
    if _has_table(_ROLES):
        _add_if_missing(
            _ROLES,
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        _add_if_missing(
            _ROLES,
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    # --- workspace tables ---
    _ensure_enum("va_assignment_status_enum", ("active", "completed", "on_hold", "cancelled"))
    _ensure_enum("va_client_status_enum", ("active", "completed", "inactive"))

    if not _has_table("va_assignments"):
        op.create_table(
            "va_assignments",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("assigned_company", sa.String(length=200), nullable=True),
            sa.Column("assigned_role", sa.String(length=100), nullable=True),
            sa.Column(
                "status",
                postgresql.ENUM(
                    "active",
                    "completed",
                    "on_hold",
                    "cancelled",
                    name="va_assignment_status_enum",
                    create_type=False,
                ),
                nullable=False,
                server_default="active",
            ),
            sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["application_id"],
                ["virtual_assistant_applications.id"],
                ondelete="CASCADE",
            ),
        )
        op.create_index("ix_va_assignments_application_id", "va_assignments", ["application_id"])

    if not _has_table("va_clients"):
        op.create_table(
            "va_clients",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("client_name", sa.String(length=200), nullable=True),
            sa.Column("company_name", sa.String(length=200), nullable=True),
            sa.Column("assigned_role", sa.String(length=100), nullable=True),
            sa.Column(
                "status",
                postgresql.ENUM(
                    "active",
                    "completed",
                    "inactive",
                    name="va_client_status_enum",
                    create_type=False,
                ),
                nullable=False,
                server_default="active",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["application_id"],
                ["virtual_assistant_applications.id"],
                ondelete="CASCADE",
            ),
        )
        op.create_index("ix_va_clients_application_id", "va_clients", ["application_id"])

    if not _has_table("va_notifications"):
        op.create_table(
            "va_notifications",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("va_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("notification_type", sa.String(length=100), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("target_url", sa.String(length=1000), nullable=True),
            sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("related_application_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("related_assignment_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(["va_id"], ["users.id"]),
            sa.ForeignKeyConstraint(
                ["related_application_id"],
                ["virtual_assistant_applications.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["related_assignment_id"],
                ["va_assignments.id"],
                ondelete="CASCADE",
            ),
        )
        op.create_index("ix_va_notifications_va_id", "va_notifications", ["va_id"])


def downgrade() -> None:
    # Non-destructive downgrade: keep repaired columns; only drop workspace tables.
    if _has_table("va_notifications"):
        op.drop_table("va_notifications")
    if _has_table("va_clients"):
        op.drop_table("va_clients")
    if _has_table("va_assignments"):
        op.drop_table("va_assignments")
