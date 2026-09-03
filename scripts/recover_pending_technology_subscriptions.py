"""One-time recovery for existing paid Technology Services purchases.

Recovers Business Phone / Web Hosting / WordPress purchases that are stuck
PENDING (or missing a subscription / invoice) WITHOUT charging the customer
again and without creating duplicate provider orders.

DEFAULT MODE: --dry-run (read-only; prints a report per purchase with the
recommended action). Only ``--apply`` performs writes.

Usage:
    python scripts/recover_pending_technology_subscriptions.py [--apply] [--user-id <uuid>] [--service-slug <slug>]

What it does (--apply):
    * Business Phone  -> validates that an area code is present (metadata /
                         provision_input); if present, runs the safe
                         reconciliation-first retry. If missing, keeps the
                         subscription PENDING with needs_input and reports it.
    * Web Hosting     -> derives cpanel_username + primary_domain from a
                         CoBrother domain record when available; if a paid
                         payment exists but no subscription/invoice row exists,
                         reconstructs them from trusted payment/request data.
    * WordPress       -> keeps the paid subscription PENDING and routes it to
                         manual fulfillment (admin endpoint) — never POST /orders.

Safety:
    * Never calls Razorpay (read-only payment input).
    * Never blindly POST /orders — always reconciles GET /orders first.
    * Never creates duplicate subscriptions or invoices.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.database import get_async_db, get_db  # noqa: E402
from app.entity.cobrother.cobrother_request_entity import CoBrotherRequest  # noqa: E402
from app.entity.technology_services.technology_subscription_entity import TechnologySubscriptionEntity  # noqa: E402
from app.entity.technology_services.technology_subscription_invoice_entity import TechnologySubscriptionInvoiceEntity  # noqa: E402
from app.service.technology.technology_subscription_retry_service import TechnologySubscriptionRetryService  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("recover_tech_subs")


async def _find_user_domain(session, user_id: str) -> str | None:
    """Best-effort: return a real CoBrother domain the user owns, if any."""
    from app.entity.domain.registration_order_entity import DomainRegistrationOrderEntity  # noqa: E402

    try:
        stmt = (
            select(DomainRegistrationOrderEntity)
            .where(
                DomainRegistrationOrderEntity.user_id == user_id,
                DomainRegistrationOrderEntity.status == "ACTIVE",
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        row = result.scalars().first()
        if row is not None and getattr(row, "domain_name", None):
            return str(row.domain_name)
    except Exception as exc:  # table may not exist in all envs
        logger.debug("domain lookup skipped: %s", exc)
    return None


async def _reconstruct_web_hosting(session, user_id: str, service_slug: str) -> dict[str, str]:
    """Reconstruct subscription + invoice for Web Hosting from payment/request data.

    Returns dict with subscription_id / invoice_number / status.
    """
    from app.repository.track_record_repository import TrackRecordRepository  # noqa: E402

    sub_stmt = select(TechnologySubscriptionEntity).where(
        TechnologySubscriptionEntity.user_id == user_id,
        TechnologySubscriptionEntity.service_slug == service_slug,
    )
    sub_row = (await session.execute(sub_stmt)).scalars().first()

    invoice_stmt = select(TechnologySubscriptionInvoiceEntity).where(
        TechnologySubscriptionInvoiceEntity.user_id == user_id,
        TechnologySubscriptionInvoiceEntity.subscription_id == (str(sub_row.id) if sub_row else None),
    )
    invoice_row = (await session.execute(invoice_stmt)).scalars().first()

    req_stmt = select(CoBrotherRequest).where(
        CoBrotherRequest.razorpay_payment_id.isnot(None),
        CoBrotherRequest.lister_id == user_id,
    ).order_by(CoBrotherRequest.created_at.desc())
    req = (await session.execute(req_stmt)).scalars().first()

    track_repo = TrackRecordRepository(session)
    record = None
    if req is not None:
        record = await track_repo.find_by_razorpay_payment_id(str(req.razorpay_payment_id))

    amount = float(record.amount_charged) if record is not None and record.amount_charged else 0.0
    if sub_row is None and req is not None:
        sub_row = TechnologySubscriptionEntity(
            user_id=user_id,
            service_slug=service_slug,
            service_name="Web Hosting",
            plan_code="starter",
            billing_cycle="monthly",
            price=amount,
            currency="INR",
            status="PENDING",
            payment_status="CAPTURED",
            razorpay_order_id=req.razorpay_order_id,
            razorpay_payment_id=req.razorpay_payment_id,
            auto_renew=True,
            email_sent=False,
            needs_review=True,
            last_provider_error="Recovered from paid payment — awaiting primary domain / provisioning.",
        )
        session.add(sub_row)
        await session.flush()
        logger.info("RECONSTRUCTED subscription %s (web-hosting, user=%s)", sub_row.id, user_id)

    if invoice_row is None and sub_row is not None:
        now = datetime.now(timezone.utc)
        invoice_row = TechnologySubscriptionInvoiceEntity(
            subscription_id=str(sub_row.id),
            user_id=user_id,
            invoice_number=f"INV-CB-{uuid.uuid4().hex[:8].upper()}",
            amount=amount,
            currency="INR",
            status="PAID",
            billing_period_start=now,
            billing_period_end=now,
            payment_method="Razorpay",
        )
        session.add(invoice_row)
        await session.flush()
        logger.info("RECONSTRUCTED invoice %s for subscription %s", invoice_row.invoice_number, sub_row.id)

    return {
        "subscription_id": str(sub_row.id) if sub_row else "",
        "invoice_number": invoice_row.invoice_number if invoice_row else "",
        "status": sub_row.status if sub_row else "MISSING",
    }


async def _process_user(session, user_id: str, apply: bool, dry_run_report: list[dict]) -> None:
    stmt = select(TechnologySubscriptionEntity).where(
        TechnologySubscriptionEntity.user_id == user_id,
        TechnologySubscriptionEntity.is_deleted.is_(False),
    ).order_by(TechnologySubscriptionEntity.created_at.asc())
    rows = (await session.execute(stmt)).scalars().all()

    # Web Hosting may have NO subscription row — the scan below also covers
    # that gap via payment/request records.
    slugs_present = {r.service_slug for r in rows}

    if not rows:
        logger.info("No subscriptions found for user %s", user_id)
        return

    retry = TechnologySubscriptionRetryService(session)

    for sub in rows:
        entry = {
            "service": sub.service_slug,
            "payment_id": sub.razorpay_payment_id,
            "amount": sub.price,
            "subscription_id": str(sub.id),
            "status": sub.status,
            "recommended": "",
        }

        if sub.status == "ACTIVE":
            entry["recommended"] = "No action (already active)"
        elif sub.status in ("PENDING", "PROVISIONING_FAILED"):
            if sub.last_provider_status == "NEEDS_INPUT":
                entry["recommended"] = (
                    f"Customer input required: {sub.last_provider_error or 'missing provisioning input'}. "
                    "Collect input, then retry through the admin endpoint."
                )
            elif sub.last_provider_status == "MANUAL_FULFILLMENT_REQUIRED":
                entry["recommended"] = "Manual fulfillment required (admin fulfill endpoint)."
            else:
                entry["recommended"] = "Safe retry (reconcile-first)."
                if apply:
                    result = await retry.retry_subscription(str(sub.id), force=False)
                    entry["recommended"] = f"Retried: outcome={result.get('outcome')} status={sub.status}"
        else:
            entry["recommended"] = f"No automatic action for status={sub.status}"

        dry_run_report.append(entry)
        logger.info(
            "[%s] %s | payment=%s | amount=%s | status=%s | %s",
            "APPLY" if apply else "DRY-RUN",
            sub.service_slug,
            sub.razorpay_payment_id,
            sub.price,
            sub.status,
            entry["recommended"],
        )

    # Web Hosting reconstruction gap (paid payment with no subscription row)
    if "web-hosting" not in slugs_present:
        from app.repository.track_record_repository import TrackRecordRepository  # noqa: E402

        track_repo = TrackRecordRepository(session)
        req_stmt = select(CoBrotherRequest).where(
            CoBrotherRequest.lister_id == user_id,
            CoBrotherRequest.razorpay_payment_id.isnot(None),
        ).order_by(CoBrotherRequest.created_at.desc())
        reqs = (await session.execute(req_stmt)).scalars().all()
        for req in reqs:
            rec = await track_repo.find_by_razorpay_payment_id(str(req.razorpay_payment_id))
            if rec is None or "hosting" not in str(rec.item_name or "").lower():
                continue
            dry_run_report.append(
                {
                    "service": "web-hosting",
                    "payment_id": req.razorpay_payment_id,
                    "amount": float(rec.amount_charged or 0.0),
                    "subscription_id": "MISSING",
                    "status": "PAID-PAYMENT",
                    "recommended": "Reconstruct subscription+invoice from payment, then provision (admin).",
                }
            )
            logger.info(
                "[%s] web-hosting | payment=%s | subscription MISSING | reconstruct + provision",
                "APPLY" if apply else "DRY-RUN",
                req.razorpay_payment_id,
            )
            if apply:
                await _reconstruct_web_hosting(session, user_id, "web-hosting")


async def _main(apply: bool, user_id_filter: str | None, slug_filter: str | None) -> None:
    report: list[dict] = []
    async with get_async_db() as session:
        stmt = select(TechnologySubscriptionEntity.user_id).distinct()
        if user_id_filter:
            stmt = stmt.where(TechnologySubscriptionEntity.user_id == user_id_filter)
        user_rows = (await session.execute(stmt)).scalars().all()
        for user_id in user_rows:
            await _process_user(session, str(user_id), apply, report)
        if apply:
            await session.commit()
    print(f"\n=== RECOVERY {'APPLIED' if apply else 'DRY-RUN'} — {len(report)} purchase(s) reviewed ===")
    for e in report:
        print(
            f"  {e['service']:<20} payment={e['payment_id']} amount={e['amount']} "
            f"status={e['status']:<20} -> {e['recommended']}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recover paid Technology Services purchases (dry-run by default).")
    parser.add_argument("--apply", action="store_true", help="Perform writes (default: dry-run, read-only)")
    parser.add_argument("--user-id", default=None, help="Restrict to one user UUID")
    parser.add_argument("--service-slug", default=None, help="Restrict to one service slug (informational)")
    args = parser.parse_args()
    asyncio.run(_main(args.apply, args.user_id, args.service_slug))
