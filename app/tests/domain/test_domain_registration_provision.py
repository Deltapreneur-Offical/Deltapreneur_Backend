"""Post-payment OpenProvider registration, price verify, webhook idempotency."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.service.domain import domain_registration_service as drs_module
from app.utils.registration_enums import RegistrationOrderStatus


async def _confirm_registrar(_self, order: DomainRegistrationOrder) -> bool:
    order.status = RegistrationOrderStatus.ACTIVE
    order.completed_at = datetime.now(timezone.utc)
    order.provision_message = "confirmed"
    return True


def _sample_order(**kwargs) -> DomainRegistrationOrder:
    order = DomainRegistrationOrder(
        id=uuid4(),
        domain_name="brand",
        domain_extension=".com",
        buyer_id=uuid4(),
        buyer_full_name="Test User",
        buyer_email="test@example.com",
        buyer_phone="9876543210",
        street="1 Main St",
        city="Delhi",
        state="Delhi",
        zip_code="110001",
        country="IN",
        period_years=1,
        price_inr=799.0,
        quoted_unit_price_inr=799.0,
        status=RegistrationOrderStatus.PAYMENT_COMPLETED,
        open_provider_handle="rc:100:200",
        provision_attempts=0,
    )
    for key, value in kwargs.items():
        setattr(order, key, value)
    return order


@pytest.mark.asyncio
async def test_verify_checkout_price_rejects_mismatch():
    mock_reg = MagicMock()
    mock_reg.is_configured = lambda: True
    mock_reg.resolve_registration_period = lambda p, ext: p
    mock_reg.get_create_price = AsyncMock(
        return_value={
            "is_premium": False,
            "price": {"reseller": {"currency": "INR", "price": 899.0}},
        }
    )
    mock_reg.extract_create_price_details = lambda quote, **kw: (899.0, "INR", "openprovider_panel_inr")

    service = drs_module.DomainRegistrationService(session=AsyncMock())
    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "is_demo_mode", return_value=False),
        patch(
            "app.service.domain.domain_commission_config.calculate_customer_price",
            side_effect=lambda provider_price, **kw: {
                "providerUnitInr": float(provider_price),
                "customerUnitInr": float(provider_price),
                "commissionRate": 0.0,
                "commissionService": "registration",
                "isPremium": False,
                "registryTier": "standard",
                "currency": "INR",
                "providerCurrency": "INR",
            },
        ),
    ):
        with pytest.raises(drs_module.AppException) as exc:
            await service._verify_checkout_price(
                "brand",
                "com",
                1,
                expected_unit_price=799.0,
            )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_provision_success_stores_openprovider_fields():
    order = _sample_order()
    mock_reg = MagicMock()
    mock_reg.is_configured = lambda: True
    mock_reg.check_domain = AsyncMock(return_value={"status": "available"})
    mock_reg.is_free = lambda c: True
    mock_reg.resolve_registration_period = lambda p, ext: p
    mock_reg.lookup_order_id_by_domain = AsyncMock(return_value=None)
    mock_reg.register_domain = AsyncMock(
        return_value={
            "id": "12345",
            "entityid": "12345",
            "actionid": "eaq-99",
            "actionstatus": "Success",
            "actionstatusdesc": "Domain registration completed",
            "invoiceid": None,
            "attributes": {"entityid": "12345", "eaqid": "eaq-99"},
        },
    )

    mock_orders = AsyncMock()
    mock_orders.save = AsyncMock()

    service = drs_module.DomainRegistrationService(session=AsyncMock())
    service._orders = mock_orders

    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "is_demo_mode", return_value=False),
        patch.object(drs_module, "_require_registrar_runtime"),
        patch.object(drs_module.DomainRegistrationService, "_reconcile_registrar_order", _confirm_registrar),
    ):
        await service.provision_order(order)

    assert order.open_provider_domain_id == "12345"
    assert order.open_provider_status == "Success"
    assert order.status == RegistrationOrderStatus.ACTIVE
    assert order.registrar_response_json is not None


@pytest.mark.asyncio
async def test_provision_skips_duplicate_when_order_id_exists():
    order = _sample_order(
        open_provider_domain_id="999",
        status=RegistrationOrderStatus.REGISTRATION_PENDING,
    )
    mock_reg = MagicMock()
    mock_reg.is_configured = lambda: True
    mock_reg.register_domain = AsyncMock()

    mock_orders = AsyncMock()
    mock_orders.save = AsyncMock()

    service = drs_module.DomainRegistrationService(session=AsyncMock())
    service._orders = mock_orders

    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "_require_registrar_runtime"),
        patch.object(drs_module.DomainRegistrationService, "_reconcile_registrar_order", _confirm_registrar),
    ):
        await service.provision_order(order)

    mock_reg.register_domain.assert_not_called()
    assert order.status == RegistrationOrderStatus.ACTIVE


@pytest.mark.asyncio
async def test_webhook_idempotent_when_already_active():
    order = _sample_order(
        status=RegistrationOrderStatus.ACTIVE,
        razorpay_order_id="order_x",
        open_provider_domain_id="op-123",
    )
    mock_orders = AsyncMock()
    mock_orders.list_by_razorpay_order_id = AsyncMock(return_value=[order])
    mock_orders.get_by_razorpay_order_id = AsyncMock(return_value=order)
    mock_orders.save = AsyncMock()

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.delete = MagicMock()
    service = drs_module.DomainRegistrationService(session=mock_session)
    service._orders = mock_orders
    service.provision_order = AsyncMock()

    with patch(
        "app.service.platform.track_record_service.TrackRecordService.record_from_registration_order",
        new_callable=AsyncMock,
    ) as mock_track_record:
        with patch("app.integrations.razorpay.client.fetch_order") as mock_fetch:
            mock_fetch.return_value = {"notes": {"type": "registration"}}
            outcome = await service.complete_payment_from_webhook("order_x", "pay_y")

    service.provision_order.assert_not_called()
    mock_track_record.assert_awaited_once()
    assert outcome["ordersFound"] == 1
    assert outcome["registrationSuccessful"] is True
    assert outcome["results"][0]["skipReason"] == "ALREADY_ACTIVE"

@pytest.mark.asyncio
async def test_ambiguous_register_reconciles_on_failure():
    order = _sample_order(        open_provider_domain_id="555", status=RegistrationOrderStatus.REGISTRATION_PENDING)
    mock_reg = MagicMock()
    mock_reg.is_configured = lambda: True
    mock_reg.check_domain = AsyncMock(return_value={"status": "available"})
    mock_reg.is_free = lambda c: True
    mock_reg.resolve_registration_period = lambda p, ext: p
    mock_reg.register_domain = AsyncMock(side_effect=RuntimeError("timeout"))
    mock_reg.friendly_error_from_body = lambda s: s

    mock_orders = AsyncMock()
    mock_orders.save = AsyncMock()

    service = drs_module.DomainRegistrationService(session=AsyncMock())
    service._orders = mock_orders

    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "is_demo_mode", return_value=False),
        patch.object(drs_module, "_require_registrar_runtime"),
        patch.object(drs_module.DomainRegistrationService, "_reconcile_registrar_order", _confirm_registrar),
    ):
        await service.provision_order(order)

    assert order.status == RegistrationOrderStatus.ACTIVE
    mock_reg.register_domain.assert_not_called()


@pytest.mark.asyncio
async def test_provision_order_refuses_domain_transfers():
    order = _sample_order(
        transfer_status="PENDING",
    )
    service = drs_module.DomainRegistrationService(session=AsyncMock())

    with pytest.raises(RuntimeError) as exc:
        await service.provision_order(order)
    
    assert "TRANSFER order" in str(exc.value)
    assert "_provision_transfer" in str(exc.value)


@pytest.mark.asyncio
async def test_paid_not_free_does_not_mark_provision_failed():
    """Captured payment + concurrent registrar success must not be marked failed."""
    order = _sample_order(razorpay_payment_id="pay_live_1")
    mock_reg = MagicMock()
    mock_reg.is_configured = lambda: True
    mock_reg.check_domain = AsyncMock(return_value={"status": "unavailable"})
    mock_reg.is_free = lambda c: False
    mock_reg.lookup_order_id_by_domain = AsyncMock(return_value=None)
    mock_reg.register_domain = AsyncMock()

    mock_orders = AsyncMock()
    mock_orders.save = AsyncMock()
    mock_followup = AsyncMock()
    mock_followup.send_lifecycle_emails = AsyncMock()

    service = drs_module.DomainRegistrationService(session=AsyncMock())
    service._orders = mock_orders
    service._followup = mock_followup

    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "is_demo_mode", return_value=False),
        patch.object(drs_module, "_require_registrar_runtime"),
    ):
        meta = await service.provision_order(order, return_meta=True)

    mock_reg.register_domain.assert_not_called()
    mock_followup.send_lifecycle_emails.assert_not_awaited()
    assert order.status == RegistrationOrderStatus.REGISTRATION_PENDING
    assert meta["skipReason"] == "DOMAIN_NOT_FREE_PAID_PENDING"
    assert meta["action"] == "attention"
    assert "no longer free" in (order.provision_message or "").lower()


@pytest.mark.asyncio
async def test_unpaid_not_free_still_marks_provision_failed():
    order = _sample_order()
    mock_reg = MagicMock()
    mock_reg.is_configured = lambda: True
    mock_reg.check_domain = AsyncMock(return_value={"status": "unavailable"})
    mock_reg.is_free = lambda c: False
    mock_reg.lookup_order_id_by_domain = AsyncMock(return_value=None)
    mock_reg.register_domain = AsyncMock()

    mock_orders = AsyncMock()
    mock_orders.save = AsyncMock()
    mock_followup = AsyncMock()
    mock_followup.send_lifecycle_emails = AsyncMock()

    service = drs_module.DomainRegistrationService(session=AsyncMock())
    service._orders = mock_orders
    service._followup = mock_followup

    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "is_demo_mode", return_value=False),
        patch.object(drs_module, "_require_registrar_runtime"),
    ):
        meta = await service.provision_order(order, return_meta=True)

    assert order.status == RegistrationOrderStatus.PROVISION_FAILED
    assert order.provision_message == "Domain no longer available at registrar"
    assert meta["skipReason"] == "DOMAIN_NOT_FREE"
    mock_followup.send_lifecycle_emails.assert_awaited()
    mock_reg.register_domain.assert_not_called()
