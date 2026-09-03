"""Transfer-vs-registration safety tests (OpenProvider-only, mocks only).

Covers the confirmed drygrain.com bug class: a legitimate domain transfer
(transfer_status != NONE) must never be failed by the registration
stale-pending timeout, must never reach provision_order(), must map to the
DOMAIN_TRANSFER track record category, and must never re-submit
transfer_domain() when an OpenProvider domain id already exists.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.entity.platform.track_record_entity import TrackRecord
from app.repository.domain_registration_order_repository import (
    DomainRegistrationOrderRepository,
)
from app.service.domain.domain_registration_followup import (
    DomainRegistrationFollowup,
)
from app.service.domain.domain_registration_ops_service import (
    DomainRegistrationOpsService,
)
from app.service.domain.domain_registration_service import DomainRegistrationService
from app.service.platform.track_record_service import (
    FulfillmentStatus,
    OverallStatus,
    PaymentStatus,
    TrackRecordCategory,
    TrackRecordService,
)
from app.utils.registration_enums import RegistrationOrderStatus


def _order(**kwargs) -> DomainRegistrationOrder:
    o = DomainRegistrationOrder(
        id=uuid4(),
        domain_name="brand",
        domain_extension=".com",
        buyer_id=uuid4(),
        buyer_email="buyer@example.com",
        period_years=1,
        price_inr=999.0,
        status=RegistrationOrderStatus.REGISTRATION_PENDING,
        transfer_status="NONE",
        open_provider_domain_id="12345",
    )
    for k, v in kwargs.items():
        setattr(o, k, v)
    return o


@pytest.mark.asyncio
async def test_recover_stale_pending_skips_transfer_but_still_fails_registration():
    """A pending transfer is never failed by the registration timeout, while a
    stale registration still is (normal registrations unchanged)."""
    past = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    transfer = _order(
        status=RegistrationOrderStatus.REGISTRATION_PENDING,
        transfer_status="PENDING",
        open_provider_domain_id="30069045",
        provision_message=f"PENDING_SINCE:{past}|transfer submitted",
    )
    registration = _order(
        status=RegistrationOrderStatus.REGISTRATION_PENDING,
        transfer_status="NONE",
        open_provider_domain_id="999",
        provision_message=f"PENDING_SINCE:{past}|waiting",
    )

    mock_orders = AsyncMock()
    mock_orders.list_open_pending = AsyncMock(return_value=[transfer, registration])
    mock_orders.save = AsyncMock()
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    followup = DomainRegistrationFollowup(session=mock_session)
    followup._orders = mock_orders
    followup.sync_from_registrar = AsyncMock(return_value=(False, registration))
    followup.send_lifecycle_emails = AsyncMock()

    with patch("app.service.domain.domain_registration_followup.settings") as mock_settings:
        mock_settings.DOMAIN_REGISTRATION_PENDING_TIMEOUT_MINUTES = 10.0
        stats = await followup.recover_stale_registration_pending()

    # Only the registration was examined and failed.
    assert stats["examined"] == 1
    assert stats["failed"] == 1
    assert registration.status == RegistrationOrderStatus.PROVISION_FAILED
    # Transfer untouched — not stamped, not failed, message unchanged.
    assert transfer.status == RegistrationOrderStatus.REGISTRATION_PENDING
    assert transfer.provision_message == f"PENDING_SINCE:{past}|transfer submitted"
    assert stats["reconciled_active"] == 0
    assert stats["retried"] == 0


@pytest.mark.asyncio
async def test_recover_stale_pending_skips_payment_completed_transfer():
    """Transfers in PAYMENT_COMPLETED are also excluded from the recovery."""
    past = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    transfer = _order(
        status=RegistrationOrderStatus.PAYMENT_COMPLETED,
        transfer_status="PENDING",
        open_provider_domain_id="30069045",
        provision_message=f"PENDING_SINCE:{past}",
    )
    mock_orders = AsyncMock()
    mock_orders.list_open_pending = AsyncMock(return_value=[transfer])
    mock_orders.save = AsyncMock()
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    followup = DomainRegistrationFollowup(session=mock_session)
    followup._orders = mock_orders
    followup.send_lifecycle_emails = AsyncMock()

    with patch("app.service.domain.domain_registration_followup.settings") as mock_settings:
        mock_settings.DOMAIN_REGISTRATION_PENDING_TIMEOUT_MINUTES = 10.0
        stats = await followup.recover_stale_registration_pending()

    assert stats["examined"] == 0
    assert stats["failed"] == 0
    assert transfer.status == RegistrationOrderStatus.PAYMENT_COMPLETED
    mock_orders.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_provision_retries_never_routes_transfer_to_provision_order():
    """A transfer in the retry candidates never reaches provision_order() and
    never aborts the scheduler tick."""
    transfer = _order(
        status=RegistrationOrderStatus.PROVISION_FAILED,
        transfer_status="PENDING",
        open_provider_domain_id="30069045",
    )
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    service = DomainRegistrationOpsService(session)
    service._orders = AsyncMock()
    service._orders.list_provision_retry_candidates = AsyncMock(return_value=[transfer])
    service._registration = MagicMock()
    service._registration.provision_order = AsyncMock()

    count = await service.run_provision_retries(max_attempts=5)

    assert count == 0
    service._registration.provision_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_provision_transfer_adopts_existing_op_id_without_resubmit():
    """_provision_transfer() with an existing OpenProvider domain id must never
    call transfer_domain() again — it adopts the existing registrar record."""
    order = _order(
        status=RegistrationOrderStatus.REGISTRATION_PENDING,
        transfer_status="PENDING",
        transfer_auth_code="AUTH-123",
        open_provider_domain_id="30069045",
    )
    session = AsyncMock()
    service = DomainRegistrationService(session)
    service._orders = AsyncMock()
    service._orders.save = AsyncMock()
    buyer = SimpleNamespace(
        phone_number="+919380861004",
        firstname="N",
        lastname="A",
        full_name="N A",
        email="buyer@example.com",
    )

    with patch(
        "app.service.domain.domain_registration_service.active_registrar"
    ) as mock_reg:
        result = await service._provision_transfer(order, buyer=buyer)

    mock_reg.assert_not_called()
    assert order.status == RegistrationOrderStatus.REGISTRATION_PENDING
    assert order.transfer_status == "PENDING"
    assert result["transferStatus"] == "PENDING"
    service._orders.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_track_record_transfer_mapping():
    """Transfer + Razorpay captured + OP pending maps to DOMAIN_TRANSFER with
    CAPTURED / IN_PROGRESS / PENDING."""
    order = _order(
        status=RegistrationOrderStatus.REGISTRATION_PENDING,
        transfer_status="PENDING",
        razorpay_order_id="order_TR1",
        razorpay_payment_id="pay_TR1",
        open_provider_domain_id="30069045",
        price_inr=1270.97,
    )
    session = AsyncMock()
    service = TrackRecordService(session)
    service._repo = AsyncMock()
    service._repo.find_by_internal_order_id = AsyncMock(return_value=None)
    service._repo.save = AsyncMock(side_effect=lambda rec: rec)

    rec = await service.record_from_registration_order(order, cart_batch_id="order_TR1")

    assert rec.category == TrackRecordCategory.DOMAIN_TRANSFER
    assert rec.provider_subcategory == "OpenProvider"
    assert rec.payment_status == PaymentStatus.CAPTURED
    assert rec.fulfillment_status == FulfillmentStatus.IN_PROGRESS
    assert rec.overall_status == OverallStatus.PENDING
    assert rec.openprovider_domain_id == "30069045"


def test_track_record_operation_fields():
    """to_dict exposes operation-aware fields so the admin UI can render a
    dedicated Transfer / Renewal column instead of the Registration column."""
    base = dict(
        category=TrackRecordCategory.DOMAIN_TRANSFER,
        provider_subcategory="OpenProvider",
        payment_status="CAPTURED",
        item_name="drygrain.com",
        amount_charged=1270.97,
        currency="INR",
        openprovider_domain_id="30069045",
        internal_order_id="TRK-REG-abc",
        fulfillment_status="IN_PROGRESS",
        overall_status="Pending",
    )
    tr = TrackRecord(**base)
    d = tr.to_dict()
    assert d["operationType"] == "transfer"
    assert d["operationTitle"] == "Transfer"
    assert d["operationStatus"] == "PENDING"

    reg = TrackRecord(**{**base, "category": TrackRecordCategory.DOMAIN_REGISTRATION_OPENPROVIDER})
    assert reg.to_dict()["operationType"] == "registration"
    assert reg.to_dict()["operationTitle"] == "Registration"

    ren = TrackRecord(**{**base, "category": TrackRecordCategory.DOMAIN_RENEWAL})
    ren_dict = ren.to_dict()
    assert ren_dict["operationType"] == "renewal"
    assert ren_dict["operationTitle"] == "Renewal"


def test_track_record_transfer_label_pending_then_ok():
    """In-progress transfers label PENDING; completed transfers label OK."""
    base = dict(
        category=TrackRecordCategory.DOMAIN_TRANSFER,
        provider_subcategory="OpenProvider",
        payment_status="CAPTURED",
        item_name="drygrain.com",
        amount_charged=1270.97,
        currency="INR",
        openprovider_domain_id="30069045",
        internal_order_id="TRK-REG-abc",
    )
    pending = TrackRecord(**base, fulfillment_status="IN_PROGRESS", overall_status="Pending")
    assert pending.to_dict()["registrationLabel"] == "PENDING"

    done = TrackRecord(**base, fulfillment_status="PROVISIONED", overall_status="Success")
    assert done.to_dict()["registrationLabel"] == "OK"


@pytest.mark.asyncio
async def test_registration_pending_queries_exclude_transfers():
    """list_open_pending / list_stale_pending / list_provision_retry_candidates
    must filter out transfer orders (transfer_status = 'NONE')."""
    def _mock_session() -> AsyncMock:
        scalars_mock = MagicMock()
        scalars_mock.all = MagicMock(return_value=[])
        result_mock = MagicMock()
        result_mock.scalars = MagicMock(return_value=scalars_mock)
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)
        return session

    cases = [
        ("list_open_pending", {}),
        ("list_stale_pending", {"cutoff": datetime.now(timezone.utc)}),
        ("list_provision_retry_candidates", {"max_attempts": 5}),
    ]
    for method, kwargs in cases:
        session = _mock_session()
        repo = DomainRegistrationOrderRepository(session)
        await getattr(repo, method)(**kwargs)
        stmt = session.execute.call_args.args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "transfer_status" in compiled, f"{method} must filter transfers"
        assert "transfer_status = 'NONE'" in compiled, f"{method} must filter transfers"


@pytest.mark.asyncio
async def test_pending_reconcile_query_keeps_transfers():
    """The safe sync-only reconciliation path (list_pending_reconcile_candidates)
    must keep seeing transfers so they complete when OpenProvider confirms."""
    scalars_mock = MagicMock()
    scalars_mock.all = MagicMock(return_value=[])
    result_mock = MagicMock()
    result_mock.scalars = MagicMock(return_value=scalars_mock)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)
    repo = DomainRegistrationOrderRepository(session)
    await repo.list_pending_reconcile_candidates()
    stmt = session.execute.call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    # The column may appear in the SELECT list; the point is there is NO
    # transfer_status WHERE filter on this safe reconciliation query.
    assert "transfer_status = 'NONE'" not in compiled


# ── sync_razorpay_missing_payments status mapping ────────────────────────────


def _order_row(**kwargs) -> dict:
    base = {
        "status": "REGISTRATION_PENDING",
        "transfer_status": "NONE",
        "open_provider_domain_id": None,
        "open_provider_status": None,
        "provision_message": None,
    }
    base.update(kwargs)
    return base


def _sync_status(order_row: dict, *, is_transfer: bool, op_domain_id=None, demo_op=False):
    return TrackRecordService._status_for_sync_order(
        order_row,
        is_transfer=is_transfer,
        target_provider="OpenProvider",
        op_domain_id=op_domain_id,
        demo_op=demo_op,
    )


def test_sync_status_transfer_stale_provision_failed_stays_in_progress():
    """THE drygrain regression: a submitted transfer whose order carries a stale
    PROVISION_FAILED must stay IN_PROGRESS / Pending with no error — never
    REGISTRATION_FAILED / Failed."""
    f, o, src, code, msg = _sync_status(
        _order_row(
            status="PROVISION_FAILED",
            transfer_status="PENDING",
            open_provider_status="REQ",
            provision_message="Registration left REGISTRATION_PENDING for over 10 minutes...",
        ),
        is_transfer=True,
        op_domain_id="30069045",
    )
    assert f == FulfillmentStatus.IN_PROGRESS
    assert o == OverallStatus.PENDING
    assert (src, code, msg) == (None, None, None)


def test_sync_status_transfer_in_progress_no_error():
    """Transfer + Razorpay CAPTURED + OP transfer REQ -> IN_PROGRESS / Pending."""
    f, o, src, code, msg = _sync_status(
        _order_row(
            status="REGISTRATION_PENDING",
            transfer_status="PENDING",
            open_provider_status="REQ",
        ),
        is_transfer=True,
        op_domain_id="30069045",
    )
    assert f == FulfillmentStatus.IN_PROGRESS
    assert o == OverallStatus.PENDING
    assert (src, code, msg) == (None, None, None)


def test_sync_status_transfer_completed_success():
    """Transfer completed at OpenProvider -> PROVISIONED / Success."""
    f, o, src, code, msg = _sync_status(
        _order_row(
            status="ACTIVE",
            transfer_status="PENDING",
            open_provider_status="ACT",
        ),
        is_transfer=True,
        op_domain_id="30069045",
    )
    assert f == FulfillmentStatus.PROVISIONED
    assert o == OverallStatus.SUCCESS
    assert (src, code, msg) == (None, None, None)


@pytest.mark.parametrize("op_status", ["FAILED", "REJECTED", "CANCELLED"])
def test_sync_status_transfer_terminal_failure_uses_transfer_error(op_status):
    """A genuine terminal failure at OpenProvider is a TRANSFER failure
    (TRANSFER_FAILED), never REGISTRATION_FAILED."""
    f, o, src, code, msg = _sync_status(
        _order_row(
            status="PROVISION_FAILED",
            transfer_status="PENDING",
            open_provider_status=op_status,
            provision_message="OP rejected the transfer",
        ),
        is_transfer=True,
        op_domain_id="30069045",
    )
    assert f == FulfillmentStatus.FAILED
    assert o == OverallStatus.FAILED
    assert src == "OPENPROVIDER_TRANSFER_FAILED"
    assert code == "TRANSFER_FAILED"
    assert msg == "OP rejected the transfer"
    assert "REGISTRATION_FAILED" not in code


def test_sync_status_transfer_demo_op_is_failure():
    """A DEMO OpenProvider id is never success for a transfer either."""
    f, o, src, code, _msg = _sync_status(
        _order_row(
            status="REGISTRATION_PENDING",
            transfer_status="PENDING",
            open_provider_status="REQ",
        ),
        is_transfer=True,
        op_domain_id="DEMO-1",
        demo_op=True,
    )
    assert f == FulfillmentStatus.FAILED
    assert o == OverallStatus.FAILED
    assert code == "TRANSFER_FAILED"


def test_sync_status_registration_failure_unchanged():
    """Normal registrations keep the existing REGISTRATION_FAILED mapping."""
    f, o, src, code, msg = _sync_status(
        _order_row(
            status="PROVISION_FAILED",
            transfer_status="NONE",
            provision_message="Registered domain failed",
        ),
        is_transfer=False,
        op_domain_id="12345",
    )
    assert f == FulfillmentStatus.FAILED
    assert o == OverallStatus.FAILED
    assert src == "OPENPROVIDER_REGISTRATION_FAILED"
    assert code == "REGISTRATION_FAILED"
    assert msg == "Registered domain failed"


def test_sync_status_registration_expired_unchanged():
    """EXPIRED registrations keep existing sync behavior (stays IN_PROGRESS —
    the sync's is_failed only ever matched FAIL/CANCEL/demo)."""
    f, o, src, code, msg = _sync_status(
        _order_row(status="EXPIRED", transfer_status="NONE"),
        is_transfer=False,
        op_domain_id=None,
    )
    assert f == FulfillmentStatus.IN_PROGRESS
    assert o == OverallStatus.PENDING
    assert (src, code, msg) == (None, None, None)


def test_sync_status_registration_success_unchanged():
    """ACTIVE registrations with a real OP id remain PROVISIONED / Success."""
    f, o, src, code, msg = _sync_status(
        _order_row(status="ACTIVE", transfer_status="NONE"),
        is_transfer=False,
        op_domain_id="12345",
    )
    assert f == FulfillmentStatus.PROVISIONED
    assert o == OverallStatus.SUCCESS
    assert (src, code, msg) == (None, None, None)


def _stale_failed_record() -> TrackRecord:
    return TrackRecord(
        internal_order_id="TRK-REG-76f04ba3-332d-46ef-afb7-c5d72c5f7a76",
        category=TrackRecordCategory.DOMAIN_TRANSFER,
        item_name="drygrain.com",
        payment_status="CAPTURED",
        fulfillment_status="FAILED",
        overall_status="Failed",
        error_code="REGISTRATION_FAILED",
        error_source="OPENPROVIDER_REGISTRATION_FAILED",
        error_message="stale failure from previous sync",
        amount_charged=1270.97,
        openprovider_domain_id="30069045",
    )


@pytest.mark.asyncio
async def test_record_paid_attempt_clears_stale_errors_for_transfer_sync():
    """The Razorpay sync (clear_errors=True) wipes stale REGISTRATION_FAILED
    diagnostics when a transfer is back IN_PROGRESS, and the overall status is
    recomputed to Pending (not Failed)."""
    session = AsyncMock()
    service = TrackRecordService(session)
    existing = _stale_failed_record()
    service._repo = AsyncMock()
    service._repo.find_by_internal_order_id = AsyncMock(return_value=existing)
    service._repo.save = AsyncMock(side_effect=lambda rec: rec)

    rec = await service.record_paid_attempt(
        internal_order_id="TRK-REG-76f04ba3-332d-46ef-afb7-c5d72c5f7a76",
        category=TrackRecordCategory.DOMAIN_TRANSFER,
        provider_subcategory="OpenProvider",
        item_name="drygrain.com",
        amount_charged=1270.97,
        payment_status=PaymentStatus.CAPTURED,
        razorpay_payment_id="pay_TNzkDIPuCCQwiI",
        fulfillment_status=FulfillmentStatus.IN_PROGRESS,
        overall_status=OverallStatus.PENDING,
        openprovider_domain_id="30069045",
        error_code=None,
        error_source=None,
        error_message=None,
        clear_errors=True,
    )

    assert rec.fulfillment_status == FulfillmentStatus.IN_PROGRESS
    assert rec.error_code is None
    assert rec.error_source is None
    assert rec.error_message is None
    assert rec.overall_status == OverallStatus.PENDING


@pytest.mark.asyncio
async def test_record_paid_attempt_default_keeps_stale_errors():
    """Without clear_errors the existing truthy-only update contract is kept
    (other callers are unaffected by the sync fix)."""
    session = AsyncMock()
    service = TrackRecordService(session)
    existing = _stale_failed_record()
    service._repo = AsyncMock()
    service._repo.find_by_internal_order_id = AsyncMock(return_value=existing)
    service._repo.save = AsyncMock(side_effect=lambda rec: rec)

    rec = await service.record_paid_attempt(
        internal_order_id="TRK-REG-76f04ba3-332d-46ef-afb7-c5d72c5f7a76",
        category=TrackRecordCategory.DOMAIN_TRANSFER,
        provider_subcategory="OpenProvider",
        item_name="drygrain.com",
        amount_charged=1270.97,
        payment_status=PaymentStatus.CAPTURED,
        fulfillment_status=FulfillmentStatus.IN_PROGRESS,
        overall_status=OverallStatus.PENDING,
        openprovider_domain_id="30069045",
        error_code=None,
    )

    # Default contract: error fields are only ever overwritten when truthy.
    assert rec.error_code == "REGISTRATION_FAILED"
    assert rec.error_source == "OPENPROVIDER_REGISTRATION_FAILED"


# ── abandoned / expired unpaid transfer attempts ─────────────────────────────


def test_sync_status_transfer_abandoned_expired():
    """An EXPIRED transfer order that was never paid and never submitted is an
    abandoned attempt: EXPIRED / Expired, no error — never Pending, never
    REGISTRATION_FAILED."""
    f, o, src, code, msg = _sync_status(
        _order_row(
            status="EXPIRED",
            transfer_status="PAYMENT_PENDING",
            open_provider_domain_id=None,
            open_provider_status=None,
        ),
        is_transfer=True,
        op_domain_id=None,
    )
    assert f == FulfillmentStatus.EXPIRED
    assert o == OverallStatus.EXPIRED
    assert (src, code, msg) == (None, None, None)


def test_sync_status_transfer_abandoned_cancelled():
    """A CANCELLED never-paid transfer is an abandoned attempt too."""
    f, o, src, code, msg = _sync_status(
        _order_row(
            status="CANCELLED",
            transfer_status="PAYMENT_PENDING",
            open_provider_domain_id=None,
        ),
        is_transfer=True,
        op_domain_id=None,
    )
    assert f == FulfillmentStatus.CANCELLED
    assert o == OverallStatus.CANCELLED
    assert (src, code, msg) == (None, None, None)


def test_sync_status_transfer_expired_with_payment_not_abandoned():
    """A paid/submitted transfer that is (anomalously) expired is NOT an
    abandoned attempt — it stays IN_PROGRESS / Pending."""
    f, o, src, code, msg = _sync_status(
        _order_row(
            status="EXPIRED",
            transfer_status="PENDING",
            razorpay_payment_id="pay_abc",
            open_provider_domain_id="30069045",
            open_provider_status="REQ",
        ),
        is_transfer=True,
        op_domain_id="30069045",
    )
    assert f == FulfillmentStatus.IN_PROGRESS
    assert o == OverallStatus.PENDING
    assert (src, code, msg) == (None, None, None)


def test_sync_status_transfer_abandoned_registration_unaffected():
    """EXPIRED normal registrations keep the existing sync behavior (Pending)."""
    f, o, src, code, msg = _sync_status(
        _order_row(
            status="EXPIRED",
            transfer_status="NONE",
            razorpay_payment_id=None,
            open_provider_domain_id=None,
        ),
        is_transfer=False,
        op_domain_id=None,
    )
    assert f == FulfillmentStatus.IN_PROGRESS
    assert o == OverallStatus.PENDING
    assert (src, code, msg) == (None, None, None)


def test_track_record_operation_status_expired():
    """to_dict exposes operationStatus = EXPIRED for an abandoned transfer so the
    admin UI's Transfer column shows EXPIRED instead of PENDING."""
    tr = TrackRecord(
        category=TrackRecordCategory.DOMAIN_TRANSFER,
        provider_subcategory="OpenProvider",
        payment_status="PENDING",
        item_name="drygrain.com",
        amount_charged=1270.97,
        currency="INR",
        internal_order_id="TRK-REG-265e719a-332d-46ef-afb7-c5d72c5f7a76",
        fulfillment_status=FulfillmentStatus.EXPIRED,
        overall_status=OverallStatus.EXPIRED,
    )
    d = tr.to_dict()
    assert d["operationType"] == "transfer"
    assert d["operationStatus"] == "EXPIRED"
    # Backward-compat label for the Registration column stays PENDING-ish.
    assert d["registrationLabel"] == "PENDING"


def test_track_record_operation_status_cancelled():
    """CANCELLED abandoned transfers map to operationStatus = CANCELLED."""
    tr = TrackRecord(
        category=TrackRecordCategory.DOMAIN_TRANSFER,
        provider_subcategory="OpenProvider",
        payment_status="PENDING",
        item_name="drygrain.com",
        amount_charged=1270.97,
        currency="INR",
        internal_order_id="TRK-REG-x",
        fulfillment_status=FulfillmentStatus.CANCELLED,
        overall_status=OverallStatus.CANCELLED,
    )
    assert tr.to_dict()["operationStatus"] == "CANCELLED"


@pytest.mark.asyncio
async def test_record_paid_attempt_preserves_expired_overall():
    """record_paid_attempt keeps an explicitly-passed Expired/Cancelled overall
    (abandoned attempt) instead of downgrading it to PENDING."""
    session = AsyncMock()
    service = TrackRecordService(session)
    service._repo = AsyncMock()
    service._repo.find_by_internal_order_id = AsyncMock(return_value=None)
    service._repo.save = AsyncMock(side_effect=lambda rec: rec)

    rec = await service.record_paid_attempt(
        internal_order_id="TRK-REG-265e719a-332d-46ef-afb7-c5d72c5f7a76",
        category=TrackRecordCategory.DOMAIN_TRANSFER,
        provider_subcategory="OpenProvider",
        item_name="drygrain.com",
        amount_charged=1270.97,
        payment_status=PaymentStatus.PENDING,
        fulfillment_status=FulfillmentStatus.EXPIRED,
        overall_status=OverallStatus.EXPIRED,
        error_code=None,
        error_source=None,
        error_message=None,
    )

    assert rec.fulfillment_status == FulfillmentStatus.EXPIRED
    assert rec.overall_status == OverallStatus.EXPIRED
    assert rec.error_code is None


@pytest.mark.asyncio
async def test_sync_historical_reconciles_existing_transfer_record():
    """The admin Sync re-evaluates existing TRANSFER track records from the order
    so an abandoned unpaid attempt is corrected to EXPIRED / Expired (no error).
    Normal registrations keep their existing update contract."""
    session = AsyncMock()
    service = TrackRecordService(session)
    orig_dt = datetime.now(timezone.utc)
    existing = TrackRecord(
        internal_order_id="TRK-REG-265e719a-332d-46ef-afb7-c5d72c5f7a76",
        category=TrackRecordCategory.DOMAIN_TRANSFER,
        provider_subcategory="OpenProvider",
        item_name="drygrain.com",
        payment_status="PENDING",
        fulfillment_status="IN_PROGRESS",
        overall_status="Pending",
        amount_charged=1270.97,
        created_at=orig_dt,
    )
    service._repo = AsyncMock()

    async def _find_by_internal_order_id(int_id):
        if str(int_id).startswith("TRK-REG-"):
            return existing
        return None

    service._repo.find_by_internal_order_id = _find_by_internal_order_id
    service._repo.save = AsyncMock(side_effect=lambda rec: rec)
    service.sync_razorpay_missing_payments = AsyncMock(return_value=0)

    order_row = {
        "id": "265e719a-332d-46ef-afb7-c5d72c5f7a76",
        "created_at": orig_dt,
        "domain_name": "drygrain",
        "domain_extension": ".com",
        "period_years": 1,
        "buyer_full_name": "N A",
        "buyer_email": "buyer@example.com",
        "buyer_phone": None,
        "buyer_id": None,
        "price_inr": 1270.97,
        "subtotal_inr": 1077.09,
        "gst_inr": 193.88,
        "razorpay_order_id": None,
        "razorpay_payment_id": None,
        "razorpay_refund_id": None,
        "status": "EXPIRED",
        "resellerclub_order_id": None,
        "open_provider_domain_id": None,
        "open_provider_status": None,
        "price_source": "OpenProvider",
        "provision_message": None,
        "transfer_status": "PAYMENT_PENDING",
    }

    def execute_side_effect(*args, **kwargs):
        result = MagicMock()
        sql_str = str(args[0] if args else "")
        if "domain_registration_orders" in sql_str:
            result.mappings.return_value.all.return_value = [order_row]
        else:
            result.mappings.return_value.all.return_value = []
        return result

    session.execute = AsyncMock(side_effect=execute_side_effect)

    synced = await service.sync_historical_purchases()

    assert synced == 0  # updated in place — no new records
    assert existing.fulfillment_status == FulfillmentStatus.EXPIRED
    assert existing.overall_status == OverallStatus.EXPIRED
    assert existing.error_code is None
    assert existing.error_source is None
    service._repo.save.assert_awaited()


@pytest.mark.asyncio
async def test_sync_historical_pending_transfer_record_stays_pending():
    """A still-pending submitted transfer is left IN_PROGRESS / Pending by the
    historical sync (no downgrade, no failure)."""
    session = AsyncMock()
    service = TrackRecordService(session)
    orig_dt = datetime.now(timezone.utc)
    existing = TrackRecord(
        internal_order_id="TRK-REG-76f04ba3-332d-46ef-afb7-c5d72c5f7a76",
        category=TrackRecordCategory.DOMAIN_TRANSFER,
        provider_subcategory="OpenProvider",
        item_name="drygrain.com",
        payment_status="CAPTURED",
        fulfillment_status="IN_PROGRESS",
        overall_status="Pending",
        amount_charged=1270.97,
        openprovider_domain_id="30069045",
        created_at=orig_dt,
    )
    service._repo = AsyncMock()

    async def _find_by_internal_order_id(int_id):
        if str(int_id).startswith("TRK-REG-"):
            return existing
        return None

    service._repo.find_by_internal_order_id = _find_by_internal_order_id
    service._repo.save = AsyncMock(side_effect=lambda rec: rec)
    service.sync_razorpay_missing_payments = AsyncMock(return_value=0)

    order_row = {
        "id": "76f04ba3-332d-46ef-afb7-c5d72c5f7a76",
        "created_at": orig_dt,
        "domain_name": "drygrain",
        "domain_extension": ".com",
        "period_years": 1,
        "buyer_full_name": "N A",
        "buyer_email": "buyer@example.com",
        "buyer_phone": None,
        "buyer_id": None,
        "price_inr": 1270.97,
        "subtotal_inr": 1077.09,
        "gst_inr": 193.88,
        "razorpay_order_id": "order_TNzjPAXqLhbLPN",
        "razorpay_payment_id": "pay_TNzkDIPuCCQwiI",
        "razorpay_refund_id": None,
        "status": "REGISTRATION_PENDING",
        "resellerclub_order_id": None,
        "open_provider_domain_id": "30069045",
        "open_provider_status": "REQ",
        "price_source": "OpenProvider",
        "provision_message": None,
        "transfer_status": "PENDING",
    }

    def execute_side_effect(*args, **kwargs):
        result = MagicMock()
        sql_str = str(args[0] if args else "")
        if "domain_registration_orders" in sql_str:
            result.mappings.return_value.all.return_value = [order_row]
        else:
            result.mappings.return_value.all.return_value = []
        return result

    session.execute = AsyncMock(side_effect=execute_side_effect)

    await service.sync_historical_purchases()

    assert existing.fulfillment_status == FulfillmentStatus.IN_PROGRESS
    assert existing.overall_status == OverallStatus.PENDING
    assert existing.error_code is None
    # Status unchanged — no save needed beyond the no-op category check.
    service._repo.save.assert_not_awaited()


# ── REFUNDED order / track-record reconciliation safety ─────────────────────


def test_status_for_registration_order_refunded():
    """A REFUNDED registration order maps to PROVISIONED / Refunded with no
    error — never the generic PENDING default."""
    order = _order(
        status=RegistrationOrderStatus.REFUNDED,
        transfer_status="NONE",
        open_provider_domain_id="30058237",
        razorpay_payment_id="pay_TNC75Aob3CphkX",
        razorpay_refund_id=None,
        provision_message="Domain deleted/released at OpenProvider after registration; provider charge refunded.",
    )
    f, o, code, msg = TrackRecordService._status_for_registration_order(order)
    assert f == FulfillmentStatus.PROVISIONED
    assert o == OverallStatus.REFUNDED
    assert code is None
    assert msg is None


def test_sync_status_refunded_registration():
    """_status_for_sync_order also maps a REFUNDED registration to
    PROVISIONED / Refunded (covers sync/razorpay recovery paths)."""
    f, o, src, code, msg = _sync_status(
        _order_row(
            status="REFUNDED",
            transfer_status="NONE",
            open_provider_domain_id="30058237",
            open_provider_status="ACT",
            razorpay_payment_id="pay_TNC75Aob3CphkX",
        ),
        is_transfer=False,
        op_domain_id="30058237",
    )
    assert f == FulfillmentStatus.PROVISIONED
    assert o == OverallStatus.REFUNDED
    assert src is None and code is None and msg is None


@pytest.mark.asyncio
async def test_record_from_registration_order_refunded_not_clobbered():
    """Re-running record_from_registration_order for a REFUNDED order (e.g. a
    Razorpay webhook replay) writes REFUNDED / PROVISIONED / Refunded and never
    reverts an existing record back to CAPTURED / Pending."""
    order = _order(
        status=RegistrationOrderStatus.REFUNDED,
        transfer_status="NONE",
        open_provider_domain_id="30058237",
        open_provider_status="ACT",
        razorpay_order_id="order_TNC6p9oIzWD4pf",
        razorpay_payment_id="pay_TNC75Aob3CphkX",
        razorpay_refund_id=None,
        period_years=1,
        price_inr=849.0,
    )
    session = AsyncMock()
    service = TrackRecordService(session)
    service._repo = AsyncMock()
    first = None

    async def _find(int_id):
        return first  # None on the first call, the created record afterwards

    service._repo.find_by_internal_order_id = _find
    service._repo.save = AsyncMock(side_effect=lambda rec: rec)

    rec = await service.record_from_registration_order(order)
    first = rec

    assert rec.payment_status == PaymentStatus.REFUNDED
    assert rec.fulfillment_status == FulfillmentStatus.PROVISIONED
    assert rec.overall_status == OverallStatus.REFUNDED
    assert rec.error_code is None and rec.error_message is None

    # Simulated webhook replay — the record already exists.
    replayed = await service.record_from_registration_order(order)
    assert replayed is rec
    assert replayed.payment_status == PaymentStatus.REFUNDED
    assert replayed.fulfillment_status == FulfillmentStatus.PROVISIONED
    assert replayed.overall_status == OverallStatus.REFUNDED
    assert replayed.error_code is None


@pytest.mark.asyncio
async def test_record_paid_attempt_preserves_refunded_overall():
    """Even a caller that passes payment_status=CAPTURED with PROVISIONED
    (e.g. sync_razorpay_missing_payments) cannot flip an explicitly-passed
    Refunded overall back to SUCCESS / Pending."""
    session = AsyncMock()
    service = TrackRecordService(session)
    service._repo = AsyncMock()
    service._repo.find_by_internal_order_id = AsyncMock(return_value=None)
    service._repo.save = AsyncMock(side_effect=lambda rec: rec)

    rec = await service.record_paid_attempt(
        internal_order_id="TRK-REG-71312723-6283-4079-b32a-f45110571278",
        category=TrackRecordCategory.DOMAIN_REGISTRATION_OPENPROVIDER,
        provider_subcategory="OpenProvider",
        item_name="vaishnavi.cyou",
        amount_charged=849.0,
        currency="INR",
        payment_status=PaymentStatus.CAPTURED,
        razorpay_order_id="order_TNC6p9oIzWD4pf",
        razorpay_payment_id="pay_TNC75Aob3CphkX",
        fulfillment_status=FulfillmentStatus.PROVISIONED,
        overall_status=OverallStatus.REFUNDED,
        openprovider_domain_id="30058237",
    )
    assert rec.payment_status == PaymentStatus.CAPTURED  # caller's own value kept
    assert rec.overall_status == OverallStatus.REFUNDED  # reconciled state preserved


# ── tax invoice display-only suppression (REFUNDED orders) ───────────────────


def _invoice_track_record(oid) -> TrackRecord:
    return TrackRecord(
        internal_order_id=f"TRK-REG-{oid}",
        category=TrackRecordCategory.DOMAIN_REGISTRATION_OPENPROVIDER,
        provider_subcategory="OpenProvider",
        item_name="vaishnavi.cyou",
        amount_charged=849.0,
        currency="INR",
        payment_status=PaymentStatus.CAPTURED,
        fulfillment_status=FulfillmentStatus.PROVISIONED,
        overall_status=OverallStatus.SUCCESS,
        openprovider_domain_id="30058237",
    )


@pytest.mark.asyncio
async def test_enrich_shows_invoice_for_active_order():
    """ACTIVE orders keep exposing their tax invoice number in the admin API."""
    from app.integrations.razorpay import client as rzp_client

    oid = uuid4()
    result_mock = MagicMock()
    result_mock.all = MagicMock(return_value=[(oid, "AI2600008", "ACTIVE", 0, None, None, "pay_ACT1")])
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)
    service = TrackRecordService(session)

    with patch.object(rzp_client, "resolve_payment_environment", return_value="LIVE"):
        payload = (await service.enrich_records_with_tax_invoices(
            [_invoice_track_record(oid)]
        ))[0]
    assert payload["taxInvoiceNumber"] == "AI2600008"
    assert payload["invoiceNumber"] == "AI2600008"
    assert payload["registrationOrderId"] == str(oid)
    assert payload["paymentMode"] == "LIVE"


