"""Domain transfer payment/retry safety regression tests.

Covers the retry-after-failure contract:
- A captured Razorpay payment must never disappear when OpenProvider rejects
  or is unreachable.
- A provider rejection records PROVISION_FAILED / transfer_status=FAILED and
  raises an honest customer-facing error (no Razorpay success).
- Provider-unreachable leaves a recoverable PENDING state that the transfer
  reconcile worker retries.
- create_transfer_payment_order allows a fresh attempt only after refund /
  when the previous attempt was never paid; never reuses a stale EPP code on
  an unpaid reuse; never duplicates a payment while one is in flight.
- Track records never map a failed transfer to PROVISIONED.
"""

import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.service.domain.domain_registration_service import DomainRegistrationService
from app.utils.registration_enums import RegistrationOrderStatus


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = MagicMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def service(mock_session):
    srv = DomainRegistrationService(mock_session)
    srv._orders = AsyncMock()
    srv._followup = AsyncMock()
    return srv


def _order(status=RegistrationOrderStatus.CREATED, *, transfer_status="PAYMENT_PENDING", payment_id=None, op_id=None):
    return DomainRegistrationOrder(
        id=uuid.uuid4(),
        domain_name="retrytest",
        domain_extension=".com",
        buyer_id=uuid.uuid4(),
        buyer_full_name="Test User",
        buyer_email="test@example.com",
        buyer_phone="9999999999",
        period_years=1,
        price_inr=799.0,
        subtotal_inr=676.27,
        gst_inr=122.73,
        quoted_unit_price_inr=799.0,
        price_source="fallback",
        status=status,
        transfer_status=transfer_status,
        transfer_auth_code="WRONG123",
        razorpay_order_id="order_test",
        razorpay_payment_id=payment_id,
        open_provider_domain_id=op_id,
    )


@pytest.fixture
def buyer():
    b = MagicMock()
    b.id = uuid.uuid4()
    b.email = "buyer@example.com"
    b.full_name = "Buyer Name"
    b.firstname = "Buyer"
    b.lastname = "Name"
    b.phone_number = "9876543210"
    return b


def _patch_provision_deps(*, transfer_side_effect=None, transfer_return=None, lookup=None):
    """Patch active_registrar + transfer_domain for _provision_transfer."""
    reg = MagicMock()
    reg.is_configured.return_value = True
    reg.lookup_order_id_by_domain = AsyncMock(return_value=lookup)
    reg.create_customer = AsyncMock(return_value="handle-123")
    transfer = AsyncMock(
        side_effect=transfer_side_effect,
        return_value=transfer_return,
    )
    patchers = [
        patch(
            "app.service.domain.domain_registration_service.active_registrar",
            return_value=reg,
        ),
        patch(
            "app.integrations.openprovider.client.transfer_domain",
            transfer,
        ),
        patch(
            "app.service.domain.domain_registration_service._default_nameservers_for_order",
            return_value=[],
        ),
    ]
    for p in patchers:
        p.start()
    return reg, transfer, patchers


# ── verify_transfer_payment ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_correct_epp_submits_transfer_and_keeps_payment(service, buyer):
    order = _order(status=RegistrationOrderStatus.CREATED)
    order.buyer_id = buyer.id
    service._orders.get_by_razorpay_order_id = AsyncMock(return_value=order)
    service._orders.get_by_id_for_update = AsyncMock(return_value=order)

    with patch(
        "app.service.domain.domain_registration_service.rzp.verify_payment_signature",
        return_value=True,
    ):
        reg, transfer, patchers = _patch_provision_deps(
            transfer_return={"id": "OP12345"},
        )
        try:
            res = await service.verify_transfer_payment(
                {
                    "razorpayOrderId": "order_test",
                    "razorpayPaymentId": "pay_ok",
                    "razorpaySignature": "sig",
                },
                buyer=buyer,
            )
        finally:
            for p in patchers:
                p.stop()

    assert res["transferStatus"] == "PENDING"
    assert order.razorpay_payment_id == "pay_ok"
    assert order.open_provider_domain_id == "OP12345"
    transfer.assert_awaited_once()
    service._session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_wrong_epp_marks_failed_refunds_and_preserves_payment(service, buyer):
    order = _order(status=RegistrationOrderStatus.CREATED)
    order.buyer_id = buyer.id
    service._orders.get_by_razorpay_order_id = AsyncMock(return_value=order)
    service._orders.get_by_id_for_update = AsyncMock(return_value=order)

    async def _refund_side_effect(order_id):
        order.razorpay_refund_id = "refund_123"
        order.status = RegistrationOrderStatus.REFUNDED
        return {"success": True, "refundId": "refund_123"}

    with patch(
        "app.service.domain.domain_registration_service.rzp.verify_payment_signature",
        return_value=True,
    ), patch(
        "app.service.domain.domain_registration_ops_service.DomainRegistrationOpsService.admin_refund",
        new=AsyncMock(side_effect=_refund_side_effect),
    ) as mock_refund:
        reg, transfer, patchers = _patch_provision_deps(
            transfer_side_effect=RuntimeError(
                "Invalid auth code, please verify the EPP code"
            ),
        )
        try:
            with pytest.raises(Exception) as exc_info:
                await service.verify_transfer_payment(
                    {
                        "razorpayOrderId": "order_test",
                        "razorpayPaymentId": "pay_bad",
                        "razorpaySignature": "sig",
                    },
                    buyer=buyer,
                )
        finally:
            for p in patchers:
                p.stop()

    assert exc_info.value.status_code == 502
    # Payment recorded and preserved — never rolled back.
    assert order.razorpay_payment_id == "pay_bad"
    # Honest terminal failure state + refund through the existing machinery,
    # exactly once.
    assert order.transfer_status == "FAILED"
    assert order.razorpay_refund_id == "refund_123"
    assert order.status == RegistrationOrderStatus.REFUNDED
    assert "EPP" in (order.provision_message or "")
    mock_refund.assert_awaited_once_with(order.id)
    # Single provider attempt only.
    transfer.assert_awaited_once()


