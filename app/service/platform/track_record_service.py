"""Service for creating, updating, and querying Track Records across all platform purchases."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.platform.track_record_entity import TrackRecord
from app.repository.track_record_repository import TrackRecordRepository
import app.entity.user.app_user  # noqa: F401
import app.entity.coventure.partner_entity  # noqa: F401

logger = logging.getLogger(__name__)

# ── Sync / network safety bounds ────────────────────────────────────────────
# The admin page triggers a full historical backfill on load (fire-and-forget).
# These bounds keep any single sync / enrichment request from hanging on a slow
# or unreachable Razorpay API — a dead network must never freeze the page.
_SYNC_LOCK = asyncio.Lock()
PAYMENT_MODE_RESOLVE_TIMEOUT_SECONDS = 8.0
RAZORPAY_RECENT_PAYMENTS_TIMEOUT_SECONDS = 20.0

# Capture likely FQDNs from Razorpay notes / descriptions (e.g. "neeligin.com", "foo.co.in").
_FQDN_RE = re.compile(
    r"\b([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])+){1,})\b",
    re.IGNORECASE,
)
_EMAIL_PROVIDER_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "yahoo.co.in",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "icloud.com",
        "me.com",
        "proton.me",
        "protonmail.com",
        "rediffmail.com",
        "aol.com",
    }
)
_NON_PRODUCT_HOSTS = frozenset(
    {
        "razorpay.com",
        "openprovider.eu",
        "openprovider.nl",
        "cobrother.com",
        "localhost",
        "example.com",
        "example.org",
    }
)


def _is_plausible_purchased_domain(host: str) -> bool:
    h = str(host or "").strip().lower().rstrip(".")
    if not h or "@" in h or "." not in h or " " in h:
        return False
    if h.startswith("www."):
        h = h[4:]
    if h in _EMAIL_PROVIDER_DOMAINS or h in _NON_PRODUCT_HOSTS:
        return False
    if any(h.endswith("." + d) for d in ("razorpay.com", "amazonaws.com", "openprovider.eu")):
        return False
    label = h.split(".", 1)[0]
    if label in {"api", "www", "mail", "cdn", "static", "assets"}:
        return False
    if len(h) > 253:
        return False
    return True


def _extract_fqdns_from_text(text: str) -> list[str]:
    found: list[str] = []
    raw = str(text or "")
    if not raw.strip():
        return found
    # Explicit cart label: "Domain Registration: neeligin.com"
    for marker in ("Domain Registration:", "domain registration:", "Domain:"):
        if marker in raw:
            tail = raw.split(marker, 1)[1]
            # Take until comma / (+N more) / newline
            piece = re.split(r"[,\n(+]", tail, maxsplit=1)[0].strip()
            if _is_plausible_purchased_domain(piece):
                found.append(piece.lower())
    for match in _FQDN_RE.findall(raw):
        candidate = str(match).lower().rstrip(".")
        if _is_plausible_purchased_domain(candidate):
            found.append(candidate)
    # Dedupe preserve order
    out: list[str] = []
    seen: set[str] = set()
    for d in found:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def extract_domains_from_razorpay_payload(
    *,
    pay: dict[str, Any],
    order: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Best-effort domain recovery from Razorpay payment + order metadata."""
    blobs: list[str] = []
    for src in (pay.get("notes") or {}, (order or {}).get("notes") or {}):
        if not isinstance(src, dict):
            continue
        for key in (
            "domainName",
            "domain",
            "domains",
            "items",
            "items_summary",
            "categories",
            "description",
            "productName",
            "fullDomain",
        ):
            val = src.get(key)
            if val is not None and str(val).strip():
                blobs.append(str(val))
    for key in ("description",):
        val = pay.get(key)
        if val is not None and str(val).strip():
            blobs.append(str(val))
    if order:
        for key in ("description", "receipt"):
            val = order.get(key)
            if val is not None and str(val).strip():
                blobs.append(str(val))

    found: list[str] = []
    for blob in blobs:
        found.extend(_extract_fqdns_from_text(blob))
    out: list[str] = []
    seen: set[str] = set()
    for d in found:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def domain_display_from_item_name(item_name: Optional[str]) -> Optional[str]:
    """Public helper: prefer a real FQDN over Payment # placeholders."""
    name = str(item_name or "").strip()
    if not name or name.startswith("Payment #") or name.startswith("Unprovisioned"):
        return None
    fqdns = _extract_fqdns_from_text(name)
    if fqdns:
        return ", ".join(fqdns)
    if "." in name and _is_plausible_purchased_domain(name.split(",")[0].strip()):
        return name.split(",")[0].strip().lower()
    return None


class TrackRecordCategory:
    DOMAIN_REGISTRATION_OPENPROVIDER = "Domain Registration (OpenProvider)"
    DOMAIN_REGISTRATION_RESELLER = "Domain Registration (Reseller)"
    DOMAIN_REGISTRATION = "Domain Registration (OpenProvider)"
    DOMAIN_MARKETPLACE = "Domain Marketplace"
    TECHNOLOGY_PURCHASE = "Technology Purchase"
    # Provider-powered technology services (VPN, Appointment Booking,
    # AI Business Suite, Invoice AI, Link in Bio, …) are subscriptions/
    # services, NOT one-time software products. They must never be filed
    # under Technology Purchase or Domain Registration.
    TECHNOLOGY_SERVICES = "Technology Services"
    VENTURE_DEAL_PAYMENT = "Venture / Deal Payment"
    DOMAIN_ADDON_EMAIL = "Domain Addon (Email)"
    DOMAIN_ADDON_SSL = "Domain Addon (SSL)"
    DOMAIN_RENEWAL = "Domain Renewal"
    DOMAIN_TRANSFER = "Domain Transfer"
    OPENPROVIDER_MANAGED_ACQUISITION = "OpenProvider Managed Acquisition"
    OPERATIONS = "Operations"
    OTHER = "Other"


class OverallStatus:
    SUCCESS = "Success"
    FAILED = "Failed"
    PENDING = "Pending"
    PARTIAL = "Partial"
    REFUNDED = "Refunded"
    EXPIRED = "Expired"
    CANCELLED = "Cancelled"


class PaymentStatus:
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    PENDING = "PENDING"