@pytest.mark.asyncio
async def test_enrich_hides_invoice_for_refunded_order():
    """REFUNDED orders keep AI2600008 in the DB but the admin API payload must
    not expose it (display-only suppression)."""
    from app.integrations.razorpay import client as rzp_client

    oid = uuid4()
    result_mock = MagicMock()
    result_mock.all = MagicMock(return_value=[(oid, "AI2600008", "REFUNDED", 0, None, None, "pay_TEST1")])
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)
    service = TrackRecordService(session)

    with patch.object(rzp_client, "resolve_payment_environment", return_value="TEST"):
        payload = (await service.enrich_records_with_tax_invoices(
            [_invoice_track_record(oid)]
        ))[0]
    assert payload["taxInvoiceNumber"] is None
    assert payload["invoiceNumber"] is None
    # The order link is still exposed (audit) — only the invoice is hidden.
    assert payload["registrationOrderId"] == str(oid)
    assert payload["paymentMode"] == "TEST"


@pytest.mark.asyncio
async def test_enrich_never_mutates_invoice_in_db():
    """Enrichment is read-only: the invoice number stays on the order row and no
    UPDATE/INSERT/DELETE is ever issued."""
    from app.integrations.razorpay import client as rzp_client

    oid = uuid4()
    order = _order(status=RegistrationOrderStatus.REFUNDED)
    order.id = oid
    order.tax_invoice_number = "AI2600008"

    result_mock = MagicMock()
    result_mock.all = MagicMock(return_value=[(oid, "AI2600008", "REFUNDED", 0, None, None, "pay_TEST1")])
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)
    service = TrackRecordService(session)

    with patch.object(rzp_client, "resolve_payment_environment", return_value="TEST"):
        await service.enrich_records_with_tax_invoices([_invoice_track_record(oid)])

    # The in-memory order row keeps its number untouched.
    assert order.tax_invoice_number == "AI2600008"
    # Only reads were issued — no write statements, no commit.
    sql_texts = [
        str(call.args[0]) for call in session.execute.call_args_list if call.args
    ]
    assert sql_texts, "enrichment should have executed the order lookup"
    assert all(
        "UPDATE" not in s.upper()
        and "DELETE" not in s.upper()
        and "INSERT" not in s.upper()
        for s in sql_texts
    )
    session.commit.assert_not_awaited()