@pytest.mark.asyncio
async def test_provider_unreachable_leaves_recoverable_pending_no_refund(service, buyer):
    order = _order(status=RegistrationOrderStatus.CREATED)
    order.buyer_id = buyer.id
    service._orders.get_by_razorpay_order_id = AsyncMock(return_value=order)
    service._orders.get_by_id_for_update = AsyncMock(return_value=order)

    with patch(
        "app.service.domain.domain_registration_service.rzp.verify_payment_signature",
        return_value=True,
    ), patch(
        "app.service.domain.domain_registration_ops_service.DomainRegistrationOpsService.admin_refund",
        new=AsyncMock(),
    ) as mock_refund:
        reg, transfer, patchers = _patch_provision_deps(
            transfer_side_effect=RuntimeError(
                "Connection timed out while contacting registrar"
            ),
        )
        try:
            res = await service.verify_transfer_payment(
                {
                    "razorpayOrderId": "order_test",
                    "razorpayPaymentId": "pay_timeout",
                    "razorpaySignature": "sig",
                },
                buyer=buyer,
            )
        finally:
            for p in patchers:
                p.stop()

    assert res["paymentReceived"] is True
    assert res["transferStatus"] == "PENDING"
    assert order.status == RegistrationOrderStatus.PAYMENT_COMPLETED
    assert order.transfer_status == "PENDING"
    assert order.razorpay_payment_id == "pay_timeout"
    # Temporary/unknown failures must NOT be refunded or resubmitted.
    mock_refund.assert_not_awaited()


@pytest.mark.asyncio
async def test_replay_same_payment_never_resubmits(service, buyer):
    order = _order(
        status=RegistrationOrderStatus.PROVISION_FAILED,
        transfer_status="FAILED",
        payment_id="pay_bad",
    )
    order.buyer_id = buyer.id
    order.provision_message = (
        "Domain transfer failed for retrytest.com: rejected. Your payment will be refunded."
    )
    service._orders.get_by_razorpay_order_id = AsyncMock(return_value=order)
    service._orders.get_by_id_for_update = AsyncMock(return_value=order)

    with patch(
        "app.service.domain.domain_registration_service.rzp.verify_payment_signature",
        return_value=True,
    ), patch(
        "app.service.domain.domain_registration_ops_service.DomainRegistrationOpsService.admin_refund",
        new=AsyncMock(),
    ) as mock_refund:
        with patch(
            "app.integrations.openprovider.client.transfer_domain",
            AsyncMock(),
        ) as transfer:
            with pytest.raises(Exception) as exc_info:
                await service.verify_transfer_payment(
                    {
                        "razorpayOrderId": "order_test",
                        "razorpayPaymentId": "pay_bad",
                        "razorpaySignature": "sig",
                    },
                    buyer=buyer,
                )

    assert exc_info.value.status_code == 502
    transfer.assert_not_awaited()
    mock_refund.assert_not_awaited()


# ── create_transfer_payment_order ──────────────────────────────────────────────


async def _call_create_order(service, buyer, existing, auth_code="CORRECT456"):
    service._orders.get_active_transfer_by_buyer_and_domain = AsyncMock(
        return_value=existing
    )
    with patch(
        "app.service.domain.domain_registration_service.rzp.is_configured",
        return_value=True,
    ), patch(
        "app.service.domain.domain_registration_service.rzp.create_order",
        return_value={"id": "order_new"},
    ):
        return await service.create_transfer_payment_order(
            {"domain": "retrytest.com", "authCode": auth_code},
            buyer=buyer,
        )


