"""Inspect / backfill a captured technology payment without charging again.

Default mode is read-only. Use --apply only after reviewing the printed state.

This script NEVER creates a Razorpay payment or charges the customer.
It NEVER creates a ResellPortal order; the retry worker does provisioning.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import or_, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.entity.platform.track_record_entity import TrackRecord  # noqa: E402
from app.entity.technology_services.technology_subscription_entity import (  # noqa: E402
    TechnologySubscriptionEntity,
)
from app.entity.technology_services.technology_subscription_invoice_entity import (  # noqa: E402
    TechnologySubscriptionInvoiceEntity,
)
from app.entity.user.app_user import AppUser  # noqa: E402
from app.service.platform.track_record_service import PaymentStatus  # noqa: E402


def _slug_from_track(track: TrackRecord) -> str:
    raw = str(track.item_id or "").strip().lower()
    if raw and " " not in raw and len(raw) <= 80 and not re.fullmatch(r"[0-9a-f-]{36}", raw):
        return raw
    name = str(track.item_name or "technology-service").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    return slug or "technology-service"


async def _run(*, payment_id: str, order_id: str | None, apply: bool) -> dict:
    payment_id = payment_id.strip()
    order_id = (order_id or "").strip() or None
    async with AsyncSessionLocal() as session:
        sub_filters = [TechnologySubscriptionEntity.is_deleted.is_(False)]
        id_filters = [TechnologySubscriptionEntity.razorpay_payment_id == payment_id]
        if order_id:
            id_filters.append(TechnologySubscriptionEntity.razorpay_order_id == order_id)
        sub_stmt = select(TechnologySubscriptionEntity).where(*sub_filters, or_(*id_filters))
        subs = list((await session.execute(sub_stmt)).scalars().all())

        track_stmt = select(TrackRecord).where(
            or_(
                TrackRecord.razorpay_payment_id == payment_id,
                *( [TrackRecord.razorpay_order_id == order_id] if order_id else [] ),
            )
        )
        tracks = list((await session.execute(track_stmt)).scalars().all())

        invs: list[TechnologySubscriptionInvoiceEntity] = []
        if subs:
            inv_stmt = select(TechnologySubscriptionInvoiceEntity).where(
                TechnologySubscriptionInvoiceEntity.subscription_id.in_([str(s.id) for s in subs])
            )
            invs = list((await session.execute(inv_stmt)).scalars().all())

        report = {
            "mode": "read-only",
            "applied": False,
            "razorpay_payment_id": payment_id,
            "razorpay_order_id": order_id or (tracks[0].razorpay_order_id if tracks else None),
            "customer": None,
            "service": None,
            "payment": None,
            "my_purchases_would_show": False,
            "subscriptions": [
                {
                    "id": str(s.id),
                    "user_id": s.user_id,
                    "service_slug": s.service_slug,
                    "service_name": s.service_name,
                    "status": s.status,
                    "payment_status": s.payment_status,
                    "provider_order_id": s.provider_order_id,
                    "provider_subscription_id": s.provider_subscription_id,
                    "email_sent": s.email_sent,
                    "confirmation_sent": s.confirmation_sent,
                    "next_retry_at": s.next_retry_at.isoformat() if s.next_retry_at else None,
                    "last_provider_status": s.last_provider_status,
                    "last_provider_error": s.last_provider_error,
                    "price": float(s.price or 0),
                }
                for s in subs
            ],
            "invoices": [
                {
                    "id": str(i.id),
                    "invoice_number": i.invoice_number,
                    "amount": float(i.amount or 0),
                    "status": i.status,
                    "subscription_id": i.subscription_id,
                }
                for i in invs
            ],
            "track_records": [
                {
                    "id": str(t.id),
                    "item_name": t.item_name,
                    "item_id": t.item_id,
                    "category": t.category,
                    "buyer_name": t.buyer_name,
                    "buyer_email": t.buyer_email,
                    "buyer_user_id": str(t.buyer_user_id) if t.buyer_user_id else None,
                    "payment_status": t.payment_status,
                    "fulfillment_status": t.fulfillment_status,
                    "overall_status": t.overall_status,
                    "amount_charged": float(t.amount_charged or 0),
                    "subtotal_ex_gst": float(t.subtotal_ex_gst) if t.subtotal_ex_gst is not None else None,
                    "gst_amount": float(t.gst_amount) if t.gst_amount is not None else None,
                    "currency": t.currency,
                    "razorpay_payment_id": t.razorpay_payment_id,
                    "razorpay_order_id": t.razorpay_order_id,
                    "error_code": t.error_code,
                    "error_message": t.error_message,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in tracks
            ],
        }
        if tracks:
            t0 = next((t for t in tracks if t.razorpay_payment_id == payment_id), tracks[0])
            report["customer"] = {
                "name": t0.buyer_name,
                "email": t0.buyer_email,
                "user_id": str(t0.buyer_user_id) if t0.buyer_user_id else None,
            }
            if t0.buyer_user_id:
                user = (
                    await session.execute(select(AppUser).where(AppUser.id == t0.buyer_user_id))
                ).scalar_one_or_none()
                if user is not None:
                    report["customer"]["account_email"] = user.email
                    report["customer"]["account_name"] = " ".join(
                        p for p in [getattr(user, "firstname", None), getattr(user, "lastname", None)] if p
                    ) or None
            report["service"] = {
                "item_name": t0.item_name,
                "item_id": t0.item_id,
                "category": t0.category,
            }
            report["payment"] = {
                "track_payment_status": t0.payment_status,
                "amount_charged": float(t0.amount_charged or 0),
                "subtotal_ex_gst": float(t0.subtotal_ex_gst) if t0.subtotal_ex_gst is not None else None,
                "gst_amount": float(t0.gst_amount) if t0.gst_amount is not None else None,
                "currency": t0.currency,
            }
        report["my_purchases_would_show"] = any(
            str(s.payment_status or "").upper() == "CAPTURED" or str(s.status or "").upper() in {"ACTIVE", "PENDING", "PAYMENT_CAPTURED", "PROVISIONING", "PROVISIONING_FAILED"}
            for s in subs
        )

        if not apply:
            return report

        from app.service.cart.cart_checkout_service import (  # noqa: E402
            _tech_backoff_for,
            _tech_sub_periods,
            _technology_idempotency_key,
        )
        from app.service.platform.track_record_service import (  # noqa: E402
            FulfillmentStatus,
            OverallStatus,
            TrackRecordService,
        )

        track = next((t for t in tracks if t.razorpay_payment_id == payment_id), tracks[0] if tracks else None)
        if track is None:
            report["error"] = "No Track Record found for this payment; refusing to invent a purchase."
            return report
        if str(track.payment_status or "").upper() not in {PaymentStatus.CAPTURED, "CAPTURED", "PAID"}:
            report["error"] = f"Track Record payment_status={track.payment_status}; refusing to backfill."
            return report
        if not track.buyer_user_id:
            report["error"] = "Track Record has no buyer_user_id; refusing to backfill."
            return report

        if not subs:
            slug = _slug_from_track(track)
            start, end = _tech_sub_periods("monthly")
            now = datetime.now(timezone.utc)
            paid = float(track.amount_charged or 0)
            sub = TechnologySubscriptionEntity(
                user_id=str(track.buyer_user_id),
                service_slug=slug,
                service_name=str(track.item_name or slug),
                plan_code="starter",
                billing_cycle="monthly",
                price=float(track.subtotal_ex_gst or paid),
                currency=str(track.currency or "INR"),
                status="PENDING",
                payment_status="CAPTURED",
                idempotency_key=_technology_idempotency_key(payment_id, slug),
                provision_attempts=1,
                last_provision_attempt_at=now,
                last_provider_status="PROVISIONING_PENDING",
                last_provider_error=track.error_message or "Provisioning pending after captured payment.",
                next_retry_at=now + _tech_backoff_for(1),
                razorpay_order_id=track.razorpay_order_id or order_id,
                razorpay_payment_id=payment_id,
                current_period_start=start,
                current_period_end=end,
                auto_renew=True,
                email_sent=True,  # customer already received the activation email
                confirmation_sent=False,
                needs_review=False,
            )
            session.add(sub)
            await session.flush()
            invoice = TechnologySubscriptionInvoiceEntity(
                subscription_id=str(sub.id),
                user_id=str(track.buyer_user_id),
                invoice_number=f"INV-CB-{uuid.uuid4().hex[:8].upper()}",
                amount=paid,
                currency=str(track.currency or "INR"),
                status="PAID",
                billing_period_start=start,
                billing_period_end=end,
                payment_method="Razorpay",
            )
            session.add(invoice)
            subs = [sub]
            invs = [invoice]
            report["created_subscription_id"] = str(sub.id)
            report["created_invoice_number"] = invoice.invoice_number
        else:
            for sub in subs:
                if str(sub.status or "").upper() != "ACTIVE":
                    sub.status = "PENDING"
                    sub.payment_status = "CAPTURED"
                    sub.next_retry_at = sub.next_retry_at or (
                        datetime.now(timezone.utc) + timedelta(minutes=5)
                    )
                    sub.last_provider_status = sub.last_provider_status or "PROVISIONING_PENDING"
            invoiced = {i.subscription_id for i in invs}
            for sub in subs:
                if str(sub.id) in invoiced:
                    continue
                start, end = _tech_sub_periods(sub.billing_cycle or "monthly")
                invoice = TechnologySubscriptionInvoiceEntity(
                    subscription_id=str(sub.id),
                    user_id=str(sub.user_id),
                    invoice_number=f"INV-CB-{uuid.uuid4().hex[:8].upper()}",
                    amount=float(track.amount_charged or sub.price or 0),
                    currency=str(track.currency or sub.currency or "INR"),
                    status="PAID",
                    billing_period_start=start,
                    billing_period_end=end,
                    payment_method="Razorpay",
                )
                session.add(invoice)
                invs.append(invoice)
                report.setdefault("created_invoice_numbers", []).append(invoice.invoice_number)

        track_service = TrackRecordService(session)
        await track_service.record_paid_attempt(
            internal_order_id=track.internal_order_id,
            category=track.category,
            provider_subcategory=track.provider_subcategory,
            item_name=track.item_name,
            item_id=track.item_id,
            buyer_user_id=track.buyer_user_id,
            amount_charged=float(track.amount_charged or 0),
            currency=track.currency or "INR",
            subtotal_ex_gst=float(track.subtotal_ex_gst) if track.subtotal_ex_gst is not None else None,
            gst_amount=float(track.gst_amount) if track.gst_amount is not None else None,
            payment_status=PaymentStatus.CAPTURED,
            razorpay_order_id=track.razorpay_order_id,
            razorpay_payment_id=track.razorpay_payment_id,
            fulfillment_status=FulfillmentStatus.IN_PROGRESS,
            overall_status=OverallStatus.PENDING,
            error_code=track.error_code,
            error_message=track.error_message,
            error_source=track.error_source,
        )
        await session.commit()
        report["applied"] = True
        report["subscriptions"] = [
            {"id": str(s.id), "status": s.status, "payment_status": s.payment_status}
            for s in subs
        ]
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payment-id", required=True, help="Razorpay payment id (pay_...)")
    parser.add_argument("--order-id", default=None, help="Optional Razorpay order id")
    parser.add_argument("--apply", action="store_true", help="Persist missing paid subscription/invoice")
    args = parser.parse_args()
    report = asyncio.run(_run(payment_id=args.payment_id, order_id=args.order_id, apply=args.apply))
    print(report)
    if report.get("error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
