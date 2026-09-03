"""Track Record classification & status unit tests (no database).

Covers the corrected business rules:

* Category comes from the real business transaction — a technology service
  (VPN, Appointment Booking, AI Business Suite, Invoice AI, Link in Bio) is
  Technology Services, never Technology Purchase, never Domain Registration.
* One real transaction => exactly one Track Record, no matter how many sync /
  recovery paths discover it.
* Non-domain categories never receive domain statuses (Registration /
  Transfer / Renewal) or domain errors (NO_REGISTRATION_ORDER).
* Sync / recovery paths never downgrade a confirmed successful transaction to
  Pending because of a stale intermediate database row.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.entity.platform.track_record_entity import TrackRecord
from app.service.platform.track_record_service import (
    FulfillmentStatus,
    OverallStatus,
    PaymentStatus,
    TrackRecordCategory,
    TrackRecordService,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    """Replies to raw-SQL text() queries by table name with canned rows.

    Applies minimal WHERE-clause filtering (payment id, entity id, user+slug)
    so multi-row tables behave like the real database instead of returning
    every row for every query.
    """

    def __init__(self, tables):
        self._tables = tables
        self.executed_sql = []

    async def execute(self, stmt, params=None):
        s = str(stmt)
        self.executed_sql.append(s)
        params = params or {}
        for table, rows in self._tables.items():
            if f"FROM {table}" not in s and f"JOIN {table}" not in s:
                continue
            result = list(rows)
            if table == "cobrother_requests" and params.get("p") is not None:
                result = [
                    r for r in result
                    if str(r.get("razorpay_payment_id") or "") == str(params["p"])
                ]
            elif table == "technology_services_catalogue" and params.get("e") is not None:
                result = [
                    r for r in result
                    if str(r.get("id") or "") == str(params["e"])
                ]
            elif (
                table == "technology_subscriptions"
                and params.get("u") is not None
                and params.get("s") is not None
            ):
                result = [
                    r for r in result
                    if str(r.get("user_id") or "") == str(params["u"])
                    and str(r.get("service_slug") or "") == str(params["s"])
                ]
            elif table == "software_purchases" and params.get("p") is not None:
                result = [
                    r for r in result
                    if str(r.get("razorpay_payment_id") or "") == str(params["p"])
                ]
            elif table == "software_purchases" and params.get("e") is not None:
                result = [
                    r for r in result
                    if str(r.get("id") or "") == str(params["e"])
                ]
            elif table in ("domain_registration_orders", "domain_listings", "venture_deal_transactions") and params.get("p") is not None:
                result = [
                    r for r in result
                    if str(r.get("razorpay_payment_id") or "") == str(params["p"])
                ]
            return _Rows(result)
        return _Rows([])

    async def commit(self):
        return None


class FakeRepo:
    def __init__(self):
        self.records = {}
        self.by_internal = {}
        self.by_payment = {}
        self.by_order = {}

    async def find_by_internal_order_id(self, oid):
        return self.by_internal.get(oid)

    async def find_by_razorpay_order_id(self, oid):
        return self.by_order.get(oid)

    async def find_by_razorpay_payment_id(self, pid):
        rows = self.by_payment.get(pid or "", [])
        return rows[0] if rows else None

    async def find_all_by_razorpay_payment_id(self, pid):
        return list(self.by_payment.get(pid or "", []))

    async def save(self, rec):
        if rec.id is None:
            rec.id = uuid.uuid4()
        self.records[rec.id] = rec
        self.by_internal[rec.internal_order_id] = rec
        if rec.razorpay_order_id:
            self.by_order.setdefault(rec.razorpay_order_id, rec)
        pid = rec.razorpay_payment_id or ""
        siblings = [r for r in self.by_payment.get(pid, []) if r.id != rec.id]
        siblings.append(rec)
        self.by_payment[pid] = siblings
        return rec


def _make_service(session, repo) -> TrackRecordService:
    service = TrackRecordService(session)
    service._repo = repo
    return service


def _pay(pay_id="pay_abc", order_id="order_abc", amount=129900, notes=None):
    return {
        "id": pay_id,
        "order_id": order_id,
        "status": "captured",
        "amount": amount,
        "currency": "INR",
        "email": "buyer@example.com",
        "contact": "9876543210",
        "notes": notes or {},
        "created_at": 1784000000,
    }


# ─────────────────────────── entity to_dict rules ────────────────────────────


def test_technology_purchase_has_no_registration_status():
    tr = TrackRecord(
        internal_order_id="TRK-TECH-1",
        category=TrackRecordCategory.TECHNOLOGY_PURCHASE,
        provider_subcategory="Razorpay",
        item_name="Invoice AI Desktop",
        payment_status="CAPTURED",
        fulfillment_status="PROVISIONED",
        overall_status="Success",
    )
    d = tr.to_dict()
    assert d["operationType"] == "fulfillment"
    assert d["operationTitle"] == "Fulfillment"
    assert d["operationStatus"] == "OK"
    assert d["operationLabel"] == "Fulfillment — Success"
    assert d["registrationLabel"] == "—"
    assert d["registrationOk"] is False


def test_technology_services_has_no_registration_status():
    tr = TrackRecord(
        internal_order_id="TRK-TSERV-1",
        category=TrackRecordCategory.TECHNOLOGY_SERVICES,
        provider_subcategory="Razorpay",
        item_name="VPN",
        payment_status="CAPTURED",
        fulfillment_status="PROVISIONED",
        overall_status="Success",
    )
    d = tr.to_dict()
    assert d["operationType"] == "provisioning"
    assert d["operationTitle"] == "Provisioning"
    assert d["operationStatus"] == "OK"
    assert d["operationLabel"] == "Provisioning — Active"
    assert d["registrationLabel"] == "—"


def test_technology_services_pending_and_failed_operation_labels():
    """A Technology Services record that is still provisioning shows
    Provisioning → Pending; a failed provisioning shows Provisioning → Failed —
    never a bare status and never a registration label."""
    pending = TrackRecord(
        internal_order_id="TRK-TSERV-P-1",
        category=TrackRecordCategory.TECHNOLOGY_SERVICES,
        item_name="VPN",
        payment_status="CAPTURED",
        fulfillment_status="IN_PROGRESS",
        overall_status="Pending",
    ).to_dict()
    assert pending["operationLabel"] == "Provisioning — Pending"
    assert pending["registrationLabel"] == "—"

    failed = TrackRecord(
        internal_order_id="TRK-TSERV-F-1",
        category=TrackRecordCategory.TECHNOLOGY_SERVICES,
        item_name="VPN",
        payment_status="CAPTURED",
        fulfillment_status="FAILED",
        overall_status="Failed",
        error_code="SERVICE_PROVISIONING_FAILED",
    ).to_dict()
    assert failed["operationLabel"] == "Provisioning — Failed"
    assert failed["registrationLabel"] == "—"


def test_marketplace_and_venture_and_addon_operation_types():
    marketplace = TrackRecord(
        internal_order_id="TRK-MKT-1",
        category=TrackRecordCategory.DOMAIN_MARKETPLACE,
        item_name="useddomain.com",
        payment_status="CAPTURED",
        fulfillment_status="PROVISIONED",
        overall_status="Success",
    ).to_dict()
    assert marketplace["operationType"] == "acquisition"
    assert marketplace["operationTitle"] == "Acquisition"
    assert marketplace["operationLabel"] == "Acquisition — Success"
    assert marketplace["registrationLabel"] == "—"

    venture = TrackRecord(
        internal_order_id="TRK-VENTURE-1",
        category=TrackRecordCategory.VENTURE_DEAL_PAYMENT,
        item_name="Venture Brand",
        payment_status="CAPTURED",
        fulfillment_status="PROVISIONED",
        overall_status="Success",
    ).to_dict()
    assert venture["operationType"] == "deal"
    assert venture["operationTitle"] == "Deal"
    assert venture["operationLabel"] == "Deal — Success"
    assert venture["registrationLabel"] == "—"

    addon = TrackRecord(
        internal_order_id="TRK-ADDON-1",
        category=TrackRecordCategory.DOMAIN_ADDON_EMAIL,
        item_name="Email Addon",
        payment_status="CAPTURED",
        fulfillment_status="PROVISIONED",
        overall_status="Success",
    ).to_dict()
    assert addon["operationType"] == "service"
    assert addon["operationTitle"] == "Service"
    assert addon["operationLabel"] == "Service — Success"
    assert addon["registrationLabel"] == "—"


def test_domain_categories_keep_registration_statuses():
    success = TrackRecord(
        internal_order_id="TRK-REG-1",
        category=TrackRecordCategory.DOMAIN_REGISTRATION_OPENPROVIDER,
        item_name="card.com",
        payment_status="CAPTURED",
        fulfillment_status="PROVISIONED",
        overall_status="Success",
        openprovider_domain_id="30000001",
    ).to_dict()
    assert success["operationType"] == "registration"
    assert success["operationStatus"] == "OK"
    assert success["operationLabel"] == "Registration — Success"
    assert success["registrationLabel"] == "OK"

    pending = TrackRecord(
        internal_order_id="TRK-REG-2",
        category=TrackRecordCategory.DOMAIN_REGISTRATION_OPENPROVIDER,
        item_name="pending.com",
        payment_status="CAPTURED",
        fulfillment_status="IN_PROGRESS",
        overall_status="Pending",
    ).to_dict()
    assert pending["operationStatus"] == "PENDING"
    assert pending["operationLabel"] == "Registration — Pending"
    assert pending["registrationLabel"] == "PENDING"

    failed = TrackRecord(
        internal_order_id="TRK-REG-3",
        category=TrackRecordCategory.DOMAIN_REGISTRATION_OPENPROVIDER,
        item_name="fail.com",
        payment_status="CAPTURED",
        fulfillment_status="FAILED",
        overall_status="Failed",
        error_code="REGISTRATION_FAILED",
    ).to_dict()
    assert failed["operationStatus"] == "FAIL"
    assert failed["operationLabel"] == "Registration — Failed"
    assert failed["registrationLabel"] == "FAIL"


def test_domain_transfer_and_renewal_operation_labels():
    """Domain Transfer / Domain Renewal get their own operation label — never a
    generic registration label."""
    transfer = TrackRecord(
        internal_order_id="TRK-TRANSFER-1",
        category=TrackRecordCategory.DOMAIN_TRANSFER,
        item_name="move.com",
        payment_status="CAPTURED",
        fulfillment_status="PROVISIONED",
        overall_status="Success",
        openprovider_domain_id="30000009",
    ).to_dict()
    assert transfer["operationType"] == "transfer"
    assert transfer["operationTitle"] == "Transfer"
    assert transfer["operationLabel"] == "Transfer — Success"

    transfer_pending = TrackRecord(
        internal_order_id="TRK-TRANSFER-2",
        category=TrackRecordCategory.DOMAIN_TRANSFER,
        item_name="move2.com",
        payment_status="CAPTURED",
        fulfillment_status="IN_PROGRESS",
        overall_status="Pending",
    ).to_dict()
    assert transfer_pending["operationLabel"] == "Transfer — Pending"

    renewal = TrackRecord(
        internal_order_id="TRK-RENEW-1",
        category=TrackRecordCategory.DOMAIN_RENEWAL,
        item_name="keep.com",
        payment_status="CAPTURED",
        fulfillment_status="COMPLETED",
        overall_status="Success",
    ).to_dict()
    assert renewal["operationType"] == "renewal"
    assert renewal["operationTitle"] == "Renewal"
    assert renewal["operationLabel"] == "Renewal — Success"

    renewal_failed = TrackRecord(
        internal_order_id="TRK-RENEW-2",
        category=TrackRecordCategory.DOMAIN_RENEWAL,
        item_name="keep2.com",
        payment_status="CAPTURED",
        fulfillment_status="FAILED",
        overall_status="Failed",
        error_code="RENEWAL_FAILED",
    ).to_dict()
    assert renewal_failed["operationLabel"] == "Renewal — Failed"


# ───────────────────────────── status mapping ────────────────────────────────


def test_domain_status_mapping_success_pending_failed():
    mapper = TrackRecordService._status_for_sync_order
    ok = mapper(
        {"status": "ACTIVE", "transfer_status": "NONE"},
        is_transfer=False,
        target_provider="OpenProvider",
        op_domain_id="30000001",
        demo_op=False,
    )
    assert ok[:2] == (FulfillmentStatus.PROVISIONED, OverallStatus.SUCCESS)

    pending = mapper(
        {"status": "REGISTRATION_PENDING", "transfer_status": "NONE"},
        is_transfer=False,
        target_provider="OpenProvider",
        op_domain_id=None,
        demo_op=False,
    )
    assert pending[:2] == (FulfillmentStatus.IN_PROGRESS, OverallStatus.PENDING)

    failed = mapper(
        {"status": "PROVISION_FAILED", "transfer_status": "NONE"},
        is_transfer=False,
        target_provider="OpenProvider",
        op_domain_id=None,
        demo_op=False,
    )
    assert failed[1] == OverallStatus.FAILED


def test_tech_fulfillment_from_result():
    from app.service.cart.cart_checkout_service import _tech_fulfillment_from_result

    # One-time product: fulfilled on capture.
    product = _tech_fulfillment_from_result({"type": "TECHNOLOGY"}, is_service=False)
    assert product[:2] == (FulfillmentStatus.PROVISIONED, OverallStatus.SUCCESS)

    # Provider service ACTIVE => provisioned. PROVISIONED/SUCCESS requires the
    # provider subscription id too (never claim success without one).
    active = _tech_fulfillment_from_result(
        {"status": "ACTIVE", "providerSubscriptionId": "SUB-X"}, is_service=True
    )
    assert active[:2] == (FulfillmentStatus.PROVISIONED, OverallStatus.SUCCESS)

    # Provider service PENDING => in progress.
    pending = _tech_fulfillment_from_result({"status": "PENDING"}, is_service=True)
    assert pending[:2] == (FulfillmentStatus.IN_PROGRESS, OverallStatus.PENDING)

    # Provider service FAILED => failed with a service error (never a domain error).
    failed = _tech_fulfillment_from_result({"status": "FAILED"}, is_service=True)
    assert failed[1] == OverallStatus.FAILED
    assert failed[2] == "SERVICE_PROVISIONING_FAILED"


# ─────────────────── recovery: one transaction => one record ─────────────────


async def _run_sync(session, repo, payments) -> int:
    service = _make_service(session, repo)
    with patch(
        "app.integrations.razorpay.client.fetch_recent_payments",
        return_value=payments,
    ), patch(
        "app.integrations.razorpay.client.fetch_order",
        return_value={},
    ):
        return await service.sync_razorpay_missing_payments()


async def test_tech_service_recovery_no_domain_error_no_duplicate():
    """A payment for a provider service (AI Business Suite) with no domain
    order must produce ONE Technology Services record — never a domain record,
    never NO_REGISTRATION_ORDER, never Failed."""
    user_id = uuid.uuid4()
    service_id = uuid.uuid4()
    pay = _pay(pay_id="pay_suite", order_id="order_suite", amount=299900, notes={
        "items": "Technology: AI Business Suite",
    })
    session = FakeSession({
        "domain_registration_orders": [],
        "software_purchases": [],
        "cobrother_requests": [{
            "id": uuid.uuid4(), "created_at": _now(), "request_type": "COCREATION",
            "entity_id": service_id, "entity_snapshot": "AI Business Suite",
            "lister_id": user_id, "razorpay_order_id": "order_suite",
            "razorpay_payment_id": "pay_suite",
        }],
        "technology_services_catalogue": [{
            "id": service_id, "slug": "ai-business-suite", "name": "AI Business Suite",
        }],
        "software_listings": [],
        "technology_subscriptions": [{
            "user_id": str(user_id), "service_slug": "ai-business-suite", "plan_code": "starter",
            "billing_cycle": "monthly", "status": "ACTIVE",
            "current_period_start": _now(), "current_period_end": _now(),
        }],
        "venture_deal_transactions": [],
        "domain_listings": [],
        "users": [{
            "id": user_id, "firstname": "N", "lastname": "A", "phone_number": "9876543210",
        }],
    })
    repo = FakeRepo()

    synced = await _run_sync(session, repo, [pay])

    records = repo.by_payment.get("pay_suite", [])
    assert len(records) == 1, "one transaction must yield exactly one record"
    rec = records[0]
    assert rec.category == TrackRecordCategory.TECHNOLOGY_SERVICES
    assert rec.item_name == "AI Business Suite"
    assert rec.overall_status == OverallStatus.SUCCESS
    assert rec.error_code is None
    assert "NO_REGISTRATION_ORDER" not in str(rec.error_code or "")
    d = rec.to_dict()
    assert d["operationType"] == "provisioning"
    assert d["registrationLabel"] == "—"
    assert synced == 1


async def test_orphan_payment_never_fabricates_domain_failure():
    """A captured payment with NO business record anywhere becomes an
    unclassified record — Payment OK, Pending, NO domain error. It must never
    be filed as a failed domain registration."""
    pay = _pay(pay_id="pay_orphan", order_id="order_orphan")
    session = FakeSession({
        "domain_registration_orders": [],
        "software_purchases": [],
        "cobrother_requests": [],
        "technology_services_catalogue": [],
        "software_listings": [],
        "venture_deal_transactions": [],
        "domain_listings": [],
        "users": [],
    })
    repo = FakeRepo()

    await _run_sync(session, repo, [pay])

    records = repo.by_payment.get("pay_orphan", [])
    assert len(records) == 1
    rec = records[0]
    assert rec.category == TrackRecordCategory.OTHER
    assert rec.payment_status == PaymentStatus.CAPTURED
    assert rec.overall_status == OverallStatus.PENDING
    assert rec.error_code is None
    assert "NO_REGISTRATION_ORDER" not in str(rec.error_code or "")
    assert "domain registration" not in rec.category.lower()


async def test_multi_line_payment_domain_plus_software_two_records():
    """One payment covering a domain AND a technology product yields exactly
    two records — one Domain Registration, one Technology Purchase — never a
    hijacked/duplicated domain row."""
    pay = _pay(pay_id="pay_multi", order_id="order_multi", amount=500000)
    order_row = {
        "id": uuid.uuid4(), "created_at": _now(), "domain_name": "card",
        "domain_extension": ".com", "buyer_full_name": "N A",
        "buyer_email": "buyer@example.com", "buyer_phone": None, "buyer_id": None,
        "price_inr": 499000, "status": "ACTIVE", "resellerclub_order_id": None,
        "open_provider_domain_id": "30000042", "open_provider_status": "ACT",
        "price_source": "OpenProvider", "provision_message": None,
        "razorpay_order_id": "order_multi", "razorpay_payment_id": "pay_multi",
        "transfer_status": "NONE",
    }
    purchase_row = {
        "id": uuid.uuid4(), "created_at": _now(), "software_id": uuid.uuid4(),
        "buyer_id": uuid.uuid4(), "buyer_full_name": "N A",
        "buyer_email": "buyer@example.com", "buyer_phone": None,
        "gross_amount_inr": 1000, "payment_status": "COMPLETED",
        "razorpay_order_id": "order_multi", "razorpay_payment_id": "pay_multi",
        "software_name": "Invoice AI",
    }
    session = FakeSession({
        "domain_registration_orders": [order_row],
        "software_purchases": [purchase_row],
        "cobrother_requests": [],
        "technology_services_catalogue": [],
        "software_listings": [],
        "venture_deal_transactions": [],
        "domain_listings": [],
        "users": [],
    })
    repo = FakeRepo()

    await _run_sync(session, repo, [pay])

    records = repo.by_payment.get("pay_multi", [])
    assert len(records) == 2
    cats = sorted(r.category for r in records)
    assert cats == [
        TrackRecordCategory.DOMAIN_REGISTRATION_OPENPROVIDER,
        TrackRecordCategory.TECHNOLOGY_PURCHASE,
    ]
    domain_rec = next(r for r in records if r.category == TrackRecordCategory.DOMAIN_REGISTRATION_OPENPROVIDER)
    tech_rec = next(r for r in records if r.category == TrackRecordCategory.TECHNOLOGY_PURCHASE)
    assert domain_rec.item_name == "card.com"
    assert domain_rec.overall_status == OverallStatus.SUCCESS
    assert tech_rec.item_name == "Invoice AI"
    assert tech_rec.overall_status == OverallStatus.SUCCESS


async def test_two_domains_one_payment_separate_records():
    """Two domains in one payment => two legitimate domain records (one per
    order), each with its own internal id."""
    pay = _pay(pay_id="pay_dom2", order_id="order_dom2")
    rows = []
    for i, dom in enumerate(("alpha", "beta")):
        rows.append({
            "id": uuid.uuid4(), "created_at": _now(), "domain_name": dom,
            "domain_extension": ".com", "buyer_full_name": "N A",
            "buyer_email": "buyer@example.com", "buyer_phone": None, "buyer_id": None,
            "price_inr": 999, "status": "ACTIVE", "resellerclub_order_id": None,
            "open_provider_domain_id": f"30000{i}00", "open_provider_status": "ACT",
            "price_source": "OpenProvider", "provision_message": None,
            "razorpay_order_id": "order_dom2", "razorpay_payment_id": "pay_dom2",
            "transfer_status": "NONE",
        })
    session = FakeSession({
        "domain_registration_orders": rows,
        "software_purchases": [],
        "cobrother_requests": [],
        "technology_services_catalogue": [],
        "software_listings": [],
        "venture_deal_transactions": [],
        "domain_listings": [],
        "users": [],
    })
    repo = FakeRepo()

    await _run_sync(session, repo, [pay])

    records = repo.by_payment.get("pay_dom2", [])
    assert len(records) == 2
    names = sorted(r.item_name for r in records)
    assert names == ["alpha.com", "beta.com"]
    assert len({r.internal_order_id for r in records}) == 2


async def test_recovery_converges_on_existing_record_no_duplicate():
    """A technology purchase already recorded by cart checkout (TRK-{order}-
    {item}, PROVISIONED/Success) must be UPDATED by the recovery — never
    duplicated into a second record."""
    pay = _pay(pay_id="pay_conv", order_id="order_conv")
    existing = TrackRecord(
        internal_order_id="TRK-order_conv-item1",
        category=TrackRecordCategory.TECHNOLOGY_PURCHASE,
        provider_subcategory="Razorpay",
        item_name="Invoice AI",
        payment_status="CAPTURED",
        fulfillment_status="PROVISIONED",
        overall_status="Success",
        razorpay_order_id="order_conv",
        razorpay_payment_id="pay_conv",
    )
    existing.id = uuid.uuid4()
    purchase_row = {
        "id": uuid.uuid4(), "created_at": _now(), "software_id": uuid.uuid4(),
        "buyer_id": uuid.uuid4(), "buyer_full_name": "N A",
        "buyer_email": "buyer@example.com", "buyer_phone": None,
        "gross_amount_inr": 1299, "payment_status": "COMPLETED",
        "razorpay_order_id": "order_conv", "razorpay_payment_id": "pay_conv",
        "software_name": "Invoice AI",
    }
    session = FakeSession({
        "domain_registration_orders": [],
        "software_purchases": [purchase_row],
        "cobrother_requests": [],
        "technology_services_catalogue": [],
        "software_listings": [],
        "venture_deal_transactions": [],
        "domain_listings": [],
        "users": [],
    })
    repo = FakeRepo()
    await repo.save(existing)

    await _run_sync(session, repo, [pay])

    records = repo.by_payment.get("pay_conv", [])
    assert len(records) == 1, "recovery must converge on the existing record"
    assert records[0].id == existing.id
    assert records[0].item_name == "Invoice AI"
    assert records[0].overall_status == OverallStatus.SUCCESS
    assert records[0].error_code is None


async def test_recovery_does_not_downgrade_confirmed_domain_success():
    """A confirmed successful domain (PROVISIONED/Success + real OP id) must
    stay Success even when the order row is momentarily PAYMENT_COMPLETED."""
    pay = _pay(pay_id="pay_domx", order_id="order_domx")
    existing = TrackRecord(
        internal_order_id="TRK-REG-77",
        category=TrackRecordCategory.DOMAIN_REGISTRATION_OPENPROVIDER,
        provider_subcategory="OpenProvider",
        item_name="card.com",
        payment_status="CAPTURED",
        fulfillment_status="PROVISIONED",
        overall_status="Success",
        openprovider_domain_id="30000099",
        razorpay_order_id="order_domx",
        razorpay_payment_id="pay_domx",
    )
    existing.id = uuid.uuid4()
    order_row = {
        "id": "77", "created_at": _now(), "domain_name": "card",
        "domain_extension": ".com", "buyer_full_name": "N A",
        "buyer_email": "buyer@example.com", "buyer_phone": None, "buyer_id": None,
        "price_inr": 999, "status": "PAYMENT_COMPLETED", "resellerclub_order_id": None,
        "open_provider_domain_id": "30000099", "open_provider_status": "REQ",
        "price_source": "OpenProvider", "provision_message": None,
        "razorpay_order_id": "order_domx", "razorpay_payment_id": "pay_domx",
        "transfer_status": "NONE",
    }
    session = FakeSession({
        "domain_registration_orders": [order_row],
        "software_purchases": [],
        "cobrother_requests": [],
        "technology_services_catalogue": [],
        "software_listings": [],
        "venture_deal_transactions": [],
        "domain_listings": [],
        "users": [],
    })
    repo = FakeRepo()
    await repo.save(existing)

    await _run_sync(session, repo, [pay])

    records = repo.by_payment.get("pay_domx", [])
    assert len(records) == 1
    assert records[0].overall_status == OverallStatus.SUCCESS
    assert records[0].fulfillment_status == FulfillmentStatus.PROVISIONED
    assert records[0].id == existing.id


async def test_venture_recovery_no_domain_statuses():
    """A venture deal transaction yields a Venture / Deal Payment record with
    no registration/transfer/renewal statuses and no domain errors."""
    pay = _pay(pay_id="pay_vent", order_id="order_vent", amount=10000000)
    tx_row = {
        "id": uuid.uuid4(), "created_at": _now(), "buyer_id": uuid.uuid4(),
        "seller_id": uuid.uuid4(), "gross_amount_inr": 100000,
        "deal_status": "ESCROW_HELD", "escrow_status": "HELD",
        "razorpay_order_id": "order_vent", "razorpay_payment_id": "pay_vent",
        "venture_name": "Growth Brand",
    }
    session = FakeSession({
        "domain_registration_orders": [],
        "software_purchases": [],
        "cobrother_requests": [],
        "technology_services_catalogue": [],
        "software_listings": [],
        "venture_deal_transactions": [tx_row],
        "domain_listings": [],
        "users": [],
    })
    repo = FakeRepo()

    await _run_sync(session, repo, [pay])

    records = repo.by_payment.get("pay_vent", [])
    assert len(records) == 1
    rec = records[0]
    assert rec.category == TrackRecordCategory.VENTURE_DEAL_PAYMENT
    assert rec.item_name == "Growth Brand"
    assert rec.error_code is None
    d = rec.to_dict()
    assert d["operationType"] == "deal"
    assert d["registrationLabel"] == "—"


async def test_recovery_clears_stale_domain_error_on_tech_record():
    """A technology record that was wrongly stamped NO_REGISTRATION_ORDER by an
    old sync is repaired once the real software purchase is found — the domain
    error is wiped and the record becomes a successful Technology Purchase."""
    pay = _pay(pay_id="pay_repair", order_id="order_repair")
    existing = TrackRecord(
        internal_order_id="TRK-order_repair-item1",
        category=TrackRecordCategory.DOMAIN_REGISTRATION_OPENPROVIDER,
        item_name="Invoice AI",
        payment_status="CAPTURED",
        fulfillment_status="FAILED",
        overall_status="Failed",
        error_code="NO_REGISTRATION_ORDER",
        error_source="PAYMENT_CAPTURED_NO_REGISTRATION_ORDER",
        error_message="Payment captured at Razorpay but no domain_registration_orders row was found.",
        razorpay_order_id="order_repair",
        razorpay_payment_id="pay_repair",
    )
    existing.id = uuid.uuid4()
    purchase_row = {
        "id": uuid.uuid4(), "created_at": _now(), "software_id": uuid.uuid4(),
        "buyer_id": uuid.uuid4(), "buyer_full_name": "N A",
        "buyer_email": "buyer@example.com", "buyer_phone": None,
        "gross_amount_inr": 1499, "payment_status": "COMPLETED",
        "razorpay_order_id": "order_repair", "razorpay_payment_id": "pay_repair",
        "software_name": "Invoice AI",
    }
    session = FakeSession({
        "domain_registration_orders": [],
        "software_purchases": [purchase_row],
        "cobrother_requests": [],
        "technology_services_catalogue": [],
        "software_listings": [],
        "venture_deal_transactions": [],
        "domain_listings": [],
        "users": [],
    })
    repo = FakeRepo()
    await repo.save(existing)

    await _run_sync(session, repo, [pay])

    records = repo.by_payment.get("pay_repair", [])
    assert len(records) == 1
    rec = records[0]
    assert rec.category == TrackRecordCategory.TECHNOLOGY_PURCHASE
    assert rec.overall_status == OverallStatus.SUCCESS
    assert rec.error_code is None
    assert "NO_REGISTRATION_ORDER" not in str(rec.error_code or "")
    assert rec.to_dict()["registrationLabel"] == "—"


async def test_two_payments_same_service_two_records_no_merge():
    """Two SEPARATE real payments for the SAME technology service (Business
    Phone bought twice, one hour apart — production case order_TPZmo6t9ITms2X
    vs order_TPasOjP90uLNZb) must yield EXACTLY TWO Technology Services
    records, one per payment. Different razorpay order/payment ids prove two
    transactions; the same product name must never merge them, and each
    payment must never gain a second record from the recovery sync."""
    user_id = uuid.uuid4()
    service_id = uuid.uuid4()
    pays = [
        _pay(pay_id="pay_bp1", order_id="order_bp1", amount=225262),
        _pay(pay_id="pay_bp2", order_id="order_bp2", amount=225262),
    ]
    existing_1 = TrackRecord(
        internal_order_id="TRK-order_bp1-item1",
        category=TrackRecordCategory.TECHNOLOGY_SERVICES,
        provider_subcategory="Razorpay",
        item_name="Business Phone",
        payment_status="CAPTURED",
        fulfillment_status="PROVISIONED",
        overall_status="Success",
        amount_charged=1909.00,
        razorpay_order_id="order_bp1",
        razorpay_payment_id="pay_bp1",
    )
    existing_1.id = uuid.uuid4()
    existing_2 = TrackRecord(
        internal_order_id="TRK-order_bp2-item2",
        category=TrackRecordCategory.TECHNOLOGY_SERVICES,
        provider_subcategory="Razorpay",
        item_name="Business Phone",
        payment_status="CAPTURED",
        fulfillment_status="PROVISIONED",
        overall_status="Success",
        amount_charged=1909.00,
        razorpay_order_id="order_bp2",
        razorpay_payment_id="pay_bp2",
    )
    existing_2.id = uuid.uuid4()
    session = FakeSession({
        "domain_registration_orders": [],
        "software_purchases": [],
        "cobrother_requests": [
            {
                "id": uuid.uuid4(), "created_at": _now(), "request_type": "COCREATION",
                "entity_id": service_id, "entity_snapshot": "Business Phone",
                "lister_id": user_id, "razorpay_order_id": "order_bp1",
                "razorpay_payment_id": "pay_bp1",
            },
            {
                "id": uuid.uuid4(), "created_at": _now(), "request_type": "COCREATION",
                "entity_id": service_id, "entity_snapshot": "Business Phone",
                "lister_id": user_id, "razorpay_order_id": "order_bp2",
                "razorpay_payment_id": "pay_bp2",
            },
        ],
        "technology_services_catalogue": [{
            "id": service_id, "slug": "business-phone", "name": "Business Phone",
        }],
        "software_listings": [],
        "technology_subscriptions": [{
            "user_id": str(user_id), "service_slug": "business-phone",
            "plan_code": "starter", "billing_cycle": "monthly", "status": "ACTIVE",
            "current_period_start": _now(), "current_period_end": _now(),
        }],
        "venture_deal_transactions": [],
        "domain_listings": [],
        "users": [{
            "id": user_id, "firstname": "K", "lastname": "K",
            "phone_number": "7975596366", "email": "buyer@example.com",
        }],
    })
    repo = FakeRepo()
    await repo.save(existing_1)
    await repo.save(existing_2)

    await _run_sync(session, repo, pays)

    assert len(repo.by_payment.get("pay_bp1", [])) == 1
    assert len(repo.by_payment.get("pay_bp2", [])) == 1
    all_records = repo.by_payment["pay_bp1"] + repo.by_payment["pay_bp2"]
    assert len(all_records) == 2
    for rec in all_records:
        assert rec.category == TrackRecordCategory.TECHNOLOGY_SERVICES
        assert rec.item_name == "Business Phone"
        assert rec.overall_status == OverallStatus.SUCCESS
        # Checkout's per-item line total (ex-GST) is preserved — the recovery
        # must not overwrite it with the GST-inclusive Razorpay payment total.
        assert rec.amount_charged == 1909.00, "amount_charged must stay the checkout line total"
    assert {r.internal_order_id for r in all_records} == {
        "TRK-order_bp1-item1",
        "TRK-order_bp2-item2",
    }


async def test_recovery_preserves_checkout_amount_on_reuse():
    """The recovery sync reuses a checkout-created Technology Services record
    and must NOT replace its per-item amount (₹1909.00, ex-GST line total) with
    the whole-payment amount (₹2252.62, GST-inclusive). One payment => exactly
    one record."""
    user_id = uuid.uuid4()
    service_id = uuid.uuid4()
    pay = _pay(pay_id="pay_bp_single", order_id="order_bp_single", amount=225262)
    existing = TrackRecord(
        internal_order_id="TRK-order_bp_single-item1",
        category=TrackRecordCategory.TECHNOLOGY_SERVICES,
        provider_subcategory="Razorpay",
        item_name="Business Phone",
        payment_status="CAPTURED",
        fulfillment_status="PROVISIONED",
        overall_status="Success",
        amount_charged=1909.00,
        razorpay_order_id="order_bp_single",
        razorpay_payment_id="pay_bp_single",
    )
    existing.id = uuid.uuid4()
    session = FakeSession({
        "domain_registration_orders": [],
        "software_purchases": [],
        "cobrother_requests": [{
            "id": uuid.uuid4(), "created_at": _now(), "request_type": "COCREATION",
            "entity_id": service_id, "entity_snapshot": "Business Phone",
            "lister_id": user_id, "razorpay_order_id": "order_bp_single",
            "razorpay_payment_id": "pay_bp_single",
        }],
        "technology_services_catalogue": [{
            "id": service_id, "slug": "business-phone", "name": "Business Phone",
        }],
        "software_listings": [],
        "technology_subscriptions": [{
            "user_id": str(user_id), "service_slug": "business-phone",
            "plan_code": "starter", "billing_cycle": "monthly", "status": "ACTIVE",
            "current_period_start": _now(), "current_period_end": _now(),
        }],
        "venture_deal_transactions": [],
        "domain_listings": [],
        "users": [{
            "id": user_id, "firstname": "K", "lastname": "K",
            "phone_number": "7975596366", "email": "buyer@example.com",
        }],
    })
    repo = FakeRepo()
    await repo.save(existing)

    await _run_sync(session, repo, [pay])

    records = repo.by_payment.get("pay_bp_single", [])
    assert len(records) == 1, "one payment must yield exactly one record"
    rec = records[0]
    assert rec.id == existing.id
    assert rec.amount_charged == 1909.00
    assert rec.category == TrackRecordCategory.TECHNOLOGY_SERVICES
    assert rec.overall_status == OverallStatus.SUCCESS


async def test_same_product_name_never_merges_distinct_transactions():
    """'Business Phone' purchased as a genuine one-time software product is a
    Technology Purchase; the same display name bought through the provider
    service flow is a Technology Services transaction. Product name alone must
    never merge or re-categorize either record."""
    user_id = uuid.uuid4()
    listing_id = uuid.uuid4()
    service_id = uuid.uuid4()
    pays = [
        _pay(pay_id="pay_sw", order_id="order_sw", amount=129900),
        _pay(pay_id="pay_tsv", order_id="order_tsv", amount=225262),
    ]
    purchase_row = {
        "id": uuid.uuid4(), "created_at": _now(), "software_id": listing_id,
        "buyer_id": user_id, "buyer_full_name": "K K",
        "buyer_email": "buyer@example.com", "buyer_phone": "7975596366",
        "gross_amount_inr": 1299, "payment_status": "COMPLETED",
        "razorpay_order_id": "order_sw", "razorpay_payment_id": "pay_sw",
        "software_name": "Business Phone",
    }
    session = FakeSession({
        "domain_registration_orders": [],
        "software_purchases": [purchase_row],
        "cobrother_requests": [{
            "id": uuid.uuid4(), "created_at": _now(), "request_type": "COCREATION",
            "entity_id": service_id, "entity_snapshot": "Business Phone",
            "lister_id": user_id, "razorpay_order_id": "order_tsv",
            "razorpay_payment_id": "pay_tsv",
        }],
        "technology_services_catalogue": [{
            "id": service_id, "slug": "business-phone", "name": "Business Phone",
        }],
        "software_listings": [],
        "technology_subscriptions": [{
            "user_id": str(user_id), "service_slug": "business-phone",
            "plan_code": "starter", "billing_cycle": "monthly", "status": "ACTIVE",
            "current_period_start": _now(), "current_period_end": _now(),
        }],
        "venture_deal_transactions": [],
        "domain_listings": [],
        "users": [{
            "id": user_id, "firstname": "K", "lastname": "K",
            "phone_number": "7975596366", "email": "buyer@example.com",
        }],
    })
    repo = FakeRepo()

    await _run_sync(session, repo, pays)

    sw_records = repo.by_payment.get("pay_sw", [])
    tsv_records = repo.by_payment.get("pay_tsv", [])
    assert len(sw_records) == 1
    assert len(tsv_records) == 1
    assert sw_records[0].category == TrackRecordCategory.TECHNOLOGY_PURCHASE
    assert tsv_records[0].category == TrackRecordCategory.TECHNOLOGY_SERVICES
    assert sw_records[0].item_name == "Business Phone"
    assert tsv_records[0].item_name == "Business Phone"
    # The software purchase record keeps its own gross amount (per-item), and
    # the tech-service record keeps its checkout line total.
    assert sw_records[0].amount_charged == 1299
    assert tsv_records[0].amount_charged == 2252.62  # brand-new record: payment amount
    assert sw_records[0].to_dict()["registrationLabel"] == "—"
    assert tsv_records[0].to_dict()["registrationLabel"] == "—"


@pytest.mark.asyncio
async def test_payment_mode_resolution_times_out_on_slow_razorpay(monkeypatch):
    """A slow / unreachable Razorpay account must never hang the admin page:
    per-payment mode resolution is time-bounded and falls back to None (the
    frontend renders '—'), even when the underlying SDK call never returns."""
    import asyncio
    import time

    from app.service.platform import track_record_service as trs_mod

    service = TrackRecordService(AsyncMock())

    class _SlowClient:
        def resolve_payment_environment(self, pid):
            time.sleep(1.0)  # simulate a hung Razorpay network call
            return "LIVE"

    monkeypatch.setattr(trs_mod, "PAYMENT_MODE_RESOLVE_TIMEOUT_SECONDS", 0.2)

    payloads = [{}]
    start = time.monotonic()
    await service._resolve_payment_modes({0: "pay_slow"}, payloads, _SlowClient())
    elapsed = time.monotonic() - start

    assert elapsed < 0.8, f"payment mode resolution hung for {elapsed:.2f}s"
    assert payloads[0]["paymentMode"] is None


@pytest.mark.asyncio
async def test_recovery_sync_fetch_recent_payments_times_out(monkeypatch):
    """The recovery sync bounds its Razorpay recent-payments fetch so a dead
    network degrades to 'no payments scanned' instead of hanging the sync."""
    import time

    from app.service.platform import track_record_service as trs_mod

    service = TrackRecordService(AsyncMock())

    def _hung_fetch(count):
        time.sleep(1.0)  # simulate a hung Razorpay API call
        return []

    monkeypatch.setattr(trs_mod, "RAZORPAY_RECENT_PAYMENTS_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(
        "app.integrations.razorpay.client.fetch_recent_payments",
        _hung_fetch,
    )

    start = time.monotonic()
    result = await service.sync_razorpay_missing_payments()
    elapsed = time.monotonic() - start

    assert elapsed < 0.8, f"recent-payments fetch hung for {elapsed:.2f}s"
    assert result == 0