@pytest.mark.asyncio
async def test_empty_epp_rejected_before_razorpay(service, buyer):
    service._orders.get_active_transfer_by_buyer_and_domain = AsyncMock()
    service._orders.create = AsyncMock()
    with patch(
        "app.service.domain.domain_registration_service.rzp.is_configured",
        return_value=True,
    ), patch(
        "app.service.domain.domain_registration_service.rzp.create_order",
        new=AsyncMock(),
    ) as mock_rzp_order:
        with pytest.raises(Exception) as exc_info:
            await service.create_transfer_payment_order(
                {"domain": "retrytest.com", "authCode": "  "},
                buyer=buyer,
            )

    assert exc_info.value.status_code == 400
    mock_rzp_order.assert_not_called()
    service._orders.create.assert_not_called()
    service._orders.get_active_transfer_by_buyer_and_domain.assert_not_called()


@pytest.mark.asyncio
async def test_empty_domain_rejected_before_razorpay(service, buyer):
    service._orders.get_active_transfer_by_buyer_and_domain = AsyncMock()
    service._orders.create = AsyncMock()
    with patch(
        "app.service.domain.domain_registration_service.rzp.is_configured",
        return_value=True,
    ), patch(
        "app.service.domain.domain_registration_service.rzp.create_order",
        new=AsyncMock(),
    ) as mock_rzp_order:
        with pytest.raises(Exception) as exc_info:
            await service.create_transfer_payment_order(
                {"domain": "", "authCode": "ABC123"},
                buyer=buyer,
            )

    assert exc_info.value.status_code == 400
    mock_rzp_order.assert_not_called()
    service._orders.create.assert_not_called()


@pytest.mark.asyncio
async def test_payment_signature_failure_never_submits_transfer(service, buyer):
    order = _order(status=RegistrationOrderStatus.CREATED)
    order.buyer_id = buyer.id
    service._orders.get_by_razorpay_order_id = AsyncMock(return_value=order)
    service._orders.get_by_id_for_update = AsyncMock(return_value=order)

    with patch(
        "app.service.domain.domain_registration_service.rzp.verify_payment_signature",
        return_value=False,
    ), patch(
        "app.integrations.openprovider.client.transfer_domain",
        AsyncMock(),
    ) as transfer, patch(
        "app.service.domain.domain_registration_ops_service.DomainRegistrationOpsService.admin_refund",
        new=AsyncMock(),
    ) as mock_refund:
        with pytest.raises(Exception) as exc_info:
            await service.verify_transfer_payment(
                {
                    "razorpayOrderId": "order_test",
                    "razorpayPaymentId": "pay_bad",
                    "razorpaySignature": "bad_sig",
                },
                buyer=buyer,
            )

    assert exc_info.value.status_code == 400
    assert order.status == RegistrationOrderStatus.FAILED
    assert order.razorpay_payment_id is None
    transfer.assert_not_awaited()
    mock_refund.assert_not_awaited()


def test_failure_email_never_says_pending_activation():
    from app.service.auth.email_templates import (
        domain_registration_failed_email_template,
    )

    html = domain_registration_failed_email_template(
        fqdn="example.com",
        message=(
            "Domain transfer failed for example.com: the registrar rejected "
            "the authorization (EPP) code."
        ),
        order_detail_url="http://test/orders/1",
        is_transfer=True,
    )
    assert "pending activation" not in html.lower()
    assert "refund" in html.lower()
    assert "Transfer issue" in html


@pytest.mark.asyncio
async def test_paid_failed_attempt_blocks_duplicate_payment(service, buyer):
    existing = _order(
        status=RegistrationOrderStatus.PROVISION_FAILED,
        transfer_status="FAILED",
        payment_id="pay_bad",
    )
    with pytest.raises(Exception) as exc_info:
        await _call_create_order(service, buyer, existing, auth_code="CORRECT456")
    assert exc_info.value.status_code == 409
    assert "refund" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_refunded_attempt_allows_fresh_order(service, buyer):
    service._orders.create = AsyncMock(
        side_effect=lambda order: order
    )
    # get_active_transfer_by_buyer_and_domain excludes REFUNDED, so a refunded
    # previous attempt yields None → a brand-new order is created with the
    # corrected code.
    res = await _call_create_order(service, buyer, existing=None, auth_code="CORRECT456")
    assert res["orderId"] == "order_new"


@pytest.mark.asyncio
async def test_unpaid_checkout_reuse_updates_code_and_mints_fresh_order(service, buyer):
    existing = _order(status=RegistrationOrderStatus.CREATED, transfer_status="PAYMENT_PENDING")
    res = await _call_create_order(service, buyer, existing, auth_code="NEWCODE789")
    # A stale Razorpay order id from an abandoned checkout is never reused — a
    # completely new order is minted for the SAME unpaid attempt.
    assert res["orderId"] == "order_new"
    assert existing.razorpay_order_id == "order_new"
    # The LATEST code is stored on the reused order — never the stale one.
    assert existing.transfer_auth_code == "NEWCODE789"