# ── Payment Mode (Razorpay environment) + Renewal state columns ──────────────


def test_razorpay_environment_from_key_config():
    """Payment Mode comes from the actual Razorpay key configuration
    (rzp_test_* => TEST, rzp_live_* => LIVE) — never guessed from order or
    payment ids. Unconfigured/unknown keys yield None (frontend shows '—')."""
    from app.integrations.razorpay import client as rzp_client

    with patch.object(rzp_client, "_key_id", return_value="rzp_test_abc123"):
        assert rzp_client.get_environment() == "TEST"
    with patch.object(rzp_client, "_key_id", return_value="rzp_live_xyz789"):
        assert rzp_client.get_environment() == "LIVE"
    with patch.object(rzp_client, "_key_id", return_value=""):
        assert rzp_client.get_environment() is None
    with patch.object(rzp_client, "_key_id", return_value="rzp_unknown_1"):
        assert rzp_client.get_environment() is None


def test_resolve_payment_environment_per_transaction():
    """Per-transaction env via the actual Razorpay account: a payment found in
    the configured account => that env; an id unknown to it => the other env;
    transient errors / unconfigured => None (frontend shows '—')."""
    from app.integrations.razorpay import client as rzp_client
    from razorpay.errors import BadRequestError
    from requests.exceptions import ConnectionError

    rzp_client._PAYMENT_ENV_CACHE.clear()
    try:
        with patch.object(rzp_client, "_key_id", return_value="rzp_live_abc"):
            with patch.object(rzp_client, "fetch_payment", return_value={"id": "pay_X"}):
                assert rzp_client.resolve_payment_environment("pay_X") == "LIVE"
        with patch.object(rzp_client, "_key_id", return_value="rzp_live_abc"):
            with patch.object(
                rzp_client, "fetch_payment",
                side_effect=BadRequestError("The id provided does not exist"),
            ):
                assert rzp_client.resolve_payment_environment("pay_Y") == "TEST"
        with patch.object(rzp_client, "_key_id", return_value="rzp_test_abc"):
            with patch.object(
                rzp_client, "fetch_payment",
                side_effect=BadRequestError("The id provided does not exist"),
            ):
                assert rzp_client.resolve_payment_environment("pay_Z") == "LIVE"
        with patch.object(rzp_client, "_key_id", return_value="rzp_live_abc"):
            with patch.object(rzp_client, "fetch_payment", side_effect=ConnectionError("down")):
                assert rzp_client.resolve_payment_environment("pay_W") is None
        with patch.object(rzp_client, "_key_id", return_value=""):
            assert rzp_client.resolve_payment_environment("pay_Q") is None
        assert rzp_client.resolve_payment_environment("") is None
    finally:
        rzp_client._PAYMENT_ENV_CACHE.clear()


