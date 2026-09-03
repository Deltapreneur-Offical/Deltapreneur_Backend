"""Add tax_invoice_number for successful domain registrations only.

Revision ID: taxinv001
Revises: phoneuniq001
Create Date: 2026-08-06 16:15:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision: str = "taxinv001"
down_revision: Union[str, Sequence[str], None] = "phoneuniq001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "domain_tax_invoice_counters" not in tables:
        op.create_table(
            "domain_tax_invoice_counters",
            sa.Column("year", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("last_seq", sa.Integer(), nullable=False, server_default="0"),
        )

    columns = {
        col["name"] for col in inspector.get_columns("domain_registration_orders")
    }
    if "tax_invoice_number" not in columns:
        op.add_column(
            "domain_registration_orders",
            sa.Column("tax_invoice_number", sa.String(length=32), nullable=True),
        )

    indexes = {
        idx["name"] for idx in inspector.get_indexes("domain_registration_orders")
    }
    if "uq_domain_reg_orders_tax_invoice_number" not in indexes:
        op.create_index(
            "uq_domain_reg_orders_tax_invoice_number",
            "domain_registration_orders",
            ["tax_invoice_number"],
            unique=True,
        )

    # Backfill ONLY currently ACTIVE / successfully registered orders.
    # Failed, refunded, cancelled, and PROVISION_FAILED rows stay NULL.
    rows = bind.execute(
        text(
            """
            SELECT id, COALESCE(completed_at, created_at, NOW()) AS stamp
            FROM domain_registration_orders
            WHERE status = 'ACTIVE'
              AND tax_invoice_number IS NULL
            ORDER BY COALESCE(completed_at, created_at) ASC NULLS LAST, id ASC
            """
        )
    ).fetchall()

    year_seq: dict[int, int] = {}
    for row in rows:
        stamp = row.stamp
        year = int(stamp.year) if hasattr(stamp, "year") else int(str(stamp)[:4])
        year_seq[year] = year_seq.get(year, 0) + 1
        seq = year_seq[year]
        year_suffix = str(year)[-2:]
        invoice_number = f"AI{year_suffix}{seq:05d}"
        bind.execute(
            text(
                """
                UPDATE domain_registration_orders
                SET tax_invoice_number = :invoice_number
                WHERE id = :id
                """
            ),
            {"invoice_number": invoice_number, "id": row.id},
        )

    for year, last_seq in year_seq.items():
        bind.execute(
            text(
                """
                INSERT INTO domain_tax_invoice_counters (year, last_seq)
                VALUES (:year, :last_seq)
                ON CONFLICT (year) DO UPDATE
                SET last_seq = GREATEST(domain_tax_invoice_counters.last_seq, EXCLUDED.last_seq)
                """
            ),
            {"year": year, "last_seq": last_seq},
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = {
        idx["name"] for idx in inspector.get_indexes("domain_registration_orders")
    }
    if "uq_domain_reg_orders_tax_invoice_number" in indexes:
        op.drop_index(
            "uq_domain_reg_orders_tax_invoice_number",
            table_name="domain_registration_orders",
        )
    columns = {
        col["name"] for col in inspector.get_columns("domain_registration_orders")
    }
    if "tax_invoice_number" in columns:
        op.drop_column("domain_registration_orders", "tax_invoice_number")
    tables = set(inspector.get_table_names())
    if "domain_tax_invoice_counters" in tables:
        op.drop_table("domain_tax_invoice_counters")