@pytest.mark.asyncio
async def test_active_domain_never_allows_new_attempt(service, buyer):
    existing = _order(
        status=RegistrationOrderStatus.ACTIVE,
        transfer_status="PENDING",
        payment_id="pay_ok",
        op_id="OP123",
    )
    with pytest.raises(Exception) as exc_info:
        await _call_create_order(service, buyer, existing)
    assert exc_info.value.status_code == 409
    assert "already been transferred" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_inflight_paid_transfer_blocks_duplicate_payment(service, buyer):
    existing = _order(
        status=RegistrationOrderStatus.REGISTRATION_PENDING,
        transfer_status="PENDING",
        payment_id="pay_ok",
        op_id="OP123",
    )
    with pytest.raises(Exception) as exc_info:
        await _call_create_order(service, buyer, existing)
    assert exc_info.value.status_code == 409
    assert "being processed" in exc_info.value.message.lower()


# ── track record mapping ───────────────────────────────────────────────────────


def _sync_order_row(**overrides):
    row = {
        "status": "PROVISION_FAILED",
        "transfer_status": "FAILED",
        "open_provider_status": "",
        "provision_message": "Domain transfer failed for example.com: rejected.",
    }
    row.update(overrides)
    return row


def test_track_sync_failed_transfer_never_provisioned():
    from app.service.platform.track_record_service import (
        TrackRecordService,
        FulfillmentStatus,
        OverallStatus,
    )

    f, o, err_src, err_code, err_msg = TrackRecordService._status_for_sync_order(
        _sync_order_row(),
        is_transfer=True,
        target_provider="OpenProvider",
        op_domain_id=None,
        demo_op=False,
    )
    assert f == FulfillmentStatus.FAILED
    assert o == OverallStatus.FAILED
    assert err_code == "TRANSFER_FAILED"


def test_track_sync_refunded_failed_transfer_is_failed_refunded():
    from app.service.platform.track_record_service import (
        TrackRecordService,
        FulfillmentStatus,
        OverallStatus,
    )

    f, o, err_src, err_code, err_msg = TrackRecordService._status_for_sync_order(
        _sync_order_row(status="REFUNDED"),
        is_transfer=True,
        target_provider="OpenProvider",
        op_domain_id=None,
        demo_op=False,
    )
    assert f == FulfillmentStatus.FAILED
    assert o == OverallStatus.REFUNDED


def test_track_sync_successful_transfer_still_provisioned():
    from app.service.platform.track_record_service import (
        TrackRecordService,
        FulfillmentStatus,
        OverallStatus,
    )

    f, o, err_src, err_code, err_msg = TrackRecordService._status_for_sync_order(
        _sync_order_row(status="ACTIVE", transfer_status="PENDING", open_provider_status="ACT"),
        is_transfer=True,
        target_provider="OpenProvider",
        op_domain_id="OP123",
        demo_op=False,
    )
    assert f == FulfillmentStatus.PROVISIONED
    assert o == OverallStatus.SUCCESS


def test_track_live_failed_transfer_never_provisioned():
    from app.service.platform.track_record_service import (
        TrackRecordService,
        FulfillmentStatus,
        OverallStatus,
    )

    order = _order(
        status=RegistrationOrderStatus.PROVISION_FAILED,
        transfer_status="FAILED",
        payment_id="pay_bad",
    )
    f, o, err_code, err_msg = TrackRecordService._status_for_registration_order(order)
    assert f == FulfillmentStatus.FAILED
    assert o == OverallStatus.FAILED
    assert err_code == "TRANSFER_FAILED"


# ── transfer reconcile worker ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transfer_reconcile_retries_unreachable_submission(service, buyer):
    order = _order(
        status=RegistrationOrderStatus.PAYMENT_COMPLETED,
        transfer_status="PENDING",
        payment_id="pay_timeout",
    )
    order.buyer_id = buyer.id
    service._orders.list_transfer_reconcile_candidates = AsyncMock(return_value=[order])
    service._orders.get_by_id_for_update = AsyncMock(return_value=order)
    service._session.get = AsyncMock(return_value=buyer)

    from app.service.domain.domain_registration_followup import (
        DomainRegistrationFollowup,
    )

    followup = DomainRegistrationFollowup(service._session)
    followup._orders = service._orders
    with patch.object(
        DomainRegistrationService,
        "_provision_transfer",
        new_callable=AsyncMock,
    ) as mock_provision:
        count = await followup.run_transfer_pending_reconcile()

    assert count == 1
    mock_provision.assert_awaited_once_with(order, buyer=buyer)
