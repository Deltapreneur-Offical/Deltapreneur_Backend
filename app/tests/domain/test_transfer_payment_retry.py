"""Domain transfer payment-retry regression tests.

Covers the cancelled/unpaid checkout contract:
- An order whose Razorpay payment was cancelled/abandoned stays unpaid
  (status CREATED/EXPIRED/PAYMENT_FAILED, no razorpay_payment_id) and must be
  retryable — never shown or treated as an active/pending transfer.
- retry_transfer_payment reuses the existing unpaid Razorpay order when valid,
  otherwise mints a fresh one on the SAME row; it never creates a duplicate DB
  order and never calls OpenProvider.
- A captured payment, in-flight transfer, successful transfer, failed attempt,
  or refunded attempt is never retryable as a payment.
"""

import uuid
from datetime import datetime, timezone

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.service.domain.domain_registration_service import (
    DomainRegistrationService,
    _RETRY_MINT_GUARD,
)
from app.utils.registration_enums import RegistrationOrderStatus


@pytest.fixture(autouse=True)
def _clear_mint_guard():
    _RETRY_MINT_GUARD.clear()
    yield
    _RETRY_MINT_GUARD.clear()


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


def _order(status=RegistrationOrderStatus.CREATED, *, transfer_status="PAYMENT_PENDING", payment_id=None, order_id="order_test"):
    return DomainRegistrationOrder(
        id=uuid.uuid4(),
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
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
        razorpay_order_id=order_id,
        razorpay_payment_id=payment_id,
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


async def _call_retry(service, buyer, order):
    service._orders.get_by_id_for_update = AsyncMock(return_value=order)
    with patch(
        "app.service.domain.domain_registration_service.rzp.is_configured",
        return_value=True,
    ), patch(
        "app.service.domain.domain_registration_service.rzp.create_order",
        return_value={"id": "order_fresh"},
    ) as mock_rzp:
        res = await service.retry_transfer_payment(order.id, buyer=buyer)
    return res, mock_rzp


# ── retry_transfer_payment ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retry_never_reuses_stale_razorpay_order(service, buyer):
    # The stored order id is from the abandoned original checkout — Razorpay
    # refuses to open it, so retry must ALWAYS mint a completely new order.
    order = _order(status=RegistrationOrderStatus.CREATED, transfer_status="PAYMENT_PENDING")
    order.buyer_id = buyer.id
    res, mock_rzp = await _call_retry(service, buyer, order)
    assert res["orderId"] == "order_fresh"
    assert res["registrationOrderId"] == str(order.id)
    mock_rzp.assert_called_once()
    # Old order id is replaced on the SAME row — never returned to the client.
    assert order.razorpay_order_id == "order_fresh"
    assert order.razorpay_payment_id is None


@pytest.mark.asyncio
async def test_duplicate_retry_click_does_not_mint_twice(service, buyer):
    order = _order(status=RegistrationOrderStatus.CREATED, transfer_status="PAYMENT_PENDING")
    order.buyer_id = buyer.id
    first, mock_rzp = await _call_retry(service, buyer, order)
    assert first["orderId"] == "order_fresh"
    # Second click in the same burst: same just-minted order, no new mint.
    second, mock_rzp2 = await _call_retry(service, buyer, order)
    assert second["orderId"] == "order_fresh"
    assert mock_rzp2.call_count == 0  # the second call did not mint again


@pytest.mark.asyncio
async def test_second_retry_after_cancel_mints_new_order(service, buyer):
    order = _order(status=RegistrationOrderStatus.CREATED, transfer_status="PAYMENT_PENDING")
    order.buyer_id = buyer.id
    first, _ = await _call_retry(service, buyer, order)
    assert first["orderId"] == "order_fresh"
    # Simulate the user cancelling the checkout and returning later: the mint
    # guard expires and the next retry mints ANOTHER new order.
    _RETRY_MINT_GUARD.clear()
    order.razorpay_order_id = None
    second, mock_rzp2 = await _call_retry(service, buyer, order)
    assert second["orderId"] == "order_fresh"
    mock_rzp2.assert_called_once()


@pytest.mark.asyncio
async def test_retry_expired_unpaid_mints_fresh_order_on_same_row(service, buyer):
    order = _order(status=RegistrationOrderStatus.EXPIRED, transfer_status="PAYMENT_PENDING")
    order.buyer_id = buyer.id
    res, mock_rzp = await _call_retry(service, buyer, order)
    mock_rzp.assert_called_once()
    assert res["orderId"] == "order_fresh"
    # Same DB row is reset to an unpaid attempt — no duplicate order created.
    assert order.status == RegistrationOrderStatus.CREATED
    assert order.transfer_status == "PAYMENT_PENDING"
    assert order.razorpay_order_id == "order_fresh"
    assert order.razorpay_payment_id is None


@pytest.mark.asyncio
async def test_retry_paid_order_never_retries(service, buyer):
    order = _order(
        status=RegistrationOrderStatus.PAYMENT_COMPLETED,
        transfer_status="PENDING",
        payment_id="pay_captured",
    )
    order.buyer_id = buyer.id
    with pytest.raises(Exception) as exc_info:
        await _call_retry(service, buyer, order)
    assert exc_info.value.status_code == 409
    assert "being processed" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_retry_in_flight_transfer_never_retries(service, buyer):
    order = _order(
        status=RegistrationOrderStatus.REGISTRATION_PENDING,
        transfer_status="PENDING",
        payment_id="pay_captured",
    )
    order.buyer_id = buyer.id
    with pytest.raises(Exception) as exc_info:
        await _call_retry(service, buyer, order)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_retry_active_transfer_never_retries(service, buyer):
    order = _order(
        status=RegistrationOrderStatus.ACTIVE,
        transfer_status="COMPLETED",
        payment_id="pay_captured",
    )
    order.buyer_id = buyer.id
    with pytest.raises(Exception) as exc_info:
        await _call_retry(service, buyer, order)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_retry_failed_or_refunded_never_retries(service, buyer):
    for status, ts in [
        (RegistrationOrderStatus.PROVISION_FAILED, "FAILED"),
        (RegistrationOrderStatus.FAILED, "FAILED"),
        (RegistrationOrderStatus.REFUNDED, "FAILED"),
    ]:
        order = _order(status=status, transfer_status=ts, payment_id="pay_captured")
        order.buyer_id = buyer.id
        with pytest.raises(Exception) as exc_info:
            await _call_retry(service, buyer, order)
        assert exc_info.value.status_code == 409
        assert "start" in exc_info.value.message.lower() or "new" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_retry_without_saved_auth_code_rejected(service, buyer):
    order = _order(status=RegistrationOrderStatus.CREATED, transfer_status="PAYMENT_PENDING")
    order.transfer_auth_code = None
    order.buyer_id = buyer.id
    with pytest.raises(Exception) as exc_info:
        await _call_retry(service, buyer, order)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_retry_non_transfer_order_rejected(service, buyer):
    order = _order(status=RegistrationOrderStatus.CREATED)
    order.transfer_status = "NONE"
    order.buyer_id = buyer.id
    with pytest.raises(Exception) as exc_info:
        await _call_retry(service, buyer, order)
    assert exc_info.value.status_code == 400


# ── create_transfer_payment_order: unpaid reuse must not duplicate rows ───────


@pytest.mark.asyncio
async def test_create_order_reuses_created_row_without_razorpay_order(service, buyer):
    existing = _order(status=RegistrationOrderStatus.CREATED, transfer_status="PAYMENT_PENDING", order_id=None)
    service._orders.get_active_transfer_by_buyer_and_domain = AsyncMock(return_value=existing)
    service._orders.create = AsyncMock(side_effect=lambda o: o)
    with patch(
        "app.service.domain.domain_registration_service.rzp.is_configured",
        return_value=True,
    ), patch(
        "app.service.domain.domain_registration_service.rzp.create_order",
        return_value={"id": "order_fresh"},
    ) as mock_rzp:
        res = await service.create_transfer_payment_order(
            {"domain": "retrytest.com", "authCode": "NEWCODE789"},
            buyer=buyer,
        )

    assert res["orderId"] == "order_fresh"
    assert res["registrationOrderId"] == str(existing.id)
    # The existing unpaid row was reused — no new database order row.
    service._orders.create.assert_not_called()
    mock_rzp.assert_called_once()
    assert existing.transfer_auth_code == "NEWCODE789"
    assert existing.razorpay_order_id == "order_fresh"


@pytest.mark.asyncio
async def test_create_order_with_stale_order_id_mints_fresh(service, buyer):
    # Storefront form reuse path: the existing unpaid row carries the stale
    # Razorpay order id from the abandoned checkout — it must be replaced with a
    # completely new order, never returned to the client.
    existing = _order(status=RegistrationOrderStatus.CREATED, transfer_status="PAYMENT_PENDING")
    service._orders.get_active_transfer_by_buyer_and_domain = AsyncMock(return_value=existing)
    service._orders.create = AsyncMock(side_effect=lambda o: o)
    with patch(
        "app.service.domain.domain_registration_service.rzp.is_configured",
        return_value=True,
    ), patch(
        "app.service.domain.domain_registration_service.rzp.create_order",
        return_value={"id": "order_fresh"},
    ) as mock_rzp:
        res = await service.create_transfer_payment_order(
            {"domain": "retrytest.com", "authCode": "NEWCODE789"},
            buyer=buyer,
        )

    assert res["orderId"] == "order_fresh"
    assert res["orderId"] != "order_test"  # stale id never reused
    assert existing.razorpay_order_id == "order_fresh"
    assert existing.transfer_auth_code == "NEWCODE789"
    mock_rzp.assert_called_once()
    service._orders.create.assert_not_called()


# ── canRetryPayment serializer flag ───────────────────────────────────────────


@pytest.mark.parametrize(
    "status,ts,payment_id,expected",
    [
        (RegistrationOrderStatus.CREATED, "PAYMENT_PENDING", None, True),
        (RegistrationOrderStatus.EXPIRED, "PAYMENT_PENDING", None, True),
        (RegistrationOrderStatus.PAYMENT_FAILED, "PAYMENT_PENDING", None, True),
        (RegistrationOrderStatus.PAYMENT_COMPLETED, "PENDING", "pay_1", False),
        (RegistrationOrderStatus.REGISTRATION_PENDING, "PENDING", "pay_1", False),
        (RegistrationOrderStatus.ACTIVE, "COMPLETED", "pay_1", False),
        (RegistrationOrderStatus.PROVISION_FAILED, "FAILED", "pay_1", False),
        (RegistrationOrderStatus.REFUNDED, "FAILED", "pay_1", False),
        (RegistrationOrderStatus.CREATED, "NONE", None, False),
    ],
)
def test_can_retry_transfer_payment(status, ts, payment_id, expected):
    order = _order(status=status, transfer_status=ts, payment_id=payment_id)
    assert DomainRegistrationService._can_retry_transfer_payment(order) is expected


def test_order_detail_dict_exposes_can_retry_payment():
    from app.service.domain.domain_registration_followup import DomainRegistrationFollowup

    order = _order(status=RegistrationOrderStatus.CREATED, transfer_status="PAYMENT_PENDING")
    followup = DomainRegistrationFollowup.__new__(DomainRegistrationFollowup)
    summary = followup.order_detail_dict(order)
    assert summary["canRetryPayment"] is True
    assert summary["isTransfer"] is True
    assert summary["transferStatus"] == "PAYMENT_PENDING"
