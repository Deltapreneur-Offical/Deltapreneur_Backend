"""domains: UUID PK, domain_name, owner_id; auctions.domain_id UUID

Clears auction-module rows then rebuilds `domains` and re-links `auctions.domain_id`.
Destructive for existing auction data; safe for empty dev databases.

Revision ID: b2c3d4e5f601
Revises: a1f4d8c9b201
Create Date: 2026-05-14 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f601"
down_revision: Union[str, Sequence[str], None] = "a1f4d8c9b201"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Known FK names: a1 used inline FK (Postgres default) or env naming convention.
_AUCTIONS_DOMAIN_FK_NAMES = (
    "auctions_domain_id_fkey",
    "fk_auctions_domain_id_domains",
)


def _soft_delete_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
    ]


def _table_exists(conn, table_name: str) -> bool:
    return bool(
        conn.execute(
            sa.text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables "
                "  WHERE table_schema = current_schema() "
                "  AND table_name = :name"
                ")"
            ),
            {"name": table_name},
        ).scalar()
    )


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    return bool(
        conn.execute(
            sa.text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.columns "
                "  WHERE table_schema = current_schema() "
                "  AND table_name = :table "
                "  AND column_name = :column"
                ")"
            ),
            {"table": table_name, "column": column_name},
        ).scalar()
    )


def _delete_if_table_exists(conn, table_name: str) -> None:
    if _table_exists(conn, table_name):
        op.execute(sa.text(f"DELETE FROM {table_name}"))


def _drop_auctions_domain_fk(conn) -> None:
    """Drop any FK on auctions.domain_id; no-op if auctions table is missing."""
    if not _table_exists(conn, "auctions"):
        return

    op.execute(
        sa.text(
            """
            DO $$
            DECLARE r RECORD;
            BEGIN
                FOR r IN
                    SELECT c.conname
                    FROM pg_constraint c
                    JOIN pg_class t ON c.conrelid = t.oid
                    JOIN pg_namespace n ON t.relnamespace = n.oid
                    WHERE n.nspname = current_schema()
                      AND t.relname = 'auctions'
                      AND c.contype = 'f'
                      AND EXISTS (
                          SELECT 1
                          FROM pg_attribute a
                          WHERE a.attrelid = c.conrelid
                            AND a.attname = 'domain_id'
                            AND a.attnum = ANY (c.conkey)
                      )
                LOOP
                    EXECUTE format(
                        'ALTER TABLE auctions DROP CONSTRAINT IF EXISTS %I',
                        r.conname
                    );
                END LOOP;
            END $$;
            """
        )
    )

    for name in _AUCTIONS_DOMAIN_FK_NAMES:
        op.execute(
            sa.text(
                f"ALTER TABLE auctions DROP CONSTRAINT IF EXISTS {name}"
            )
        )


def _drop_old_domains_table(conn) -> None:
    if not _table_exists(conn, "domains"):
        return

    op.execute(sa.text("DROP INDEX IF EXISTS uq_domains_domain_name_active"))
    op.drop_index("idx_domains_domain_name", table_name="domains", if_exists=True)
    op.drop_index("idx_domains_owner_id", table_name="domains", if_exists=True)
    op.drop_index("idx_domains_owner_user_id", table_name="domains", if_exists=True)
    op.drop_table("domains")


def _create_uuid_domains_table() -> None:
    op.create_table(
        "domains",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        *_soft_delete_columns(),
    )
    op.create_index("idx_domains_owner_id", "domains", ["owner_id"])
    op.create_index("idx_domains_domain_name", "domains", ["domain_name"])
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_domains_domain_name_active "
            "ON domains (lower(domain_name)) WHERE NOT is_deleted"
        )
    )


def _remove_auctions_domain_id(conn) -> None:
    """Drop FK + column so `domains` can be dropped and recreated."""
    if not _table_exists(conn, "auctions"):
        return

    _drop_auctions_domain_fk(conn)

    if _column_exists(conn, "auctions", "domain_id"):
        op.drop_index("idx_auction_domain_id", table_name="auctions", if_exists=True)
        op.drop_column("auctions", "domain_id")


def _add_auctions_domain_id_uuid(conn) -> None:
    """Add UUID domain_id after the new `domains` table exists."""
    if not _table_exists(conn, "auctions"):
        return

    if _column_exists(conn, "auctions", "domain_id"):
        return

    op.add_column(
        "auctions",
        sa.Column(
            "domain_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "auctions_domain_id_fkey",
        "auctions",
        "domains",
        ["domain_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("idx_auction_domain_id", "auctions", ["domain_id"])


def upgrade() -> None:
    conn = op.get_bind()

    # Child tables first (FK order).
    for table in ("transactions", "payments", "bids", "auctions"):
        _delete_if_table_exists(conn, table)

    # Must drop auctions -> domains FK before dropping `domains`.
    _remove_auctions_domain_id(conn)
    _drop_old_domains_table(conn)
    _create_uuid_domains_table()
    _add_auctions_domain_id_uuid(conn)


def downgrade() -> None:
    conn = op.get_bind()

    for table in ("transactions", "payments", "bids", "auctions"):
        _delete_if_table_exists(conn, table)

    _remove_auctions_domain_id(conn)
    _drop_old_domains_table(conn)

    op.create_table(
        "domains",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        *_soft_delete_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_domains"),
    )
    op.create_index("idx_domains_owner_user_id", "domains", ["owner_user_id"])

    if _table_exists(conn, "auctions"):
        op.add_column(
            "auctions",
            sa.Column(
                "domain_id",
                sa.Integer(),
                nullable=False,
            ),
        )
        op.create_foreign_key(
            "auctions_domain_id_fkey",
            "auctions",
            "domains",
            ["domain_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index("idx_auction_domain_id", "auctions", ["domain_id"])
