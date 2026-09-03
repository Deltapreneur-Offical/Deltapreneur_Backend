"""Correct historical Technology Purchase track records that lie.

Finds Technology Purchase track records where the record says
PROVISIONED/SUCCESS but the authoritative source (the
technology_subscriptions row) says otherwise, and rewrites them to match
reality — the track record is NEVER treated as its own source of truth.

DEFAULT MODE: --dry-run (read-only). Only ``--apply`` performs writes.

Criteria (matches the production invariant):
    track = Technology Purchase AND fulfillment_status = PROVISIONED
        AND overall_status = SUCCESS
        AND (subscription is missing
             OR subscription.status != ACTIVE
             OR subscription.provider_subscription_id IS NULL)

Usage:
    python scripts/correct_technology_track_records.py [--apply] [--user-id <uuid>]

Before/after audit rows are printed always; with --apply they are also
written to a JSON audit file (scripts/output/track_record_corrections.json).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.database import get_async_db  # noqa: E402
from app.entity.technology_services.technology_subscription_entity import TechnologySubscriptionEntity  # noqa: E402
from app.service.platform.track_record_service import (  # noqa: E402
    FulfillmentStatus,
    OverallStatus,
    TrackRecordCategory,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("correct_tech_track")


async def _main(apply: bool, user_id_filter: str | None) -> None:
    from app.repository.track_record_repository import TrackRecordRepository  # noqa: E402
    from app.service.platform.track_record_service import TrackRecordService  # noqa: E402

    audit: list[dict] = []
    async with get_async_db() as session:
        track_repo = TrackRecordRepository(session)
        track_svc = TrackRecordService(session)

        stmt = select(TechnologySubscriptionEntity).where(
            TechnologySubscriptionEntity.is_deleted.is_(False)
        )
        if user_id_filter:
            stmt = stmt.where(TechnologySubscriptionEntity.user_id == user_id_filter)
        subs = (await session.execute(stmt)).scalars().all()

        subs_by_payment: dict[str, TechnologySubscriptionEntity] = {}
        subs_by_order: dict[str, TechnologySubscriptionEntity] = {}
        for s in subs:
            if s.razorpay_payment_id:
                subs_by_payment[s.razorpay_payment_id] = s
            if s.razorpay_order_id:
                subs_by_order[s.razorpay_order_id] = s

        # Scan all Technology Purchase track records (paginate over the full set).
        records, _ = await track_repo.query_records(
            category=TrackRecordCategory.TECHNOLOGY_PURCHASE,
            page=1,
            limit=100000,
        )
        violations = 0

        for rec in records:
            if not (
                rec.category == TrackRecordCategory.TECHNOLOGY_PURCHASE
                and rec.fulfillment_status == FulfillmentStatus.PROVISIONED
                and rec.overall_status == OverallStatus.SUCCESS
            ):
                continue

            sub = None
            if rec.razorpay_payment_id:
                sub = subs_by_payment.get(rec.razorpay_payment_id)
            if sub is None and rec.razorpay_order_id:
                sub = subs_by_order.get(rec.razorpay_order_id)

            if sub is not None and sub.status == "ACTIVE" and sub.provider_subscription_id:
                continue  # consistent — leave alone

            violations += 1
            entry = {
                "track_record_id": str(rec.id),
                "internal_order_id": rec.internal_order_id,
                "item_name": rec.item_name,
                "razorpay_order_id": rec.razorpay_order_id,
                "razorpay_payment_id": rec.razorpay_payment_id,
                "before": {
                    "fulfillment_status": rec.fulfillment_status,
                    "overall_status": rec.overall_status,
                    "error_code": rec.error_code,
                    "error_message": rec.error_message,
                },
                "subscription_status": sub.status if sub else "MISSING",
                "provider_subscription_id": sub.provider_subscription_id if sub else None,
                "after": None,
            }

            if sub is not None and sub.status in ("PENDING", "PAYMENT_CAPTURED", "PROVISIONING"):
                entry["after"] = {
                    "fulfillment_status": FulfillmentStatus.IN_PROGRESS,
                    "overall_status": OverallStatus.PENDING,
                    "error_code": None,
                    "error_message": "Corrected: subscription is not ACTIVE.",
                }
            elif sub is not None and sub.status == "PROVISIONING_FAILED":
                entry["after"] = {
                    "fulfillment_status": FulfillmentStatus.FAILED,
                    "overall_status": OverallStatus.FAILED,
                    "error_code": "PROVISIONING_ERROR",
                    "error_message": "Corrected: provider provisioning failed.",
                }
            else:
                entry["after"] = {
                    "fulfillment_status": FulfillmentStatus.IN_PROGRESS,
                    "overall_status": OverallStatus.PENDING,
                    "error_code": None,
                    "error_message": "Corrected: no authoritative ACTIVE subscription with provider id.",
                }

            audit.append(entry)
            logger.info(
                "[%s] track=%s item=%s -> %s/%s (sub=%s, provider_id=%s)",
                "APPLY" if apply else "DRY-RUN",
                rec.internal_order_id,
                rec.item_name,
                entry["after"]["fulfillment_status"],
                entry["after"]["overall_status"],
                entry["after"]["subscription_status"] if "subscription_status" in entry else sub.status if sub else "MISSING",
                sub.provider_subscription_id if sub else None,
            )

            if apply:
                await track_svc.record_paid_attempt(
                    internal_order_id=rec.internal_order_id,
                    category=rec.category,
                    provider_subcategory=rec.provider_subcategory,
                    item_name=rec.item_name,
                    amount_charged=float(rec.amount_charged or 0.0),
                    payment_status=rec.payment_status,
                    razorpay_order_id=rec.razorpay_order_id,
                    razorpay_payment_id=rec.razorpay_payment_id,
                    fulfillment_status=entry["after"]["fulfillment_status"],
                    overall_status=entry["after"]["overall_status"],
                    error_code=entry["after"]["error_code"],
                    error_message=entry["after"]["error_message"],
                    error_source="BACKEND_RECONCILIATION",
                    clear_errors=True,
                )

        if apply:
            await session.commit()

        out_dir = Path("scripts/output")
        if apply:
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / "track_record_corrections.json"
            out_file.write_text(
                json.dumps(
                    {
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "mode": "apply",
                        "corrections": audit,
                    },
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            logger.info("Audit written to %s", out_file)

    print(f"\n=== TRACK CORRECTION {'APPLIED' if apply else 'DRY-RUN'} — {violations} violation(s) ===")
    for e in audit:
        print(
            f"  track={e['internal_order_id']} item={e['item_name']} "
            f"before={e['before']['fulfillment_status']}/{e['before']['overall_status']} "
            f"after={e['after']['fulfillment_status']}/{e['after']['overall_status']}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Correct Technology Purchase track records (dry-run by default)."
    )
    parser.add_argument("--apply", action="store_true", help="Perform writes (default: dry-run, read-only)")
    parser.add_argument("--user-id", default=None, help="Restrict to one user UUID")
    args = parser.parse_args()
    asyncio.run(_main(args.apply, args.user_id))