class FulfillmentStatus:
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    PROVISIONED = "PROVISIONED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class TrackRecordService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = TrackRecordRepository(session)

    @staticmethod
    def generate_internal_order_id(prefix: str = "TRK") -> str:
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        random_suffix = str(uuid.uuid4().hex[:6]).upper()
        return f"{prefix}-{timestamp_str}-{random_suffix}"

    async def record_paid_attempt(
        self,
        *,
        internal_order_id: Optional[str] = None,
        cart_batch_id: Optional[str] = None,
        category: str = TrackRecordCategory.OTHER,
        provider_subcategory: Optional[str] = "OpenProvider",
        item_name: str,
        item_id: Optional[str] = None,
        quantity_years: int = 1,
        buyer_name: Optional[str] = None,
        buyer_email: Optional[str] = None,
        buyer_phone: Optional[str] = None,
        buyer_user_id: Optional[uuid.UUID] = None,
        amount_charged: float = 0.0,
        currency: str = "INR",
        subtotal_ex_gst: Optional[float] = None,
        gst_amount: Optional[float] = None,
        payment_status: str = PaymentStatus.CAPTURED,
        razorpay_order_id: Optional[str] = None,
        razorpay_payment_id: Optional[str] = None,
        razorpay_refund_id: Optional[str] = None,
        fulfillment_status: str = FulfillmentStatus.IN_PROGRESS,
        overall_status: str = OverallStatus.PENDING,
        openprovider_domain_id: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        error_source: Optional[str] = None,
        notes: Optional[str] = None,
        admin_deep_link: Optional[str] = None,
        created_at: Optional[datetime] = None,
        clear_errors: bool = False,
    ) -> TrackRecord:
        """Create or update a single Track Record for a paid transaction attempt.

        When ``clear_errors`` is True the error fields are treated as
        authoritative: they are set to exactly what the caller passed (including
        None, which wipes stale diagnostics from earlier states).
        """
        try:
            record: Optional[TrackRecord] = None

            if internal_order_id:
                record = await self._repo.find_by_internal_order_id(internal_order_id)
            # Only reuse by payment id when no explicit internal id was supplied.
            # Cart checkouts share one Razorpay payment across multiple line items.
            if not record and razorpay_payment_id and not internal_order_id:
                record = await self._repo.find_by_razorpay_payment_id(razorpay_payment_id)

            if not record:
                record = TrackRecord(
                    internal_order_id=internal_order_id or self.generate_internal_order_id(),
                    cart_batch_id=cart_batch_id,
                    category=category,
                    provider_subcategory=provider_subcategory,
                    item_name=item_name,
                    item_id=str(item_id) if item_id else None,
                    quantity_years=quantity_years,
                    buyer_name=buyer_name,
                    buyer_email=buyer_email,
                    buyer_phone=buyer_phone,
                    buyer_user_id=buyer_user_id,
                    amount_charged=amount_charged,
                    currency=currency,
                    subtotal_ex_gst=subtotal_ex_gst,
                    gst_amount=gst_amount,
                    payment_status=payment_status,
                    razorpay_order_id=razorpay_order_id,
                    razorpay_payment_id=razorpay_payment_id,
                    razorpay_refund_id=razorpay_refund_id,
                    fulfillment_status=fulfillment_status,
                    overall_status=overall_status,
                    openprovider_domain_id=openprovider_domain_id,
                    error_code=error_code,
                    error_message=error_message,
                    error_source=error_source,
                    notes=notes,
                    admin_deep_link=admin_deep_link,
                )
                if created_at:
                    record.created_at = created_at
            else:
                # Update existing record
                if created_at:
                    record.created_at = created_at
                if cart_batch_id:
                    record.cart_batch_id = cart_batch_id
                if category:
                    record.category = category
                if provider_subcategory:
                    record.provider_subcategory = provider_subcategory
                if item_name:
                    is_current_generic = not record.item_name or record.item_name.startswith("Payment #") or record.item_name.startswith("Unprovisioned") or record.item_name in ("Item", "Domain listing")
                    is_new_generic = item_name.startswith("Payment #") or item_name.startswith("Unprovisioned") or item_name in ("Item", "Domain listing")
                    if is_current_generic or not is_new_generic:
                        record.item_name = item_name
                if item_id:
                    record.item_id = str(item_id)
                if buyer_name:
                    record.buyer_name = buyer_name
                if buyer_email:
                    record.buyer_email = buyer_email
                if buyer_phone:
                    record.buyer_phone = buyer_phone
                if buyer_user_id:
                    record.buyer_user_id = buyer_user_id
                if amount_charged > 0:
                    record.amount_charged = amount_charged
                if payment_status:
                    record.payment_status = payment_status
                if razorpay_order_id:
                    record.razorpay_order_id = razorpay_order_id
                if razorpay_payment_id:
                    record.razorpay_payment_id = razorpay_payment_id
                if razorpay_refund_id:
                    record.razorpay_refund_id = razorpay_refund_id
                # ── Success preservation ───────────────────────────────────────
                # A confirmed-successful record (PROVISIONED / Success, or a
                # real OpenProvider id) must NEVER be downgraded to a stale
                # intermediate state (IN_PROGRESS / NOT_STARTED) just because a
                # sync/recovery path re-read a momentarily PAYMENT_COMPLETED /
                # REGISTRATION_PENDING order row. Real failures (FAIL token,
                # error_code) and reversed states (Refund/Cancel/Expired) still
                # overwrite as before.
                _prev_ful = str(record.fulfillment_status or "").upper()
                _prev_overall = str(record.overall_status or "").upper()
                _prev_success = (
                    "PROVISIONED" in _prev_ful
                    or "ACTIVE" in _prev_ful
                    or "COMPLETED" in _prev_ful
                ) and "SUCCESS" in _prev_overall
                _new_intermediate = str(fulfillment_status or "").upper() in (
                    "IN_PROGRESS",
                    "NOT_STARTED",
                    "PENDING",
                )
                _passed_tokens = str(overall_status or "").upper()
                _keep_success = (
                    _prev_success
                    and _new_intermediate
                    and not error_code
                    and not any(
                        tok in _passed_tokens
                        for tok in ("REFUND", "CANCEL", "EXPIRED", "FAIL")
                    )
                )
                if fulfillment_status and not _keep_success:
                    record.fulfillment_status = fulfillment_status
                if overall_status and not _keep_success:
                    record.overall_status = overall_status
                if openprovider_domain_id:
                    record.openprovider_domain_id = openprovider_domain_id
                if clear_errors:
                    # Sync flows rebuild the whole status from the order, so the
                    # error fields are authoritative — write them verbatim so a
                    # recovered (non-failed) state wipes stale diagnostics.
                    record.error_code = error_code
                    record.error_message = error_message
                    record.error_source = error_source
                else:
                    if error_code:
                        record.error_code = error_code
                    if error_message:
                        record.error_message = error_message
                    if error_source:
                        record.error_source = error_source
                # Clear stale diagnostics once registration is truly provisioned.
                if (
                    fulfillment_status
                    and "PROVISIONED" in str(fulfillment_status).upper()
                    and not error_code
                ):
                    record.error_code = None
                    record.error_message = None
                    record.error_source = None
                if notes:
                    record.notes = notes

            # Automatic overall status determination
            pay_st = str(record.payment_status or "").upper()
            ful_st = str(record.fulfillment_status or "").upper()

            # Preserve an explicitly-passed terminal reconciled state —
            # Expired/Cancelled (abandoned unpaid attempt) or Refunded
            # (reversed order) — the generic rules below would downgrade them
            # to PENDING or SUCCESS.
            _passed_overall = str(overall_status or "").upper()
            if (
                "EXPIRED" in _passed_overall
                or "CANCELLED" in _passed_overall
                or "REFUND" in _passed_overall
            ):
                record.overall_status = overall_status
            elif record.razorpay_refund_id or "REFUND" in pay_st:
                record.overall_status = OverallStatus.REFUNDED
            elif "FAIL" in pay_st or "FAIL" in ful_st or bool(record.error_code):
                record.overall_status = OverallStatus.FAILED
            elif "CAPTURED" in pay_st or "PAID" in pay_st or "SUCCESS" in pay_st:
                if "PROVISIONED" in ful_st or "COMPLETED" in ful_st or "SUCCESS" in ful_st or "ACTIVE" in ful_st:
                    record.overall_status = OverallStatus.SUCCESS
                elif "PARTIAL" in ful_st:
                    record.overall_status = OverallStatus.PARTIAL
                elif "FAIL" in ful_st:
                    record.overall_status = OverallStatus.FAILED
                else:
                    record.overall_status = OverallStatus.PENDING
            else:
                record.overall_status = OverallStatus.PENDING

            await self._repo.save(record)
            logger.info(
                "track_record.saved internal_order_id=%s payment_id=%s category=%s item=%s",
                record.internal_order_id,
                record.razorpay_payment_id,
                record.category,
                record.item_name,
            )
            return record
        except Exception as exc:
            logger.error("Failed to record track_record: %s", exc, exc_info=True)
            raise

    async def update_fulfillment(
        self,
        internal_order_id: str,
        *,
        fulfillment_status: str,
        overall_status: Optional[str] = None,
        openprovider_domain_id: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        error_source: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[TrackRecord]:
        try:
            record = await self._repo.find_by_internal_order_id(internal_order_id)
            if not record:
                return None

            record.fulfillment_status = fulfillment_status
            record.provision_attempts += 1

            if openprovider_domain_id:
                record.openprovider_domain_id = openprovider_domain_id

            if error_code:
                record.error_code = error_code
            if error_message:
                record.error_message = error_message
            if error_source:
                record.error_source = error_source
            if notes:
                record.notes = notes

            pay_st = str(record.payment_status or "").upper()
            ful_st = str(record.fulfillment_status or "").upper()

            if record.razorpay_refund_id or "REFUND" in pay_st:
                record.overall_status = OverallStatus.REFUNDED
            elif "FAIL" in pay_st or "FAIL" in ful_st or bool(record.error_code):
                record.overall_status = OverallStatus.FAILED
            elif "CAPTURED" in pay_st or "PAID" in pay_st or "SUCCESS" in pay_st:
                if "PROVISIONED" in ful_st or "COMPLETED" in ful_st or "SUCCESS" in ful_st or "ACTIVE" in ful_st:
                    record.overall_status = OverallStatus.SUCCESS
                elif "PARTIAL" in ful_st:
                    record.overall_status = OverallStatus.PARTIAL
                elif "FAIL" in ful_st:
                    record.overall_status = OverallStatus.FAILED
                else:
                    record.overall_status = OverallStatus.PENDING
            else:
                record.overall_status = OverallStatus.PENDING

            await self._repo.save(record)
            logger.info(
                "track_record.persisted id=%s internal_id=%s item=%s cat=%s pay_id=%s overall=%s",
                record.id, record.internal_order_id, record.item_name, record.category, record.razorpay_payment_id, record.overall_status,
            )
            return record
        except Exception as exc:
            logger.error("Failed to update track_record fulfillment: %s", exc, exc_info=True)
            return None

    async def list_admin_records(
        self,
        *,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        category: Optional[str] = None,
        overall_status: Optional[str] = None,
        search_term: Optional[str] = None,
        sort_by: str = "timestamp",
        sort_dir: str = "desc",
        page: int = 1,
        limit: int = 20,
    ) -> Tuple[Sequence[TrackRecord], int]:
        return await self._repo.query_records(
            start_date=start_date,
            end_date=end_date,
            category=category,
            overall_status=overall_status,
            search_term=search_term,
            sort_by=sort_by,
            sort_dir=sort_dir,
            page=page,
            limit=limit,
        )

    async def get_by_id(self, record_id: uuid.UUID) -> Optional[TrackRecord]:
        return await self._repo.find_by_id(record_id)

    @staticmethod
    def _registration_order_id_from_track_record(record: TrackRecord) -> uuid.UUID | None:
        """Resolve domain_registration_orders.id from track record identifiers."""
        for raw in (
            getattr(record, "item_id", None),
            getattr(record, "internal_order_id", None),
        ):
            text_val = str(raw or "").strip()
            if not text_val:
                continue
            if text_val.upper().startswith("TRK-REG-"):
                text_val = text_val[8:]
            try:
                return uuid.UUID(text_val)
            except ValueError:
                continue
        return None

    @staticmethod
    def _renewal_state_for_order(order_row: dict) -> str:
        """Actual renewal state from the order's renewal fields.

        Never inferred from registration success. A reversed/failed order has
        no renewal applicable (N/A). A completed renewal (renewal_count >= 1)
        is OK; a renewal payment verified but never completed (last
        last_renewal_payment_id set without a completed count) is FAILED; an
        in-flight renewal order is PENDING; otherwise N/A.
        """
        st = str(order_row.get("status") or "").upper()
        if any(
            tok in st
            for tok in ("REFUND", "CANCEL", "PROVISION_FAILED", "EXPIRED", "PAYMENT_FAILED", "FAIL")
        ):
            return "N/A"
        renewal_count = int(order_row.get("renewal_count") or 0)
        pending = str(order_row.get("pending_renewal_razorpay_order_id") or "").strip()
        last_pay = str(order_row.get("last_renewal_payment_id") or "").strip()
        if renewal_count >= 1:
            return "OK"
        if last_pay:
            # Payment was verified but the renewal never completed (provisioning
            # failed/stuck) — the renewal did not succeed.
            return "FAILED"
        if pending:
            return "PENDING"
        return "N/A"

    async def enrich_records_with_tax_invoices(
        self,
        records: Sequence[TrackRecord],
    ) -> list[dict]:
        """Attach taxInvoiceNumber + registrationOrderId for domain registration rows."""
        from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
        from sqlalchemy import select

        from app.integrations.razorpay import client as rzp_client

        payloads = [r.to_dict() for r in records]
        order_ids: list[uuid.UUID] = []
        index_by_order: dict[uuid.UUID, list[int]] = {}
        # Payment id to use for per-transaction Payment Mode resolution,
        # per payload index (order payment id preferred, else record's own).
        payment_id_by_idx: dict[int, str] = {}
        for idx, record in enumerate(records):
            payloads[idx]["paymentMode"] = None
            payloads[idx]["renewalState"] = "N/A"
            payloads[idx]["businessDetails"] = None
            rec_pid = str(getattr(record, "razorpay_payment_id", None) or "").strip()
            cat = str(getattr(record, "category", "") or "").lower()
            if (
                "domain registration" not in cat
                and "domain marketplace" not in cat
                and "domain transfer" not in cat
            ):
                payloads[idx]["taxInvoiceNumber"] = None
                payloads[idx]["invoiceNumber"] = None
                payloads[idx]["registrationOrderId"] = None
                if rec_pid:
                    payment_id_by_idx[idx] = rec_pid
                continue
            oid = self._registration_order_id_from_track_record(record)
            if oid is None:
                payloads[idx]["taxInvoiceNumber"] = None
                payloads[idx]["invoiceNumber"] = None
                payloads[idx]["registrationOrderId"] = None
                if rec_pid:
                    payment_id_by_idx[idx] = rec_pid
                continue
            order_ids.append(oid)
            index_by_order.setdefault(oid, []).append(idx)
            payloads[idx]["registrationOrderId"] = str(oid)
            payloads[idx]["taxInvoiceNumber"] = None
            payloads[idx]["invoiceNumber"] = None
            if rec_pid:
                payment_id_by_idx[idx] = rec_pid

        await self._enrich_business_details(payloads, records)

        if not order_ids:
            await self._resolve_payment_modes(payment_id_by_idx, payloads, rzp_client)
            return payloads

        unique_ids = list({oid for oid in order_ids})
        result = await self._session.execute(
            select(
                DomainRegistrationOrder.id,
                DomainRegistrationOrder.tax_invoice_number,
                DomainRegistrationOrder.status,
                DomainRegistrationOrder.renewal_count,
                DomainRegistrationOrder.pending_renewal_razorpay_order_id,
                DomainRegistrationOrder.last_renewal_payment_id,
                DomainRegistrationOrder.razorpay_payment_id,
            ).where(DomainRegistrationOrder.id.in_(unique_ids))
        )
        for row in result.all():
            oid, inv, status = row[0], row[1], row[2]
            order_row = {
                "status": status,
                "renewal_count": row[3],
                "pending_renewal_razorpay_order_id": row[4],
                "last_renewal_payment_id": row[5],
            }
            # Display-only suppression: a refunded/reversed order keeps its
            # tax invoice number in the DB (finance/audit) but it is not
            # exposed in admin views. ACTIVE orders show it as before.
            st_upper = str(status or "").upper()
            inv_str = (
                str(inv).strip()
                if inv and "REFUND" not in st_upper
                else None
            )
            renewal_state = self._renewal_state_for_order(order_row)
            order_pid = str(row[6] or "").strip()
            for idx in index_by_order.get(oid, []):
                payloads[idx]["taxInvoiceNumber"] = inv_str
                payloads[idx]["invoiceNumber"] = inv_str
                payloads[idx]["registrationOrderId"] = str(oid)
                payloads[idx]["renewalState"] = renewal_state
                # Prefer the authoritative order payment id for Payment Mode.
                if order_pid:
                    payment_id_by_idx[idx] = order_pid

        await self._resolve_payment_modes(payment_id_by_idx, payloads, rzp_client)

        # ── Domain name enrichment for ALL records with generic item names ──
        # Replace generic "Domain listing" / "Item" / "Domain registration" with
        # the actual domain name looked up from domain_registration_orders via
        # Razorpay payment/order id. Marketplace purchases create records in
        # domain_registration_orders (not domain_listings), so we must query that.
        try:
            from sqlalchemy import bindparam, text

            generic_names = ("Item", "Domain listing", "Domain registration", "domain registration", None, "")
            mkt_indices = [
                idx for idx, payload in enumerate(payloads)
                if "marketplace" in str(payload.get("category", "") or "").lower()
                and payload.get("itemName") in generic_names
            ]
            if mkt_indices:
                mkt_pay_ids: dict[int, str] = {}
                mkt_ord_ids: dict[int, str] = {}
                for idx in mkt_indices:
                    rec = records[idx]
                    pid = str(getattr(rec, "razorpay_payment_id", None) or "").strip()
                    oid = str(getattr(rec, "razorpay_order_id", None) or "").strip()
                    if pid:
                        mkt_pay_ids[idx] = pid
                    if oid:
                        mkt_ord_ids[idx] = oid

                if mkt_pay_ids or mkt_ord_ids:
                    all_pids = sorted(set(mkt_pay_ids.values())) if mkt_pay_ids else []
                    all_ords = sorted(set(mkt_ord_ids.values())) if mkt_ord_ids else []
                    dro_lookup: dict[str, tuple[str, str]] = {}

                    # Query domain_registration_orders — marketplace purchases create
                    # rows here with price_source='marketplace'.
                    if all_pids:
                        sql_pay = text(
                            "SELECT razorpay_payment_id, domain_name, domain_extension "
                            "FROM domain_registration_orders WHERE razorpay_payment_id IN :pids"
                        ).bindparams(bindparam("pids", expanding=True))
                        for row in (await self._session.execute(sql_pay, {"pids": all_pids})).mappings().all():
                            dn = str(row.get("domain_name") or "").strip()
                            de = str(row.get("domain_extension") or "").strip()
                            pid = str(row.get("razorpay_payment_id") or "").strip()
                            if pid and (dn or de):
                                dro_lookup[pid] = (dn, de)

                    if all_ords:
                        sql_ord = text(
                            "SELECT razorpay_order_id, domain_name, domain_extension "
                            "FROM domain_registration_orders WHERE razorpay_order_id IN :oids"
                        ).bindparams(bindparam("oids", expanding=True))
                        for row in (await self._session.execute(sql_ord, {"oids": all_ords})).mappings().all():
                            dn = str(row.get("domain_name") or "").strip()
                            de = str(row.get("domain_extension") or "").strip()
                            oid = str(row.get("razorpay_order_id") or "").strip()
                            if oid and (dn or de):
                                dro_lookup[oid] = (dn, de)

                    # Apply to payloads
                    for idx in mkt_indices:
                        pid = mkt_pay_ids.get(idx, "")
                        oid = mkt_ord_ids.get(idx, "")
                        match = dro_lookup.get(pid) or dro_lookup.get(oid)
                        if match:
                            domain_full = f"{match[0]}{match[1]}".strip()
                            if domain_full:
                                payloads[idx]["itemName"] = domain_full
                                payloads[idx]["domainName"] = domain_full
                                logger.debug("Marketplace domain name enriched: idx=%d -> %s", idx, domain_full)
        except Exception as e_mkt_fix:
            logger.warning("Marketplace domain name enrichment error: %s", e_mkt_fix)

        return payloads

    async def _enrich_business_details(
        self,
        payloads: list[dict],
        records: Sequence[TrackRecord],
    ) -> None:
        """Attach category-relevant business details for the admin drawer
        (Technology plan/subscription/expiry, Venture deal/escrow state).
        Read-only raw SQL, never guessed from product names."""
        if not records:
            return
        from sqlalchemy import bindparam, text

        pay_ids_by_idx: dict[int, str] = {}
        for idx, record in enumerate(records):
            pid = str(getattr(record, "razorpay_payment_id", None) or "").strip()
            if pid:
                pay_ids_by_idx[idx] = pid
        if not pay_ids_by_idx:
            return

        # ── Technology Purchase: plan / expiry / completion from the purchase ──
        tech_purchase_idx = [
            idx
            for idx, record in enumerate(records)
            if str(record.category or "") == TrackRecordCategory.TECHNOLOGY_PURCHASE
            and idx in pay_ids_by_idx
        ]
        if tech_purchase_idx:
            pids = sorted({pay_ids_by_idx[i] for i in tech_purchase_idx})
            sql_pur = text("""
                SELECT sp.razorpay_payment_id, sp.selected_plan, sp.expiry_date,
                       sp.completion_status, sp.sold_at, sl.name AS software_name
                FROM software_purchases sp
                LEFT JOIN software_listings sl ON sl.id = sp.software_id
                WHERE sp.razorpay_payment_id IN :pids
            """).bindparams(bindparam("pids", expanding=True))
            pur_res = await self._session.execute(sql_pur, {"pids": pids})
            details_by_pid: dict[str, dict] = {}
            for row in pur_res.mappings().all():
                pid = str(row.get("razorpay_payment_id") or "").strip()
                details_by_pid[pid] = {
                    "type": "technology_purchase",
                    "product": row.get("software_name") or None,
                    "plan": row.get("selected_plan") or None,
                    "expiryDate": row.get("expiry_date").isoformat() if row.get("expiry_date") else None,
                    "completionStatus": row.get("completion_status") or None,
                    "soldAt": row.get("sold_at").isoformat() if row.get("sold_at") else None,
                }
            for idx in tech_purchase_idx:
                if pay_ids_by_idx[idx] in details_by_pid:
                    payloads[idx]["businessDetails"] = details_by_pid[pay_ids_by_idx[idx]]

        # ── Technology Services: subscription / plan / billing period ──
        tech_service_idx = [
            idx
            for idx, record in enumerate(records)
            if str(record.category or "") == TrackRecordCategory.TECHNOLOGY_SERVICES
            and idx in pay_ids_by_idx
        ]
        if tech_service_idx:
            pids = sorted({pay_ids_by_idx[i] for i in tech_service_idx})
            sql_req = text("""
                SELECT razorpay_payment_id, entity_id, entity_snapshot, lister_id
                FROM cobrother_requests
                WHERE razorpay_payment_id IN :pids AND request_type = 'COCREATION'
            """).bindparams(bindparam("pids", expanding=True))
            req_res = await self._session.execute(sql_req, {"pids": pids})
            req_by_pid: dict[str, dict] = {}
            for row in req_res.mappings().all():
                pid = str(row.get("razorpay_payment_id") or "").strip()
                if pid not in req_by_pid:
                    req_by_pid[pid] = {
                        "entity_id": str(row.get("entity_id") or ""),
                        "snapshot": row.get("entity_snapshot") or None,
                        "lister_id": str(row.get("lister_id") or ""),
                    }
            # Resolve catalogue names + subscription states for the service ids.
            service_by_entity: dict[str, dict] = {}
            sub_by_key: dict[tuple, dict] = {}
            entity_ids = sorted({v["entity_id"] for v in req_by_pid.values() if v["entity_id"]})
            if entity_ids:
                sql_tsvc = text(
                    "SELECT id, slug, name FROM technology_services_catalogue WHERE id IN :ids"
                ).bindparams(bindparam("ids", expanding=True))
                tsvc_res = await self._session.execute(sql_tsvc, {"ids": entity_ids})
                for row in tsvc_res.mappings().all():
                    service_by_entity[str(row.get("id"))] = dict(row)
                slugs = [r["slug"] for r in service_by_entity.values() if r.get("slug")]
                if slugs:
                    sql_sub = text("""
                        SELECT user_id, service_slug, plan_code, billing_cycle, status,
                               current_period_start, current_period_end
                        FROM technology_subscriptions
                        WHERE service_slug IN :slugs
                    """).bindparams(bindparam("slugs", expanding=True))
                    sub_res = await self._session.execute(sql_sub, {"slugs": slugs})
                    for row in sub_res.mappings().all():
                        key = (str(row.get("user_id") or ""), str(row.get("service_slug") or ""))
                        if key not in sub_by_key:
                            sub_by_key[key] = dict(row)
            for idx in tech_service_idx:
                info = req_by_pid.get(pay_ids_by_idx[idx])
                if not info:
                    continue
                service_row = service_by_entity.get(info["entity_id"])
                sub_row = None
                if service_row and service_row.get("slug") and info["lister_id"]:
                    sub_row = sub_by_key.get((info["lister_id"], service_row["slug"]))
                payloads[idx]["businessDetails"] = {
                    "type": "technology_service",
                    "service": (service_row or {}).get("name") or info["snapshot"] or None,
                    "slug": (service_row or {}).get("slug") or None,
                    "plan": (sub_row or {}).get("plan_code") or None,
                    "billingCycle": (sub_row or {}).get("billing_cycle") or None,
                    "subscriptionStatus": (sub_row or {}).get("status") or None,
                    "periodStart": (sub_row or {}).get("current_period_start").isoformat()
                    if (sub_row or {}).get("current_period_start")
                    else None,
                    "periodEnd": (sub_row or {}).get("current_period_end").isoformat()
                    if (sub_row or {}).get("current_period_end")
                    else None,
                }

        # ── Venture / Deal: deal + escrow state ──
        venture_idx = [
            idx
            for idx, record in enumerate(records)
            if str(record.category or "") == TrackRecordCategory.VENTURE_DEAL_PAYMENT
            and idx in pay_ids_by_idx
        ]
        if venture_idx:
            pids = sorted({pay_ids_by_idx[i] for i in venture_idx})
            sql_vtx = text("""
                SELECT razorpay_payment_id, deal_status, escrow_status, seller_id,
                       bd.brand_name AS venture_name
                FROM venture_deal_transactions vt
                LEFT JOIN ventures v ON v.id = vt.venture_id
                LEFT JOIN brand_details bd ON bd.id = v.brand_details_id
                WHERE vt.razorpay_payment_id IN :pids
            """).bindparams(bindparam("pids", expanding=True))
            vtx_res = await self._session.execute(sql_vtx, {"pids": pids})
            vtx_by_pid: dict[str, dict] = {}
            for row in vtx_res.mappings().all():
                pid = str(row.get("razorpay_payment_id") or "").strip()
                if pid not in vtx_by_pid:
                    vtx_by_pid[pid] = {
                        "type": "venture",
                        "venture": row.get("venture_name") or None,
                        "dealStatus": row.get("deal_status") or None,
                        "escrowStatus": row.get("escrow_status") or None,
                        "sellerId": str(row.get("seller_id") or "") or None,
                    }
            for idx in venture_idx:
                if pay_ids_by_idx[idx] in vtx_by_pid:
                    payloads[idx]["businessDetails"] = vtx_by_pid[pay_ids_by_idx[idx]]

    @staticmethod
    async def _resolve_payment_modes(
        payment_id_by_idx: dict[int, str],
        payloads: list[dict],
        rzp_client: Any,
    ) -> None:
        """Resolve per-transaction Payment Mode (TEST/LIVE) for each record's
        payment id against the actual Razorpay account (cached, concurrent).
        Undeterminable ids stay None => frontend shows '—' (never guessed)."""
        if not payment_id_by_idx:
            return
        unique_ids = sorted({pid for pid in payment_id_by_idx.values() if pid})
        if not unique_ids:
            return

        async def _resolve_one(pid: str) -> Optional[str]:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(rzp_client.resolve_payment_environment, pid),
                    timeout=PAYMENT_MODE_RESOLVE_TIMEOUT_SECONDS,
                )
            except Exception:
                # Network / timeout / transient — cannot determine, do not guess.
                return None

        resolved = dict(
            zip(
                unique_ids,
                await asyncio.gather(*(_resolve_one(pid) for pid in unique_ids)),
            )
        )
        for idx, pid in payment_id_by_idx.items():
            payloads[idx]["paymentMode"] = resolved.get(pid)

    @staticmethod
    def _category_for_registration_order(order: Any) -> tuple[str, str]:
        # Domain transfers (storefront transfer flow, OpenProvider-only) are
        # never registrations. They use the dedicated transfer category while
        # preserving the OpenProvider provider label.
        transfer_status = str(getattr(order, "transfer_status", None) or "").strip().upper()
        if transfer_status != "NONE":
            return TrackRecordCategory.DOMAIN_TRANSFER, "OpenProvider"
        rc_id = str(getattr(order, "resellerclub_order_id", None) or "").strip()
        price_src = str(getattr(order, "price_source", None) or "").lower()
        if rc_id or "reseller" in price_src:
            return TrackRecordCategory.DOMAIN_REGISTRATION_RESELLER, "Reseller"
        if "marketplace" in price_src or "market" in price_src:
            return TrackRecordCategory.DOMAIN_MARKETPLACE, "Razorpay"
        return TrackRecordCategory.DOMAIN_REGISTRATION_OPENPROVIDER, "OpenProvider"

    @staticmethod
    def _status_for_registration_order(order: Any) -> tuple[str, str, Optional[str], Optional[str]]:
        st = str(getattr(order, "status", None) or "")
        if hasattr(st, "value"):
            st = str(st.value)
        st_upper = st.upper()
        op_id = str(getattr(order, "open_provider_domain_id", None) or "").strip()
        if (
            any(token in st_upper for token in ("ACTIVE", "REGISTERED"))
            and op_id
            and not op_id.upper().startswith("DEMO-")
        ):
            return FulfillmentStatus.PROVISIONED, OverallStatus.SUCCESS, None, None
        # Abandoned unpaid transfer attempt: expired/cancelled during checkout,
        # never paid, never submitted to OpenProvider. Shown as
        # Expired/Cancelled — never FAILED, never "in progress".
        transfer_status = str(getattr(order, "transfer_status", None) or "").strip().upper()
        if transfer_status != "NONE" and ("EXPIRED" in st_upper or "CANCELLED" in st_upper):
            rzp_pay = str(getattr(order, "razorpay_payment_id", None) or "").strip()
            if not rzp_pay and not op_id:
                if "CANCELLED" in st_upper:
                    return FulfillmentStatus.CANCELLED, OverallStatus.CANCELLED, None, None
                return FulfillmentStatus.EXPIRED, OverallStatus.EXPIRED, None, None
            # Paid/submitted transfer that was (anomalously) expired: the
            # registrar transfer is still legitimately in progress.
            return FulfillmentStatus.IN_PROGRESS, OverallStatus.PENDING, None, None
        # Transfers: a recorded terminal transfer failure is FAILED — never
        # PROVISIONED, and a refund of a failed transfer is FAILED/Refunded.
        # A paid transfer refunded while still in flight is never PROVISIONED.
        if transfer_status != "NONE" and "REFUND" in st_upper:
            if transfer_status == "FAILED" or not op_id:
                return (
                    FulfillmentStatus.FAILED,
                    OverallStatus.REFUNDED,
                    "TRANSFER_FAILED",
                    str(
                        getattr(order, "provision_message", None)
                        or "Domain transfer failed."
                    ),
                )
            return FulfillmentStatus.IN_PROGRESS, OverallStatus.REFUNDED, None, None
        if transfer_status == "FAILED" or (
            transfer_status != "NONE"
            and ("PROVISION_FAILED" in st_upper or "FAIL" in st_upper)
        ):
            return (
                FulfillmentStatus.FAILED,
                OverallStatus.FAILED,
                "TRANSFER_FAILED",
                str(
                    getattr(order, "provision_message", None)
                    or "Domain transfer failed."
                ),
            )
        # Refunded/reversed registration (e.g. provider-side refund, test-mode
        # payment with no customer refund): the domain WAS provisioned at the
        # registrar, then released — reconciled as PROVISIONED / Refunded with
        # no error. Must never fall through to the generic PENDING default.
        if "REFUND" in st_upper:
            return FulfillmentStatus.PROVISIONED, OverallStatus.REFUNDED, None, None
        if "PROVISION_FAILED" in st_upper or "EXPIRED" in st_upper or (
            "FAIL" in st_upper and "PAYMENT_COMPLETED" not in st_upper
        ):
            msg = str(getattr(order, "provision_message", None) or "Domain registration failed or expired.")
            return (
                FulfillmentStatus.FAILED,
                OverallStatus.FAILED,
                "PROVISIONING_ERROR",
                msg,
            )
        if any(token in st_upper for token in ("PAYMENT_COMPLETED", "REGISTRATION_PENDING", "CREATED")):
            return FulfillmentStatus.IN_PROGRESS, OverallStatus.PENDING, None, None
        if "CANCEL" in st_upper:
            return (
                FulfillmentStatus.FAILED,
                OverallStatus.FAILED,
                "PROVISIONING_ERROR",
                str(getattr(order, "provision_message", None) or "Order cancelled."),
            )
        # ACTIVE without a real OpenProvider id is not success.
        if any(token in st_upper for token in ("ACTIVE", "REGISTERED")) and not op_id:
            return (
                FulfillmentStatus.FAILED,
                OverallStatus.FAILED,
                "NO_OPENPROVIDER_DOMAIN_ID",
                "Order marked ACTIVE/registered but open_provider_domain_id is missing.",
            )
        return FulfillmentStatus.IN_PROGRESS, OverallStatus.PENDING, None, None

    @staticmethod
    def _status_for_sync_order(
        order_row: dict,
        *,
        is_transfer: bool,
        target_provider: str,
        op_domain_id: Optional[str],
        demo_op: bool,
    ) -> tuple[str, str, Optional[str], Optional[str], Optional[str]]:
        """Map a registration/transfer order row to Track Record status fields.

        Domain transfers are never "registration failures": a submitted transfer
        stays IN_PROGRESS/Pending even if the order carries a stale
        PROVISION_FAILED (the registration timeout must not apply to transfers).
        Only a genuine terminal failure at OpenProvider (OP status FAIL/REJECT/
        CANCEL, or a DEMO id) marks the transfer failed, with a TRANSFER_FAILED
        error code so it stays distinguishable from a registration failure.
        """
        st = str(order_row.get("status") or "").upper()
        if (
            ("SUCCESS" in st or "COMPLETED" in st or "REGISTERED" in st or "ACTIVE" in st)
            and bool(op_domain_id)
            and not demo_op
        ):
            return FulfillmentStatus.PROVISIONED, OverallStatus.SUCCESS, None, None, None

        if is_transfer:
            op_st = str(order_row.get("open_provider_status") or "").upper()
            ts = str(order_row.get("transfer_status") or "").upper()
            # Abandoned unpaid attempt: the order expired/cancelled during
            # checkout and never entered the transfer process (no Razorpay
            # payment, no OpenProvider id). It is an abandoned attempt —
            # Expired/Cancelled, never a failure, never "in progress".
            if (
                ("EXPIRED" in st or "CANCELLED" in st)
                and "PAYMENT_PENDING" in ts
                and not bool(order_row.get("razorpay_payment_id"))
                and not bool(op_domain_id)
            ):
                if "CANCELLED" in st:
                    return (
                        FulfillmentStatus.CANCELLED,
                        OverallStatus.CANCELLED,
                        None,
                        None,
                        None,
                    )
                return FulfillmentStatus.EXPIRED, OverallStatus.EXPIRED, None, None, None
            # A transfer is failed when the order itself records a terminal
            # transfer failure (transfer_status == FAILED), the registrar
            # reported FAIL/REJECT/CANCEL, or the id is a DEMO placeholder.
            # A failed transfer is NEVER PROVISIONED — even when later refunded
            # (the domain was never provisioned), so it maps to FAILED/Refunded
            # instead of the registration PROVISIONED/Refunded contract.
            transfer_failed = (
                demo_op
                or ts == "FAILED"
                or any(token in op_st for token in ("FAIL", "REJECT", "CANCEL"))
            )
            if transfer_failed:
                return (
                    FulfillmentStatus.FAILED,
                    OverallStatus.REFUNDED if "REFUND" in st else OverallStatus.FAILED,
                    f"{target_provider.upper()}_TRANSFER_FAILED",
                    "TRANSFER_FAILED",
                    str(
                        order_row.get("provision_message")
                        or f"{target_provider} domain transfer failed."
                    ),
                )
            if "REFUND" in st:
                # Paid transfer refunded while still in flight — never claim
                # PROVISIONED without an ACTIVE registrar state.
                return FulfillmentStatus.IN_PROGRESS, OverallStatus.REFUNDED, None, None, None
            return FulfillmentStatus.IN_PROGRESS, OverallStatus.PENDING, None, None, None

        # Refunded/reversed registration (provider-side refund, test-mode payment,
        # no customer refund): reconciled as PROVISIONED / Refunded — never the
        # generic PENDING default, never a FAILED re-derivation.
        if "REFUND" in st:
            return FulfillmentStatus.PROVISIONED, OverallStatus.REFUNDED, None, None, None

        if "FAIL" in st or "CANCEL" in st or demo_op:
            return (
                FulfillmentStatus.FAILED,
                OverallStatus.FAILED,
                f"{target_provider.upper()}_REGISTRATION_FAILED",
                "REGISTRATION_FAILED",
                str(
                    order_row.get("provision_message")
                    or f"{target_provider} domain registration failed."
                ),
            )
        return FulfillmentStatus.IN_PROGRESS, OverallStatus.PENDING, None, None, None

    async def record_from_registration_order(
        self,
        order: Any,
        *,
        cart_batch_id: Optional[str] = None,
        internal_order_id: Optional[str] = None,
    ) -> TrackRecord:
        """Create or update a Track Record from a domain_registration_orders row."""
        order_id = str(getattr(order, "id", "") or "")
        int_id = internal_order_id or (f"TRK-REG-{order_id}" if order_id else None)
        category, provider = self._category_for_registration_order(order)
        fulfillment_status, overall_status, error_code, error_message = (
            self._status_for_registration_order(order)
        )
        # Payment status is derived from the order state: a REFUNDED order must
        # stay REFUNDED (never re-clobbered to CAPTURED by a webhook replay or
        # sync re-run). All other paid orders keep CAPTURED.
        order_st = str(getattr(order, "status", None) or "")
        if hasattr(order_st, "value"):
            order_st = str(order_st.value)
        derived_payment_status = (
            PaymentStatus.REFUNDED if "REFUND" in order_st.upper() else PaymentStatus.CAPTURED
        )
        domain_name = (
            f"{getattr(order, 'domain_name', '') or ''}"
            f"{getattr(order, 'domain_extension', '') or ''}"
        ).strip()
        return await self.record_paid_attempt(
            internal_order_id=int_id,
            cart_batch_id=cart_batch_id,
            category=category,
            provider_subcategory=provider,
            item_name=domain_name or order_id or "Domain registration",
            item_id=order_id or None,
            quantity_years=int(getattr(order, "period_years", None) or 1),
            buyer_name=getattr(order, "buyer_full_name", None),
            buyer_email=getattr(order, "buyer_email", None),
            buyer_phone=getattr(order, "buyer_phone", None),
            buyer_user_id=getattr(order, "buyer_id", None),
            amount_charged=float(getattr(order, "price_inr", None) or 0.0),
            subtotal_ex_gst=(
                float(order.subtotal_inr)
                if getattr(order, "subtotal_inr", None) is not None
                else None
            ),
            gst_amount=(
                float(order.gst_inr)
                if getattr(order, "gst_inr", None) is not None
                else None
            ),
            currency="INR",
            payment_status=derived_payment_status,
            razorpay_order_id=getattr(order, "razorpay_order_id", None),
            razorpay_payment_id=getattr(order, "razorpay_payment_id", None),
            razorpay_refund_id=getattr(order, "razorpay_refund_id", None),
            fulfillment_status=fulfillment_status,
            overall_status=overall_status,
            openprovider_domain_id=str(getattr(order, "open_provider_domain_id", None) or "") or None,
            error_code=error_code,
            error_message=error_message,
            error_source="OPENPROVIDER_OR_BACKEND" if error_code else None,
        )

    async def backfill_from_registration_orders(
        self,
        *,
        razorpay_order_id: Optional[str] = None,
        razorpay_payment_id: Optional[str] = None,
        cart_batch_id: Optional[str] = None,
    ) -> int:
        """Ensure track_records exist for paid registration orders (idempotent)."""
        from app.repository.domain_registration_order_repository import (
            DomainRegistrationOrderRepository,
        )

        if not razorpay_order_id and not razorpay_payment_id:
            return 0

        repo = DomainRegistrationOrderRepository(self._session)
        orders = []
        if razorpay_order_id:
            orders = list(await repo.list_by_razorpay_order_id(razorpay_order_id))
        if not orders and razorpay_payment_id:
            orders = list(await repo.list_by_razorpay_payment_id(razorpay_payment_id))

        synced = 0
        for order in orders:
            if not getattr(order, "razorpay_payment_id", None):
                continue
            await self.record_from_registration_order(
                order,
                cart_batch_id=cart_batch_id or razorpay_order_id,
            )
            synced += 1
        return synced

    async def sync_historical_purchases(self) -> int:
        """Public entry point for the full historical backfill.

        Serialized with a module-level lock so rapid admin refreshes (which now
        fire this in the background) cannot pile up concurrent full-table scans
        against the database.
        """
        async with _SYNC_LOCK:
            return await self._sync_historical_purchases_unlocked()

    async def _sync_historical_purchases_unlocked(self) -> int:
        """Backfill existing historical purchase records across all modules into Track Records using raw SQL queries."""
        synced_count = 0
        try:
            from sqlalchemy import text

            # 1. Backfill Domain Registration Orders
            try:
                sql = text("""
                    SELECT id, created_at, domain_name, domain_extension, period_years, buyer_full_name, buyer_email, buyer_phone,
                           buyer_id, price_inr, subtotal_inr, gst_inr, razorpay_order_id, razorpay_payment_id,
                           razorpay_refund_id, status, resellerclub_order_id, open_provider_domain_id, open_provider_status,
                           price_source, provision_message, transfer_status
                    FROM domain_registration_orders
                """)
                res = await self._session.execute(sql)
                for row in res.mappings().all():
                    reg_id = str(row.get("id"))
                    int_id = f"TRK-REG-{reg_id}"
                    orig_dt = row.get("created_at")

                    rc_id = str(row.get("resellerclub_order_id") or "").strip()
                    price_src = str(row.get("price_source") or "").lower()
                    transfer_status = str(row.get("transfer_status") or "").strip().upper()
                    rzp_pay_id = row.get("razorpay_payment_id")
                    rzp_ord_id = row.get("razorpay_order_id")

                    if transfer_status != "NONE":
                        target_category = TrackRecordCategory.DOMAIN_TRANSFER
                        target_provider = "OpenProvider"
                    elif rc_id or "reseller" in price_src:
                        target_category = TrackRecordCategory.DOMAIN_REGISTRATION_RESELLER
                        target_provider = "Reseller"
                    elif "marketplace" in price_src or "market" in price_src:
                        target_category = TrackRecordCategory.DOMAIN_MARKETPLACE
                        target_provider = "Razorpay"
                    else:
                        target_category = TrackRecordCategory.DOMAIN_REGISTRATION_OPENPROVIDER
                        target_provider = "OpenProvider"

                    existing = await self._repo.find_by_internal_order_id(int_id)
                    if not existing and rzp_pay_id:
                        existing = await self._repo.find_by_razorpay_payment_id(rzp_pay_id)
                    if not existing and rzp_ord_id:
                        existing = await self._repo.find_by_razorpay_order_id(rzp_ord_id)
                    if existing:
                        updated_fields = False
                        domain_full_name = f"{row.get('domain_name') or ''}{row.get('domain_extension') or ''}".strip()
                        if domain_full_name and (existing.item_name.startswith("Payment #") or existing.item_name.startswith("Unprovisioned") or existing.item_name in ("Item", "Domain listing")):
                            existing.item_name = domain_full_name
                            updated_fields = True
                        if existing.category != target_category or existing.provider_subcategory != target_provider:
                            existing.category = target_category
                            existing.provider_subcategory = target_provider
                            updated_fields = True
                        if orig_dt and existing.created_at != orig_dt:
                            existing.created_at = orig_dt
                            updated_fields = True
                        if row.get("buyer_phone") and not existing.buyer_phone:
                            existing.buyer_phone = row.get("buyer_phone")
                            updated_fields = True
                        # Transfers are re-evaluated from the order on every sync
                        # so an abandoned unpaid attempt is corrected to
                        # Expired/Cancelled (never left Pending/in-progress, never
                        # mislabeled as a registration failure). Normal
                        # registrations keep their existing update contract.
                        if transfer_status != "NONE":
                            op_domain_id = str(row.get("open_provider_domain_id") or "").strip() or None
                            demo_op = bool(op_domain_id and op_domain_id.upper().startswith("DEMO-"))
                            f_status, o_status, err_src, err_msg, err_code = (
                                self._status_for_sync_order(
                                    row,
                                    is_transfer=True,
                                    target_provider="OpenProvider",
                                    op_domain_id=op_domain_id,
                                    demo_op=demo_op,
                                )
                            )
                            if (
                                existing.fulfillment_status != f_status
                                or existing.overall_status != o_status
                                or (existing.error_code or None) != (err_code or None)
                            ):
                                existing.fulfillment_status = f_status
                                existing.overall_status = o_status
                                existing.error_code = err_code
                                existing.error_message = err_msg
                                existing.error_source = err_src
                                updated_fields = True
                        if updated_fields:
                            await self._repo.save(existing)
                    else:
                        st = str(row.get("status") or "").upper()
                        is_success = "SUCCESS" in st or "COMPLETED" in st or "REGISTERED" in st or "ACTIVE" in st
                        await self.record_paid_attempt(
                            internal_order_id=int_id,
                            category=target_category,
                            provider_subcategory=target_provider,
                            item_name=f"{row.get('domain_name') or ''}{row.get('domain_extension') or ''}",
                            quantity_years=int(row.get("period_years") or 1),
                            buyer_name=row.get("buyer_full_name"),
                            buyer_email=row.get("buyer_email"),
                            buyer_phone=row.get("buyer_phone"),
                            buyer_user_id=row.get("buyer_id"),
                            amount_charged=float(row.get("price_inr") or 0.0),
                            subtotal_ex_gst=float(row.get("subtotal_inr") or 0.0) if row.get("subtotal_inr") else None,
                            gst_amount=float(row.get("gst_inr") or 0.0) if row.get("gst_inr") else None,
                            currency="INR",
                            payment_status=PaymentStatus.CAPTURED if is_success else PaymentStatus.PENDING,
                            razorpay_order_id=row.get("razorpay_order_id"),
                            razorpay_payment_id=row.get("razorpay_payment_id"),
                            razorpay_refund_id=row.get("razorpay_refund_id"),
                            fulfillment_status=FulfillmentStatus.PROVISIONED if is_success else FulfillmentStatus.IN_PROGRESS,
                            overall_status=OverallStatus.SUCCESS if is_success else OverallStatus.PENDING,
                            created_at=orig_dt,
                        )
                        synced_count += 1
            except Exception as e1:
                logger.warning("Historical sync domain registrations warning: %s", e1)

            # 2. Backfill Domain Marketplace Listings
            try:
                sql = text("""
                    SELECT id, created_at, domain_name, domain_extension, asking_price, purchase_buyer_name, purchase_buyer_email,
                           purchase_buyer_phone, purchased_by_user_id, razorpay_order_id, razorpay_payment_id
                    FROM domain_listings WHERE purchased_by_user_id IS NOT NULL
                """)
                res = await self._session.execute(sql)
                for row in res.mappings().all():
                    list_id = str(row.get("id"))
                    int_id = f"TRK-MKT-HIST-{list_id}"
                    orig_dt = row.get("created_at")
                    rzp_pay_id = row.get("razorpay_payment_id")
                    rzp_ord_id = row.get("razorpay_order_id")

                    existing = await self._repo.find_by_internal_order_id(int_id)
                    if not existing and rzp_pay_id:
                        existing = await self._repo.find_by_razorpay_payment_id(rzp_pay_id)
                    if not existing and rzp_ord_id:
                        existing = await self._repo.find_by_razorpay_order_id(rzp_ord_id)

                    if existing:
                        if existing.category != TrackRecordCategory.DOMAIN_MARKETPLACE:
                            existing.category = TrackRecordCategory.DOMAIN_MARKETPLACE
                            existing.provider_subcategory = "Razorpay"
                        if orig_dt and existing.created_at != orig_dt:
                            existing.created_at = orig_dt
                        await self._repo.save(existing)
                    else:
                        domain_full_name = f"{row.get('domain_name') or ''}{row.get('domain_extension') or ''}".strip()
                        await self.record_paid_attempt(
                            internal_order_id=int_id,
                            category=TrackRecordCategory.DOMAIN_MARKETPLACE,
                            provider_subcategory="Razorpay",
                            item_name=domain_full_name or list_id,
                            item_id=list_id,
                            buyer_name=row.get("purchase_buyer_name"),
                            buyer_email=row.get("purchase_buyer_email"),
                            buyer_phone=row.get("purchase_buyer_phone"),
                            buyer_user_id=row.get("purchased_by_user_id"),
                            amount_charged=float(row.get("asking_price") or 0.0),
                            currency="INR",
                            payment_status=PaymentStatus.CAPTURED,
                            razorpay_order_id=row.get("razorpay_order_id"),
                            razorpay_payment_id=row.get("razorpay_payment_id"),
                            fulfillment_status=FulfillmentStatus.PROVISIONED,
                            overall_status=OverallStatus.SUCCESS,
                            created_at=orig_dt,
                        )
                        synced_count += 1
            except Exception as e2:
                logger.warning("Historical sync marketplace warning: %s", e2)

            # 2b. Fix existing marketplace records with generic item_name
            # Match domain_listings via razorpay_payment_id or razorpay_order_id
            try:
                sql = text("""
                    SELECT tr.id AS tr_id, dl.domain_name, dl.domain_extension
                    FROM track_records tr
                    JOIN domain_listings dl ON (
                        dl.razorpay_payment_id = tr.razorpay_payment_id
                        OR dl.razorpay_order_id = tr.razorpay_order_id
                    )
                    WHERE tr.category = :mkt_cat
                      AND tr.item_name IN ('Item', 'Domain listing')
                      AND dl.purchased_by_user_id IS NOT NULL
                      AND (dl.razorpay_payment_id IS NOT NULL OR dl.razorpay_order_id IS NOT NULL)
                """)
                res = await self._session.execute(sql, {"mkt_cat": TrackRecordCategory.DOMAIN_MARKETPLACE})
                fix_count = 0
                for row in res.mappings().all():
                    full_name = f"{row.get('domain_name') or ''}{row.get('domain_extension') or ''}".strip()
                    if not full_name:
                        continue
                    rec = await self._repo.get_by_id(row["tr_id"])
                    if rec and rec.item_name in ("Item", "Domain listing"):
                        rec.item_name = full_name
                        await self._repo.save(rec)
                        fix_count += 1
                if fix_count:
                    logger.info("Track record marketplace name fix: updated %d records", fix_count)
            except Exception as e2b:
                logger.warning("Track record marketplace name fix warning: %s", e2b)

            # 3. Backfill Software Purchases (Technology Purchase — real product names)
            try:
                sql = text("""
                    SELECT sp.id, sp.created_at, sp.software_id, sp.buyer_id, sp.buyer_full_name,
                           sp.buyer_email, sp.buyer_phone, sp.gross_amount_inr, sp.payment_status,
                           sp.razorpay_order_id, sp.razorpay_payment_id,
                           sl.name AS software_name
                    FROM software_purchases sp
                    LEFT JOIN software_listings sl ON sl.id = sp.software_id
                """)
                res = await self._session.execute(sql)
                for row in res.mappings().all():
                    pur_id = str(row.get("id"))
                    int_id = f"TRK-TECH-HIST-{pur_id}"
                    orig_dt = row.get("created_at")
                    rzp_pay_id = row.get("razorpay_payment_id")
                    rzp_ord_id = row.get("razorpay_order_id")
                    software_name = str(row.get("software_name") or "").strip()

                    existing = await self._repo.find_by_internal_order_id(int_id)
                    if not existing and rzp_pay_id:
                        # Line-aware match: never the first arbitrary record of a
                        # payment that may cover several cart lines.
                        existing = await self._record_for_business_item(
                            razorpay_payment_id=rzp_pay_id,
                            internal_order_id=int_id,
                            item_name=software_name or None,
                            category=TrackRecordCategory.TECHNOLOGY_PURCHASE,
                        )
                    if not existing and rzp_ord_id:
                        existing = await self._repo.find_by_razorpay_order_id(rzp_ord_id)

                    if existing:
                        updated_fields = False
                        if orig_dt and existing.created_at != orig_dt:
                            existing.created_at = orig_dt
                            updated_fields = True
                        # Repair the old generic item name with the real product.
                        if (
                            software_name
                            and (
                                not existing.item_name
                                or existing.item_name.startswith("Payment #")
                                or existing.item_name == "Technology Software Listing"
                            )
                        ):
                            existing.item_name = software_name
                            updated_fields = True
                        if updated_fields:
                            await self._repo.save(existing)
                    else:
                        st = str(row.get("payment_status") or "").upper()
                        is_success = "COMPLETED" in st or "CONFIRMED" in st or "PAID" in st
                        await self.record_paid_attempt(
                            internal_order_id=int_id,
                            category=TrackRecordCategory.TECHNOLOGY_PURCHASE,
                            provider_subcategory="Razorpay",
                            item_name=software_name or f"Technology Product #{pur_id}",
                            item_id=str(row.get("software_id") or pur_id),
                            buyer_name=row.get("buyer_full_name"),
                            buyer_email=row.get("buyer_email"),
                            buyer_phone=row.get("buyer_phone"),
                            buyer_user_id=row.get("buyer_id"),
                            amount_charged=float(row.get("gross_amount_inr") or 0.0),
                            currency="INR",
                            payment_status=PaymentStatus.CAPTURED if is_success else PaymentStatus.PENDING,
                            razorpay_order_id=row.get("razorpay_order_id"),
                            razorpay_payment_id=row.get("razorpay_payment_id"),
                            fulfillment_status=FulfillmentStatus.PROVISIONED if is_success else FulfillmentStatus.IN_PROGRESS,
                            overall_status=OverallStatus.SUCCESS if is_success else OverallStatus.PENDING,
                            created_at=orig_dt,
                        )
                        synced_count += 1
            except Exception as e3:
                logger.warning("Historical sync software purchases warning: %s", e3)

            # 3b. Backfill Technology Services (provider-powered subscriptions)
            # Provider services (VPN, Appointment Booking, AI Business Suite,
            # Invoice AI, Link in Bio, …) never create software_purchases rows;
            # their CoBrother COCREATION request + catalogue entry is the
            # authoritative source. Keyed per request so re-runs converge.
            try:
                sql = text("""
                    SELECT cr.id, cr.created_at, cr.request_type, cr.entity_id, cr.entity_snapshot,
                           cr.lister_id, cr.razorpay_order_id, cr.razorpay_payment_id
                    FROM cobrother_requests cr
                    WHERE cr.request_type = 'COCREATION' AND cr.razorpay_payment_id IS NOT NULL
                """)
                res = await self._session.execute(sql)
                for row in res.mappings().all():
                    req_id = str(row.get("id"))
                    entity_id = str(row.get("entity_id") or "")
                    rzp_pay_id = str(row.get("razorpay_payment_id") or "").strip()
                    if not rzp_pay_id:
                        continue
                    service_row: Optional[dict] = None
                    if entity_id:
                        sql_tsvc = text(
                            "SELECT id, slug, name FROM technology_services_catalogue WHERE id = :e"
                        )
                        tsvc_res = await self._session.execute(sql_tsvc, {"e": entity_id})
                        service_row = tsvc_res.mappings().first()
                    if not service_row and entity_id:
                        # A software listing entity belongs to a Technology
                        # Purchase (covered by section 3) — skip it here.
                        sql_sw = text(
                            "SELECT id FROM software_listings WHERE id = :e"
                        )
                        sw_res = await self._session.execute(sql_sw, {"e": entity_id})
                        if sw_res.mappings().first() is not None:
                            continue
                    int_id = (
                        f"TRK-TSERV-{rzp_pay_id}-{entity_id}"
                        if entity_id
                        else f"TRK-TSERV-{rzp_pay_id}-{req_id}"
                    )
                    existing = await self._repo.find_by_internal_order_id(int_id)
                    if not existing:
                        existing = await self._record_for_business_item(
                            razorpay_payment_id=rzp_pay_id,
                            internal_order_id=int_id,
                            item_name=str(
                                (service_row or {}).get("name")
                                or row.get("entity_snapshot")
                                or ""
                            ) or None,
                            category=TrackRecordCategory.TECHNOLOGY_SERVICES,
                        )
                    if not existing:
                        await self.record_paid_attempt(
                            internal_order_id=int_id,
                            category=TrackRecordCategory.TECHNOLOGY_SERVICES,
                            provider_subcategory="Razorpay",
                            item_name=str(
                                (service_row or {}).get("name")
                                or row.get("entity_snapshot")
                                or f"Technology Service #{req_id}"
                            ),
                            item_id=entity_id or None,
                            buyer_user_id=row.get("lister_id"),
                            amount_charged=0.0,
                            currency="INR",
                            payment_status=PaymentStatus.CAPTURED,
                            razorpay_order_id=row.get("razorpay_order_id"),
                            razorpay_payment_id=rzp_pay_id,
                            fulfillment_status=FulfillmentStatus.PROVISIONED,
                            overall_status=OverallStatus.SUCCESS,
                            created_at=row.get("created_at"),
                        )
                        synced_count += 1
                    elif existing.category != TrackRecordCategory.TECHNOLOGY_SERVICES:
                        existing.category = TrackRecordCategory.TECHNOLOGY_SERVICES
                        existing.provider_subcategory = "Razorpay"
                        await self._repo.save(existing)
            except Exception as e3b:
                logger.warning("Historical sync technology services warning: %s", e3b)

            # 4. Backfill Venture Deal Transactions
            try:
                sql = text("""
                    SELECT vt.id, vt.created_at, vt.buyer_id, vt.seller_id, vt.gross_amount_inr,
                           vt.deal_status, vt.escrow_status, vt.razorpay_order_id, vt.razorpay_payment_id,
                           bd.brand_name AS venture_name
                    FROM venture_deal_transactions vt
                    LEFT JOIN ventures v ON v.id = vt.venture_id
                    LEFT JOIN brand_details bd ON bd.id = v.brand_details_id
                """)
                res = await self._session.execute(sql)
                for row in res.mappings().all():
                    vtx_id = str(row.get("id"))
                    int_id = f"TRK-VENTURE-HIST-{vtx_id}"
                    orig_dt = row.get("created_at")
                    rzp_pay_id = row.get("razorpay_payment_id")
                    rzp_ord_id = row.get("razorpay_order_id")
                    venture_name = str(row.get("venture_name") or "").strip()

                    existing = await self._repo.find_by_internal_order_id(int_id)
                    if not existing and rzp_pay_id:
                        existing = await self._record_for_business_item(
                            razorpay_payment_id=rzp_pay_id,
                            internal_order_id=int_id,
                            item_name=venture_name or None,
                            category=TrackRecordCategory.VENTURE_DEAL_PAYMENT,
                        )
                    if not existing and rzp_ord_id:
                        existing = await self._repo.find_by_razorpay_order_id(rzp_ord_id)
                    if existing:
                        updated_fields = False
                        if orig_dt and existing.created_at != orig_dt:
                            existing.created_at = orig_dt
                            updated_fields = True
                        if (
                            venture_name
                            and (
                                not existing.item_name
                                or existing.item_name.startswith("Payment #")
                                or existing.item_name.startswith("Venture Deal Transaction")
                            )
                        ):
                            existing.item_name = venture_name
                            updated_fields = True
                        if updated_fields:
                            await self._repo.save(existing)
                    else:
                        st = str(row.get("deal_status") or "").upper()
                        escrow = str(row.get("escrow_status") or "").upper()
                        is_success = (
                            "COMPLETED" in st
                            or "SUCCESS" in st
                            or "PAID" in st
                            or "ESCROW" in st
                            or "HELD" in escrow
                            or "COMPLETED" in escrow
                        )
                        await self.record_paid_attempt(
                            internal_order_id=int_id,
                            category=TrackRecordCategory.VENTURE_DEAL_PAYMENT,
                            provider_subcategory="Razorpay",
                            item_name=venture_name or f"Venture Deal Transaction #{vtx_id}",
                            buyer_user_id=row.get("buyer_id"),
                            amount_charged=float(row.get("gross_amount_inr") or 0.0),
                            currency="INR",
                            payment_status=PaymentStatus.CAPTURED if is_success else PaymentStatus.PENDING,
                            razorpay_order_id=row.get("razorpay_order_id"),
                            razorpay_payment_id=row.get("razorpay_payment_id"),
                            fulfillment_status=FulfillmentStatus.PROVISIONED if is_success else FulfillmentStatus.IN_PROGRESS,
                            overall_status=OverallStatus.SUCCESS if is_success else OverallStatus.PENDING,
                            created_at=orig_dt,
                        )
                        synced_count += 1
            except Exception as e4:
                logger.warning("Historical sync venture deals warning: %s", e4)

            await self._session.commit()
            await self.sync_razorpay_missing_payments()
        except Exception as global_exc:
            logger.error("Failed historical track_records sync: %s", global_exc, exc_info=True)

        return synced_count

    # ── Business-record → Track Record resolution (one real transaction = one record) ──

    @staticmethod
    def _normalize_item_key(name: Optional[str]) -> str:
        return " ".join(str(name or "").lower().split())

    @staticmethod
    def _items_match(a: Optional[str], b: Optional[str]) -> bool:
        """Line-aware item matching: exact match, or containment for longer
        product/domain names. Short tokens (<= 6 chars) only match exactly so
        e.g. "VPN" never fuzzy-matches a different line."""
        ka = TrackRecordService._normalize_item_key(a)
        kb = TrackRecordService._normalize_item_key(b)
        if not ka or not kb:
            return False
        if ka == kb:
            return True
        short = ka if len(ka) <= len(kb) else kb
        long_ = kb if len(ka) <= len(kb) else ka
        if len(short) <= 6:
            return False
        return short in long_

    async def _record_for_business_item(
        self,
        *,
        razorpay_payment_id: str,
        internal_order_id: Optional[str] = None,
        item_name: Optional[str] = None,
        category: Optional[str] = None,
        claimed_ids: Optional[set[str]] = None,
    ) -> Optional[TrackRecord]:
        """Resolve the single Track Record that represents a business transaction.

        Authoritative internal order ids win. Otherwise the match is
        payment-scoped and line-aware (exact item, then category when the
        payment has exactly one record) — NEVER a blind ``.first()`` over a
        payment that may cover several cart lines.
        """
        if internal_order_id:
            rec = await self._repo.find_by_internal_order_id(internal_order_id)
            if rec is not None and (not claimed_ids or str(rec.id) not in claimed_ids):
                return rec
        candidates = await self._repo.find_all_by_razorpay_payment_id(razorpay_payment_id)
        if claimed_ids:
            candidates = [c for c in candidates if str(c.id) not in claimed_ids]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        if item_name:
            for c in candidates:
                if self._items_match(c.item_name, item_name):
                    return c
        if category:
            cat_matches = [c for c in candidates if c.category == category]
            if len(cat_matches) == 1:
                return cat_matches[0]
        return None

    async def _adopt_placeholder(
        self,
        *,
        razorpay_payment_id: str,
        claimed_ids: Optional[set[str]] = None,
    ) -> Optional[TrackRecord]:
        """Reuse an unclassified ``TRK-RZP-REC-`` placeholder record from an
        earlier recovery run once a real business record is discovered — the
        placeholder becomes the business record instead of leaving a duplicate."""
        for c in await self._repo.find_all_by_razorpay_payment_id(razorpay_payment_id):
            if claimed_ids and str(c.id) in claimed_ids:
                continue
            if str(c.category or "").lower() == "other" and str(c.internal_order_id or "").startswith("TRK-RZP-REC-"):
                return c
        return None

    @staticmethod
    def _record_snapshot(rec: Optional[TrackRecord]) -> Optional[tuple]:
        if rec is None:
            return None
        return (
            str(rec.category or ""),
            str(rec.item_name or ""),
            str(rec.overall_status or ""),
            str(rec.error_code or ""),
        )

    async def _sync_domain_order_record(
        self,
        *,
        order_row: dict,
        pay: dict[str, Any],
        buyer_name: str,
        buyer_email: str,
        buyer_phone: str,
        buyer_user_id: Any,
        amount_inr: float,
        rzp_order_id: Optional[str],
        pay_id: str,
        created_at: Optional[datetime],
        claimed_ids: Optional[set[str]] = None,
    ) -> tuple[Optional[TrackRecord], bool]:
        """One domain registration/transfer/renewal order row => one Track Record."""
        order_id = str(order_row.get("id") or "")
        if not order_id:
            return None, False
        rc_id = str(order_row.get("resellerclub_order_id") or "").strip()
        price_src = str(order_row.get("price_source") or "").lower()
        notes_cat = str(
            (pay.get("notes") or {}).get("categories")
            or (pay.get("notes") or {}).get("items")
            or ""
        )
        is_transfer = str(order_row.get("transfer_status") or "").strip().upper() != "NONE"
        is_reseller = bool(rc_id) or "reseller" in price_src
        is_marketplace = (
            "marketplace" in price_src
            or "market" in price_src
            or "Domain Marketplace" in notes_cat
        )
        if is_transfer:
            target_category = TrackRecordCategory.DOMAIN_TRANSFER
            target_provider = "OpenProvider"
        elif is_reseller:
            target_category = TrackRecordCategory.DOMAIN_REGISTRATION_RESELLER
            target_provider = "Reseller"
        elif is_marketplace:
            target_category = TrackRecordCategory.DOMAIN_MARKETPLACE
            target_provider = "Razorpay"
        else:
            target_category = TrackRecordCategory.DOMAIN_REGISTRATION_OPENPROVIDER
            target_provider = "OpenProvider"

        domain_name = (
            f"{order_row.get('domain_name') or ''}{order_row.get('domain_extension') or ''}"
        ).strip()
        op_domain_id = str(order_row.get("open_provider_domain_id") or "").strip() or None
        demo_op = bool(op_domain_id and op_domain_id.upper().startswith("DEMO-"))
        f_status, o_status, err_src, err_msg, err_code = (
            self._status_for_sync_order(
                order_row,
                is_transfer=is_transfer,
                target_provider=target_provider,
                op_domain_id=op_domain_id,
                demo_op=demo_op,
            )
        )
        st = str(order_row.get("status") or "").upper()
        payment_status = (
            PaymentStatus.REFUNDED
            if "REFUND" in st
            else (PaymentStatus.CAPTURED if order_row.get("razorpay_payment_id") else PaymentStatus.PENDING)
        )
        rec = await self._record_for_business_item(
            razorpay_payment_id=pay_id,
            internal_order_id=f"TRK-REG-{order_id}",
            item_name=domain_name or None,
            category=target_category,
            claimed_ids=claimed_ids,
        )
        if rec is None:
            rec = await self._adopt_placeholder(razorpay_payment_id=pay_id, claimed_ids=claimed_ids)
        before = self._record_snapshot(rec)
        saved = await self.record_paid_attempt(
            internal_order_id=rec.internal_order_id if rec else f"TRK-REG-{order_id}",
            category=target_category,
            provider_subcategory=target_provider,
            item_name=domain_name or order_id or "Domain registration",
            item_id=order_id,
            quantity_years=int(order_row.get("period_years") or 1),
            buyer_name=order_row.get("buyer_full_name") or buyer_name or None,
            buyer_email=order_row.get("buyer_email") or buyer_email or None,
            buyer_phone=order_row.get("buyer_phone") or buyer_phone or None,
            buyer_user_id=order_row.get("buyer_id") or buyer_user_id,
            amount_charged=float(order_row.get("price_inr") or amount_inr or 0.0),
            currency=str(pay.get("currency") or "INR").upper(),
            payment_status=payment_status,
            razorpay_order_id=rzp_order_id or None,
            razorpay_payment_id=pay_id,
            fulfillment_status=f_status,
            overall_status=o_status,
            openprovider_domain_id=op_domain_id,
            error_code=err_code,
            error_source=err_src,
            error_message=err_msg,
            created_at=created_at if rec is None else None,
            clear_errors=True,
        )
        changed = before != self._record_snapshot(saved)
        return saved, changed

    async def _sync_software_purchase_record(
        self,
        *,
        purchase_row: dict,
        pay: dict[str, Any],
        buyer_name: str,
        buyer_email: str,
        buyer_phone: str,
        buyer_user_id: Any,
        rzp_order_id: Optional[str],
        pay_id: str,
        claimed_ids: Optional[set[str]] = None,
    ) -> tuple[Optional[TrackRecord], bool]:
        """One software purchase row => one Technology Purchase record."""
        pur_id = str(purchase_row.get("id") or "")
        if not pur_id:
            return None, False
        software_name = str(purchase_row.get("software_name") or "").strip()
        st = str(purchase_row.get("payment_status") or "").upper()
        is_success = "COMPLETED" in st or "CONFIRMED" in st or "PAID" in st
        rec = await self._record_for_business_item(
            razorpay_payment_id=pay_id,
            internal_order_id=f"TRK-TECH-HIST-{pur_id}",
            item_name=software_name or None,
            category=TrackRecordCategory.TECHNOLOGY_PURCHASE,
            claimed_ids=claimed_ids,
        )
        if rec is None:
            rec = await self._adopt_placeholder(razorpay_payment_id=pay_id, claimed_ids=claimed_ids)
        before = self._record_snapshot(rec)
        saved = await self.record_paid_attempt(
            internal_order_id=rec.internal_order_id if rec else f"TRK-TECH-HIST-{pur_id}",
            category=TrackRecordCategory.TECHNOLOGY_PURCHASE,
            provider_subcategory="Razorpay",
            item_name=software_name or f"Technology Product #{pur_id}",
            item_id=str(purchase_row.get("software_id") or pur_id),
            buyer_name=purchase_row.get("buyer_full_name") or buyer_name or None,
            buyer_email=purchase_row.get("buyer_email") or buyer_email or None,
            buyer_phone=purchase_row.get("buyer_phone") or buyer_phone or None,
            buyer_user_id=purchase_row.get("buyer_id") or buyer_user_id,
            amount_charged=float(purchase_row.get("gross_amount_inr") or 0.0),
            currency=str(pay.get("currency") or "INR").upper(),
            payment_status=PaymentStatus.CAPTURED if is_success else PaymentStatus.PENDING,
            razorpay_order_id=rzp_order_id or None,
            razorpay_payment_id=pay_id,
            fulfillment_status=FulfillmentStatus.PROVISIONED if is_success else FulfillmentStatus.IN_PROGRESS,
            overall_status=OverallStatus.SUCCESS if is_success else OverallStatus.PENDING,
            created_at=purchase_row.get("created_at") if rec is None else None,
            clear_errors=True,
        )
        changed = before != self._record_snapshot(saved)
        return saved, changed

    async def _sync_technology_service_record(
        self,
        *,
        request_row: dict,
        service_row: Optional[dict],
        pay: dict[str, Any],
        buyer_name: str,
        buyer_email: str,
        buyer_phone: str,
        buyer_user_id: Any,
        rzp_order_id: Optional[str],
        pay_id: str,
        claimed_ids: Optional[set[str]] = None,
    ) -> tuple[Optional[TrackRecord], bool]:
        """One CoBrother COCREATION request for a provider-powered service
        (technology_services_catalogue entry) => one Technology Services record."""
        req_id = str(request_row.get("id") or "")
        entity_id = str(request_row.get("entity_id") or "")
        service_name = str(
            (service_row or {}).get("name")
            or request_row.get("entity_snapshot")
            or "Technology Service"
        ).strip()
        # Payment captured => the service purchase exists. Provisioning state
        # comes from the actual subscription when one is present; otherwise the
        # captured payment keeps the record Pending (never a domain error).
        f_status = FulfillmentStatus.IN_PROGRESS
        o_status = OverallStatus.PENDING
        err_code = err_src = err_msg = None
        if buyer_user_id and service_row and service_row.get("slug"):
            try:
                from sqlalchemy import text

                sql_sub = text(
                    "SELECT status, plan_code, billing_cycle FROM technology_subscriptions "
                    "WHERE user_id = :u AND service_slug = :s "
                    "ORDER BY created_at DESC LIMIT 1"
                )
                sub_res = await self._session.execute(
                    sql_sub,
                    {"u": str(buyer_user_id), "s": service_row.get("slug")},
                )
                sub_row = sub_res.mappings().first()
                if sub_row:
                    sub_status = str(sub_row.get("status") or "PENDING").upper()
                    if sub_status == "ACTIVE":
                        f_status, o_status = FulfillmentStatus.PROVISIONED, OverallStatus.SUCCESS
                    elif any(tok in sub_status for tok in ("FAIL", "CANCEL", "SUSPEND")):
                        f_status, o_status = FulfillmentStatus.FAILED, OverallStatus.FAILED
                        err_code = "SERVICE_PROVISIONING_FAILED"
                        err_src = "RESELLPORTAL"
                        err_msg = f"Provider subscription status: {sub_status}"
                    else:
                        f_status, o_status = FulfillmentStatus.IN_PROGRESS, OverallStatus.PENDING
            except Exception:
                logger.warning(
                    "sync_razorpay_missing_payments.subscription_lookup_failed req=%s",
                    req_id,
                    exc_info=True,
                )
        int_id = (
            f"TRK-TSERV-{pay_id}-{entity_id}"
            if entity_id
            else f"TRK-TSERV-{pay_id}-{req_id}"
        )
        rec = await self._record_for_business_item(
            razorpay_payment_id=pay_id,
            internal_order_id=int_id,
            item_name=service_name or None,
            category=TrackRecordCategory.TECHNOLOGY_SERVICES,
            claimed_ids=claimed_ids,
        )
        if rec is None:
            rec = await self._adopt_placeholder(razorpay_payment_id=pay_id, claimed_ids=claimed_ids)
        before = self._record_snapshot(rec)
        saved = await self.record_paid_attempt(
            internal_order_id=rec.internal_order_id if rec else int_id,
            category=TrackRecordCategory.TECHNOLOGY_SERVICES,
            provider_subcategory="Razorpay",
            item_name=service_name or f"Technology Service #{req_id}",
            item_id=entity_id or None,
            buyer_name=buyer_name or None,
            buyer_email=buyer_email or None,
            buyer_phone=buyer_phone or None,
            buyer_user_id=buyer_user_id,
            # Only a brand-new record takes the Razorpay payment amount as its
            # charge. When a checkout-created record is reused, keep the line
            # total the checkout stored (ex-GST, per item); the payment total
            # is GST-inclusive and would double-count a multi-item payment.
            amount_charged=(
                float(pay.get("amount") or 0) / 100.0 if rec is None else 0.0
            ),
            currency=str(pay.get("currency") or "INR").upper(),
            payment_status=PaymentStatus.CAPTURED,
            razorpay_order_id=rzp_order_id or None,
            razorpay_payment_id=pay_id,
            fulfillment_status=f_status,
            overall_status=o_status,
            error_code=err_code,
            error_source=err_src,
            error_message=err_msg,
            created_at=request_row.get("created_at") if rec is None else None,
            clear_errors=True,
        )
        changed = before != self._record_snapshot(saved)
        return saved, changed

    async def _sync_venture_transaction_record(
        self,
        *,
        tx_row: dict,
        pay: dict[str, Any],
        buyer_name: str,
        buyer_email: str,
        buyer_phone: str,
        buyer_user_id: Any,
        rzp_order_id: Optional[str],
        pay_id: str,
        claimed_ids: Optional[set[str]] = None,
    ) -> tuple[Optional[TrackRecord], bool]:
        """One venture deal transaction => one Venture / Deal Payment record."""
        tx_id = str(tx_row.get("id") or "")
        if not tx_id:
            return None, False
        venture_name = str(tx_row.get("venture_name") or "").strip()
        st = str(tx_row.get("deal_status") or "").upper()
        escrow = str(tx_row.get("escrow_status") or "").upper()
        is_success = (
            "COMPLETED" in st
            or "SUCCESS" in st
            or "PAID" in st
            or "ESCROW" in st
            or "HELD" in escrow
            or "COMPLETED" in escrow
        )
        rec = await self._record_for_business_item(
            razorpay_payment_id=pay_id,
            internal_order_id=f"TRK-VENTURE-HIST-{tx_id}",
            item_name=venture_name or None,
            category=TrackRecordCategory.VENTURE_DEAL_PAYMENT,
            claimed_ids=claimed_ids,
        )
        if rec is None:
            rec = await self._adopt_placeholder(razorpay_payment_id=pay_id, claimed_ids=claimed_ids)
        before = self._record_snapshot(rec)
        saved = await self.record_paid_attempt(
            internal_order_id=rec.internal_order_id if rec else f"TRK-VENTURE-HIST-{tx_id}",
            category=TrackRecordCategory.VENTURE_DEAL_PAYMENT,
            provider_subcategory="Razorpay",
            item_name=venture_name or f"Venture Deal Transaction #{tx_id}",
            item_id=tx_id,
            buyer_name=buyer_name or None,
            buyer_email=buyer_email or None,
            buyer_phone=buyer_phone or None,
            buyer_user_id=tx_row.get("buyer_id") or buyer_user_id,
            amount_charged=float(tx_row.get("gross_amount_inr") or 0.0),
            currency=str(pay.get("currency") or "INR").upper(),
            payment_status=PaymentStatus.CAPTURED if is_success else PaymentStatus.PENDING,
            razorpay_order_id=rzp_order_id or None,
            razorpay_payment_id=pay_id,
            fulfillment_status=FulfillmentStatus.PROVISIONED if is_success else FulfillmentStatus.IN_PROGRESS,
            overall_status=OverallStatus.SUCCESS if is_success else OverallStatus.PENDING,
            created_at=tx_row.get("created_at") if rec is None else None,
            clear_errors=True,
        )
        changed = before != self._record_snapshot(saved)
        return saved, changed

    async def _sync_marketplace_listing_record(
        self,
        *,
        listing_row: dict,
        pay: dict[str, Any],
        buyer_name: str,
        buyer_email: str,
        buyer_phone: str,
        buyer_user_id: Any,
        rzp_order_id: Optional[str],
        pay_id: str,
        claimed_ids: Optional[set[str]] = None,
    ) -> tuple[Optional[TrackRecord], bool]:
        """One sold marketplace listing (legacy rows without a registration
        order) => one Domain Marketplace record."""
        list_id = str(listing_row.get("id") or "")
        if not list_id:
            return None, False
        d_raw = str(listing_row.get("domain_name") or "").strip()
        ext = str(listing_row.get("domain_extension") or "").strip()
        if ext and not ext.startswith("."):
            ext = "." + ext
        domain = d_raw if "." in d_raw else (f"{d_raw}{ext}" if d_raw else "")
        rec = await self._record_for_business_item(
            razorpay_payment_id=pay_id,
            internal_order_id=f"TRK-MKT-HIST-{list_id}",
            item_name=domain or None,
            category=TrackRecordCategory.DOMAIN_MARKETPLACE,
            claimed_ids=claimed_ids,
        )
        if rec is None:
            rec = await self._adopt_placeholder(razorpay_payment_id=pay_id, claimed_ids=claimed_ids)
        before = self._record_snapshot(rec)
        saved = await self.record_paid_attempt(
            internal_order_id=rec.internal_order_id if rec else f"TRK-MKT-HIST-{list_id}",
            category=TrackRecordCategory.DOMAIN_MARKETPLACE,
            provider_subcategory="Razorpay",
            item_name=domain or list_id,
            item_id=list_id,
            buyer_name=listing_row.get("purchase_buyer_name") or buyer_name or None,
            buyer_email=listing_row.get("purchase_buyer_email") or buyer_email or None,
            buyer_phone=listing_row.get("purchase_buyer_phone") or buyer_phone or None,
            buyer_user_id=listing_row.get("purchased_by_user_id") or buyer_user_id,
            amount_charged=float(listing_row.get("asking_price") or 0.0),
            currency=str(pay.get("currency") or "INR").upper(),
            payment_status=PaymentStatus.CAPTURED,
            razorpay_order_id=rzp_order_id or None,
            razorpay_payment_id=pay_id,
            fulfillment_status=FulfillmentStatus.PROVISIONED,
            overall_status=OverallStatus.SUCCESS,
            created_at=listing_row.get("created_at") if rec is None else None,
            clear_errors=True,
        )
        changed = before != self._record_snapshot(saved)
        return saved, changed

    async def sync_razorpay_missing_payments(self) -> int:
        """Scan Razorpay captured payments for missing database order & track records to auto-recover."""
        synced_count = 0
        try:
            from app.integrations.razorpay import client as rzp
            from sqlalchemy import text

            recent_payments: list[dict] = []
            try:
                recent_payments = (
                    await asyncio.wait_for(
                        asyncio.to_thread(rzp.fetch_recent_payments, 50),
                        timeout=RAZORPAY_RECENT_PAYMENTS_TIMEOUT_SECONDS,
                    )
                ) or []
            except asyncio.TimeoutError:
                logger.warning("sync_razorpay_missing_payments fetch_recent_payments timed out")
                recent_payments = []
            for pay in recent_payments:
                if str(pay.get("status") or "").lower() != "captured":
                    continue

                pay_id = str(pay.get("id") or "").strip()
                order_id = str(pay.get("order_id") or "").strip()
                if not pay_id:
                    continue

                # Extract metadata
                notes = pay.get("notes") or {}
                amount_inr = float(pay.get("amount") or 0) / 100.0
                buyer_email = str(pay.get("email") or notes.get("email") or notes.get("buyerEmail") or "").strip()
                buyer_name = str(notes.get("buyerName") or notes.get("name") or "").strip()
                buyer_phone = str(pay.get("contact") or notes.get("phone") or notes.get("buyerPhone") or "").strip()

                if not buyer_phone and buyer_name and (buyer_name.startswith("+") or buyer_name.isdigit() or (len(buyer_name) >= 10 and buyer_name.replace("+", "").replace("-", "").isdigit())):
                    buyer_phone = buyer_name
                    buyer_name = ""

                pay_created_at = None
                if pay.get("created_at"):
                    try:
                        pay_created_at = datetime.fromtimestamp(int(pay["created_at"]), tz=timezone.utc)
                    except Exception:
                        pass

                # Fetch Razorpay order notes/description to recover domain names + buyer details
                order_notes: dict[str, Any] = {}
                rzp_order: dict[str, Any] = {}
                if order_id:
                    try:
                        rzp_order = rzp.fetch_order(order_id) or {}
                        order_notes = rzp_order.get("notes") or {}
                        if not isinstance(order_notes, dict):
                            order_notes = {}
                    except Exception:
                        rzp_order = {}
                        order_notes = {}

                recovered_domains = extract_domains_from_razorpay_payload(
                    pay=pay,
                    order=rzp_order or None,
                )
                domain_name = recovered_domains[0] if recovered_domains else ""
                domain_label = ", ".join(recovered_domains) if recovered_domains else ""

                existing_tr = await self._repo.find_by_razorpay_payment_id(pay_id)
                if not domain_name and existing_tr:
                    from_item = domain_display_from_item_name(existing_tr.item_name)
                    if from_item:
                        domain_name = from_item.split(",")[0].strip()
                        domain_label = from_item
                        recovered_domains = [d.strip() for d in from_item.split(",") if d.strip()]

                if not domain_name:
                    sql_dl = text(
                        "SELECT domain_name FROM domain_listings "
                        "WHERE razorpay_payment_id = :p OR razorpay_order_id = :o LIMIT 1"
                    )
                    dl_res = await self._session.execute(sql_dl, {"p": pay_id, "o": order_id})
                    dl_row = dl_res.mappings().first()
                    if dl_row and dl_row.get("domain_name"):
                        d_raw = str(dl_row.get("domain_name")).strip()
                        domain_name = d_raw if "." in d_raw else f"{d_raw}.com"
                        domain_label = domain_name
                        recovered_domains = [domain_name]

                if existing_tr and existing_tr.buyer_email:
                    buyer_email = existing_tr.buyer_email
                if existing_tr and existing_tr.buyer_name and not buyer_name:
                    buyer_name = existing_tr.buyer_name
                if existing_tr and existing_tr.buyer_phone and not buyer_phone:
                    buyer_phone = existing_tr.buyer_phone

                if not buyer_email:
                    buyer_email = str(
                        order_notes.get("buyerEmail")
                        or notes.get("buyerEmail")
                        or notes.get("email")
                        or pay.get("email")
                        or ""
                    ).strip()

                # Look up actual buyer full name and phone number from users table
                buyer_user_id = None
                if buyer_email:
                    sql_user = text(
                        "SELECT id, firstname, lastname, phone_number FROM users WHERE email = :e LIMIT 1"
                    )
                    user_res = await self._session.execute(sql_user, {"e": buyer_email})
                    found_user = user_res.mappings().first()
                    if found_user:
                        buyer_user_id = found_user.get("id")
                        fn = (found_user.get("firstname") or "").strip()
                        ln = (found_user.get("lastname") or "").strip()
                        full_name_db = f"{fn} {ln}".strip()
                        if full_name_db:
                            buyer_name = full_name_db
                        if found_user.get("phone_number") and not buyer_phone:
                            buyer_phone = str(found_user.get("phone_number"))

                # Prefer registration orders linked by payment id, then by Razorpay order id.
                order_row = None
                order_rows: list[Any] = []
                name_part, ext_part = (
                    domain_name.split(".", 1) if "." in domain_name else (domain_name, "")
                )
                ext_full = ("." + ext_part) if ext_part else ""

                if pay_id:
                    sql_check = text("""
                        SELECT id, created_at, domain_name, domain_extension, buyer_full_name, buyer_email, buyer_phone, buyer_id,
                               price_inr, status, resellerclub_order_id, open_provider_domain_id, open_provider_status, price_source, provision_message,
                               razorpay_order_id, razorpay_payment_id, transfer_status
                        FROM domain_registration_orders
                        WHERE razorpay_payment_id = :pay_id
                        ORDER BY created_at ASC
                    """)
                    res = await self._session.execute(sql_check, {"pay_id": pay_id})
                    order_rows = list(res.mappings().all())
                    order_row = order_rows[0] if order_rows else None

                if not order_rows and order_id:
                    sql_by_order = text("""
                        SELECT id, created_at, domain_name, domain_extension, buyer_full_name, buyer_email, buyer_phone, buyer_id,
                               price_inr, status, resellerclub_order_id, open_provider_domain_id, open_provider_status, price_source, provision_message,
                               razorpay_order_id, razorpay_payment_id, transfer_status
                        FROM domain_registration_orders
                        WHERE razorpay_order_id = :oid
                        ORDER BY created_at ASC
                    """)
                    res = await self._session.execute(sql_by_order, {"oid": order_id})
                    order_rows = list(res.mappings().all())
                    order_row = order_rows[0] if order_rows else None

                if not order_rows and name_part and ext_full and not str(domain_name).startswith("Payment #"):
                    sql_check = text("""
                        SELECT id, created_at, domain_name, domain_extension, buyer_full_name, buyer_email, buyer_phone, buyer_id,
                               price_inr, status, resellerclub_order_id, open_provider_domain_id, open_provider_status, price_source, provision_message,
                               razorpay_order_id, razorpay_payment_id, transfer_status
                        FROM domain_registration_orders
                        WHERE domain_name = :dname AND domain_extension = :dext
                        ORDER BY created_at DESC
                        LIMIT 1
                    """)
                    res = await self._session.execute(
                        sql_check, {"dname": name_part, "dext": ext_full}
                    )
                    order_row = res.mappings().first()
                    if order_row:
                        order_rows = [order_row]

                # If DB orders exist, prefer their FQDNs for the Track Record item name.
                if order_rows:
                    db_domains = [
                        f"{r.get('domain_name') or ''}{r.get('domain_extension') or ''}".strip().lower()
                        for r in order_rows
                    ]
                    db_domains = [d for d in db_domains if d and "." in d]
                    if db_domains:
                        recovered_domains = db_domains
                        domain_name = db_domains[0]
                        domain_label = ", ".join(db_domains)

                rec_created_at = (order_rows[0].get("created_at") if order_rows else None) or pay_created_at
                recovery_note = None
                if recovered_domains and not order_rows:
                    recovery_note = (
                        "Domain recovered from Razorpay notes/description: "
                        + ", ".join(recovered_domains)
                    )

                claimed_ids: set[str] = set()
                handled_business = False

                # ── 1. Domain registration / transfer / marketplace orders ──────
                # One order row = one real transaction = one Track Record. This
                # fixes the old bug where the whole payment was classified as a
                # single domain (multi-line carts mixed domains + technology).
                for order_row in order_rows:
                    rec, changed = await self._sync_domain_order_record(
                        order_row=order_row,
                        pay=pay,
                        buyer_name=buyer_name,
                        buyer_email=buyer_email,
                        buyer_phone=buyer_phone,
                        buyer_user_id=buyer_user_id,
                        amount_inr=amount_inr,
                        rzp_order_id=order_id or None,
                        pay_id=pay_id,
                        created_at=rec_created_at,
                        claimed_ids=claimed_ids,
                    )
                    if rec is not None:
                        claimed_ids.add(str(rec.id))
                        if changed:
                            synced_count += 1
                            logger.warning(
                                "sync_razorpay_missing_payments.upserted payment_id=%s "
                                "order_id=%s category=%s item=%s overall=%s op_id=%s",
                                pay_id,
                                order_row.get("id"),
                                rec.category,
                                rec.item_name,
                                rec.overall_status,
                                rec.openprovider_domain_id,
                            )
                    handled_business = True

                # ── 2. Software purchases (Technology Purchase) ──────────────────
                # A payment can bundle a domain AND technology lines; software
                # purchases must still get their own Technology Purchase record.
                if pay_id:
                    sql_pur = text("""
                        SELECT sp.id, sp.created_at, sp.software_id, sp.buyer_id, sp.buyer_full_name,
                               sp.buyer_email, sp.buyer_phone, sp.gross_amount_inr, sp.payment_status,
                               sp.razorpay_order_id, sp.razorpay_payment_id,
                               sl.name AS software_name
                        FROM software_purchases sp
                        LEFT JOIN software_listings sl ON sl.id = sp.software_id
                        WHERE sp.razorpay_payment_id = :p
                    """)
                    pur_res = await self._session.execute(sql_pur, {"p": pay_id})
                    for purchase_row in pur_res.mappings().all():
                        rec, changed = await self._sync_software_purchase_record(
                            purchase_row=purchase_row,
                            pay=pay,
                            buyer_name=buyer_name,
                            buyer_email=buyer_email,
                            buyer_phone=buyer_phone,
                            buyer_user_id=buyer_user_id,
                            rzp_order_id=order_id or None,
                            pay_id=pay_id,
                            claimed_ids=claimed_ids,
                        )
                        if rec is not None:
                            claimed_ids.add(str(rec.id))
                            if changed:
                                synced_count += 1
                        handled_business = True

                # ── 3. Technology service subscriptions (via CoBrother requests) ──
                # Provider-powered services (VPN, AI Business Suite, …) have no
                # software_purchases row; their CoBrother request links the
                # payment to the service catalogue entry.
                if pay_id:
                    sql_req = text("""
                        SELECT id, created_at, request_type, entity_id, entity_snapshot, lister_id,
                               razorpay_order_id, razorpay_payment_id
                        FROM cobrother_requests
                        WHERE razorpay_payment_id = :p AND request_type = 'COCREATION'
                    """)
                    req_res = await self._session.execute(sql_req, {"p": pay_id})
                    for request_row in req_res.mappings().all():
                        entity_id = str(request_row.get("entity_id") or "")
                        service_row: Optional[dict] = None
                        if entity_id:
                            sql_tsvc = text(
                                "SELECT id, slug, name FROM technology_services_catalogue WHERE id = :e"
                            )
                            tsvc_res = await self._session.execute(sql_tsvc, {"e": entity_id})
                            service_row = tsvc_res.mappings().first()
                            if not service_row:
                                # A software purchase entity is covered by step 2.
                                sql_sw_check = text(
                                    "SELECT id FROM software_purchases WHERE id = :e"
                                )
                                sw_res = await self._session.execute(sql_sw_check, {"e": entity_id})
                                if sw_res.mappings().first() is not None:
                                    continue
                        rec, changed = await self._sync_technology_service_record(
                            request_row=request_row,
                            service_row=service_row,
                            pay=pay,
                            buyer_name=buyer_name,
                            buyer_email=buyer_email,
                            buyer_phone=buyer_phone,
                            buyer_user_id=buyer_user_id,
                            rzp_order_id=order_id or None,
                            pay_id=pay_id,
                            claimed_ids=claimed_ids,
                        )
                        if rec is not None:
                            claimed_ids.add(str(rec.id))
                            if changed:
                                synced_count += 1
                        handled_business = True

                # ── 4. Venture deal transactions ─────────────────────────────────
                if pay_id:
                    sql_vtx = text("""
                        SELECT vt.id, vt.created_at, vt.buyer_id, vt.seller_id, vt.gross_amount_inr,
                               vt.deal_status, vt.escrow_status, vt.razorpay_order_id, vt.razorpay_payment_id,
                               bd.brand_name AS venture_name
                        FROM venture_deal_transactions vt
                        LEFT JOIN ventures v ON v.id = vt.venture_id
                        LEFT JOIN brand_details bd ON bd.id = v.brand_details_id
                        WHERE vt.razorpay_payment_id = :p
                    """)
                    vtx_res = await self._session.execute(sql_vtx, {"p": pay_id})
                    for tx_row in vtx_res.mappings().all():
                        rec, changed = await self._sync_venture_transaction_record(
                            tx_row=tx_row,
                            pay=pay,
                            buyer_name=buyer_name,
                            buyer_email=buyer_email,
                            buyer_phone=buyer_phone,
                            buyer_user_id=buyer_user_id,
                            rzp_order_id=order_id or None,
                            pay_id=pay_id,
                            claimed_ids=claimed_ids,
                        )
                        if rec is not None:
                            claimed_ids.add(str(rec.id))
                            if changed:
                                synced_count += 1
                        handled_business = True

                # ── 5. Marketplace listings (legacy rows without an order) ───────
                if not handled_business and pay_id:
                    sql_ml = text("""
                        SELECT id, created_at, domain_name, domain_extension, asking_price,
                               purchase_buyer_name, purchase_buyer_email, purchase_buyer_phone,
                               purchased_by_user_id, razorpay_order_id, razorpay_payment_id
                        FROM domain_listings
                        WHERE razorpay_payment_id = :p AND purchased_by_user_id IS NOT NULL
                    """)
                    ml_res = await self._session.execute(sql_ml, {"p": pay_id})
                    for listing_row in ml_res.mappings().all():
                        rec, changed = await self._sync_marketplace_listing_record(
                            listing_row=listing_row,
                            pay=pay,
                            buyer_name=buyer_name,
                            buyer_email=buyer_email,
                            buyer_phone=buyer_phone,
                            buyer_user_id=buyer_user_id,
                            rzp_order_id=order_id or None,
                            pay_id=pay_id,
                            claimed_ids=claimed_ids,
                        )
                        if rec is not None:
                            claimed_ids.add(str(rec.id))
                            if changed:
                                synced_count += 1
                        handled_business = True

                # ── 6. Genuinely orphan payment ──────────────────────────────────
                # No business record anywhere. A captured payment is real money
                # but we do NOT know what it bought — never fabricate a domain
                # registration (NO_REGISTRATION_ORDER) over it. If a Track
                # Record already exists for the payment it already represents
                # the transaction; leave it alone.
                if not handled_business:
                    existing_for_payment = await self._repo.find_all_by_razorpay_payment_id(pay_id)
                    if not existing_for_payment:
                        await self.record_paid_attempt(
                            internal_order_id=f"TRK-RZP-REC-{pay_id}",
                            category=TrackRecordCategory.OTHER,
                            provider_subcategory="Razorpay",
                            item_name=f"Payment #{pay_id}",
                            buyer_name=buyer_name or None,
                            buyer_email=buyer_email or None,
                            buyer_phone=buyer_phone or None,
                            buyer_user_id=buyer_user_id,
                            amount_charged=amount_inr,
                            currency=str(pay.get("currency") or "INR").upper(),
                            payment_status=PaymentStatus.CAPTURED,
                            razorpay_order_id=order_id or None,
                            razorpay_payment_id=pay_id,
                            fulfillment_status=FulfillmentStatus.NOT_STARTED,
                            overall_status=OverallStatus.PENDING,
                            notes=recovery_note,
                            created_at=pay_created_at,
                            clear_errors=True,
                        )
                        synced_count += 1
                    else:
                        logger.info(
                            "sync_razorpay_missing_payments.orphan_payment_has_record "
                            "payment_id=%s records=%s — no business row found, record kept as-is",
                            pay_id,
                            len(existing_for_payment),
                        )

            await self._session.commit()
        except Exception as exc:
            logger.warning("sync_razorpay_missing_payments warning: %s", exc)

        return synced_count