def test_renewal_state_mapping():
    """Renewal state is derived from the order's renewal fields — never
    inferred from registration success."""
    mapper = TrackRecordService._renewal_state_for_order
    # Reversed / failed orders have no renewal applicable.
    assert mapper({"status": "REFUNDED"}) == "N/A"
    assert mapper({"status": "PROVISION_FAILED"}) == "N/A"
    assert mapper({"status": "CANCELLED"}) == "N/A"
    assert mapper({"status": "PAYMENT_FAILED"}) == "N/A"
    # ACTIVE order with no renewal activity yet.
    assert mapper({"status": "ACTIVE"}) == "N/A"
    # Completed renewal.
    assert mapper(
        {"status": "ACTIVE", "renewal_count": 1, "last_renewal_payment_id": "pay_REN1"}
    ) == "OK"
    # Renewal payment in flight.
    assert mapper(
        {"status": "ACTIVE", "pending_renewal_razorpay_order_id": "order_REN1"}
    ) == "PENDING"
    # Payment verified but renewal never completed (provision failed/stuck).
    assert mapper(
        {"status": "ACTIVE", "renewal_count": 0, "last_renewal_payment_id": "pay_REN1"}
    ) == "FAILED"


@pytest.mark.asyncio
async def test_enrich_payment_mode_and_renewal_state():
    """The admin API payload carries paymentMode (per-transaction Razorpay env)
    and renewalState (from order renewal data)."""
    from app.integrations.razorpay import client as rzp_client

    oid = uuid4()
    result_mock = MagicMock()
    result_mock.all = MagicMock(
        return_value=[(oid, None, "ACTIVE", 1, None, "pay_REN1", "pay_LIVE1")]
    )
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)
    service = TrackRecordService(session)

    with patch.object(rzp_client, "resolve_payment_environment", return_value="LIVE"):
        payload = (await service.enrich_records_with_tax_invoices(
            [_invoice_track_record(oid)]
        ))[0]
    assert payload["paymentMode"] == "LIVE"
    assert payload["renewalState"] == "OK"

    result_mock.all = MagicMock(
        return_value=[(oid, None, "REFUNDED", 0, None, None, "pay_TEST1")]
    )
    with patch.object(rzp_client, "resolve_payment_environment", return_value="TEST"):
        payload = (await service.enrich_records_with_tax_invoices(
            [_invoice_track_record(oid)]
        ))[0]
    assert payload["paymentMode"] == "TEST"
    assert payload["renewalState"] == "N/A"
