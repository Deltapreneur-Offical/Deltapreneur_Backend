"""Allocate Aultum tax invoice numbers only for successful domain registrations.

Format: AI + YY + 5-digit sequence (e.g. AI2600001).
Numbers are global across all users and never assigned to failed / refunded /
cancelled / PROVISION_FAILED orders.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.utils.registration_enums import RegistrationOrderStatus

logger = logging.getLogger(__name__)

DOMAIN_TAX_INVOICE_LOCK_KEY = 826_001
INVOICE_PREFIX = "AI"
_INVOICE_RE = re.compile(r"^AI(\d{2})(\d{5})$")


def format_tax_invoice_number(year: int, sequence: int) -> str:
    year_suffix = str(int(year))[-2:]
    return f"{INVOICE_PREFIX}{year_suffix}{int(sequence):05d}"


def parse_tax_invoice_number(invoice_number: str) -> tuple[int, int]:
    """Return (full_year, sequence) from AIYY#####. Raises AppException if invalid."""
    raw = str(invoice_number or "").strip().upper().replace(" ", "")
    match = _INVOICE_RE.fullmatch(raw)
    if not match:
        raise AppException(
            "Invalid invoice number. Use format AI + year + 5 digits (e.g. AI2600001).",
            status_code=400,
        )
    yy = int(match.group(1))
    seq = int(match.group(2))
    if seq < 1:
        raise AppException("Invoice sequence must be at least 00001.", status_code=400)
    # Map 2-digit year into 2000–2099 (current product window).
    year = 2000 + yy
    return year, seq


def _invoice_year_for_order(order: DomainRegistrationOrder) -> int:
    stamp = order.completed_at or order.created_at or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return int(stamp.astimezone(timezone.utc).year)


async def ensure_tax_invoice_number(
    session: AsyncSession,
    order: DomainRegistrationOrder,
) -> str | None:
    """
    Assign a permanent tax invoice number when (and only when) the order is ACTIVE.

    Idempotent: returns the existing number if already assigned.
    Concurrent-safe via a transaction-scoped advisory lock + year counter row.
    """
    if order.status != RegistrationOrderStatus.ACTIVE:
        return None

    existing = getattr(order, "tax_invoice_number", None)
    if existing:
        return str(existing)

    year = _invoice_year_for_order(order)

    # Serialize allocations across workers for this transaction.
    try:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": DOMAIN_TAX_INVOICE_LOCK_KEY},
        )
    except Exception:
        # Non-Postgres test DBs may lack advisory locks; fall through with
        # unique-index protection on tax_invoice_number.
        logger.debug("domain.tax_invoice.advisory_lock_unavailable", exc_info=True)

    await session.execute(
        text(
            """
            INSERT INTO domain_tax_invoice_counters (year, last_seq)
            VALUES (:year, 0)
            ON CONFLICT (year) DO NOTHING
            """
        ),
        {"year": year},
    )
    row = await session.execute(
        text(
            """
            SELECT last_seq
            FROM domain_tax_invoice_counters
            WHERE year = :year
            FOR UPDATE
            """
        ),
        {"year": year},
    )
    last_seq = int(row.scalar_one())
    next_seq = last_seq + 1
    invoice_number = format_tax_invoice_number(year, next_seq)

    await session.execute(
        text(
            """
            UPDATE domain_tax_invoice_counters
            SET last_seq = :last_seq
            WHERE year = :year
            """
        ),
        {"year": year, "last_seq": next_seq},
    )

    order.tax_invoice_number = invoice_number
    logger.info(
        "domain.tax_invoice.allocated order_id=%s domain=%s number=%s",
        getattr(order, "id", None),
        getattr(order, "fqdn", None),
        invoice_number,
    )
    return invoice_number


async def admin_set_tax_invoice_number(
    session: AsyncSession,
    order_id: uuid.UUID,
    new_number: str,
) -> dict:
    """
    ADMIN-only: set/replace tax_invoice_number on an ACTIVE registration order.

    Safe ops only: UPDATE order.tax_invoice_number + bump counter last_seq.
    Does not delete orders or wipe other data.
    """
    year, seq = parse_tax_invoice_number(new_number)
    invoice_number = format_tax_invoice_number(year, seq)

    try:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": DOMAIN_TAX_INVOICE_LOCK_KEY},
        )
    except Exception:
        logger.debug("domain.tax_invoice.advisory_lock_unavailable", exc_info=True)

    result = await session.execute(
        select(DomainRegistrationOrder).where(DomainRegistrationOrder.id == order_id)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise AppException("Domain registration order not found.", status_code=404)

    if order.status != RegistrationOrderStatus.ACTIVE:
        raise AppException(
            "Invoice numbers can only be set on ACTIVE (successfully registered) orders.",
            status_code=400,
        )

    existing_same = str(getattr(order, "tax_invoice_number", None) or "").strip().upper()
    if existing_same == invoice_number:
        domain = f"{order.domain_name}{order.domain_extension}"
        return {
            "orderId": str(order.id),
            "domain": domain,
            "taxInvoiceNumber": invoice_number,
            "invoiceNumber": invoice_number,
            "unchanged": True,
        }

    conflict = await session.execute(
        select(DomainRegistrationOrder.id)
        .where(
            DomainRegistrationOrder.tax_invoice_number == invoice_number,
            DomainRegistrationOrder.id != order_id,
        )
        .limit(1)
    )
    if conflict.scalar_one_or_none() is not None:
        raise AppException(
            f"Invoice number {invoice_number} is already used by another order.",
            status_code=409,
        )

    previous = existing_same or None
    order.tax_invoice_number = invoice_number

    await session.execute(
        text(
            """
            INSERT INTO domain_tax_invoice_counters (year, last_seq)
            VALUES (:year, :seq)
            ON CONFLICT (year) DO UPDATE
            SET last_seq = GREATEST(domain_tax_invoice_counters.last_seq, EXCLUDED.last_seq)
            """
        ),
        {"year": year, "seq": seq},
    )

    await session.flush()
    domain = f"{order.domain_name}{order.domain_extension}"
    logger.info(
        "domain.tax_invoice.admin_set order_id=%s domain=%s previous=%s new=%s",
        order.id,
        domain,
        previous,
        invoice_number,
    )
    return {
        "orderId": str(order.id),
        "domain": domain,
        "taxInvoiceNumber": invoice_number,
        "invoiceNumber": invoice_number,
        "previousTaxInvoiceNumber": previous,
        "unchanged": False,
    }
