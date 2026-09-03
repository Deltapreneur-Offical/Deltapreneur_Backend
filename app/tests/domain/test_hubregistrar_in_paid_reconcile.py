"""Isolated paid-order reconcile for hubregistrar.in — do not steal other orders."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.service.domain import domain_registration_service as drs_module
from app.service.domain.provider_domain_correlation import (
    decide_provider_link,
    emails_from_provider_details,
)
from app.utils.registration_enums import RegistrationOrderStatus

TARGET_ORDER_ID = UUID("315e944d-35a7-4e79-ac11-1b3b65da2291")
TARGET_RZP_ORDER = "order_TUlTJuDs3zCeeB"
TARGET_RZP_PAY = "pay_TUlUDOH8WsaJPc"
TARGET_OP_ID = "30145282"
TARGET_EMAIL = "neminath.akkole01@gmail.com"


async def _confirm_registrar(_self, order: DomainRegistrationOrder) -> bool:
    order.status = RegistrationOrderStatus.ACTIVE
    order.completed_at = datetime.now(timezone.utc)
    order.provision_message = "confirmed"
    return True


def _target_order(**kwargs) -> DomainRegistrationOrder:
    order = DomainRegistrationOrder(
        id=TARGET_ORDER_ID,
        domain_name="hubregistrar",
        domain_extension=".in",
        buyer_id=uuid4(),
        buyer_full_name="Neminath Akkole",
        buyer_email=TARGET_EMAIL,
        buyer_phone="9876543210",
        street="1 Main St",
        city="Delhi",
        state="Delhi",
        zip_code="110001",
        country="IN",
        period_years=1,
        price_inr=590.0,
        quoted_unit_price_inr=590.0,
        status=RegistrationOrderStatus.PROVISION_FAILED,
        razorpay_order_id=TARGET_RZP_ORDER,
        razorpay_payment_id=TARGET_RZP_PAY,
        open_provider_handle=None,
        open_provider_domain_id=None,
        provision_attempts=17,
        provision_message="Domain no longer available at registrar",
    )
    for key, value in kwargs.items():
        setattr(order, key, value)
    return order


def _other_customer_order(**kwargs) -> DomainRegistrationOrder:
    order = DomainRegistrationOrder(
        id=uuid4(),
        domain_name="otherbrand",
        domain_extension=".com",
        buyer_id=uuid4(),
        buyer_full_name="Other Customer",
        buyer_email="other.customer@example.com",
        buyer_phone="9123456789",
        street="2 Side St",
        city="Mumbai",
        state="MH",
        zip_code="400001",
        country="IN",
        period_years=1,
        price_inr=799.0,
        quoted_unit_price_inr=799.0,
        status=RegistrationOrderStatus.PAYMENT_COMPLETED,
        razorpay_order_id="order_OTHER_CUSTOMER",
        razorpay_payment_id="pay_OTHER_CUSTOMER",
        open_provider_handle="OP-OTHER",
        provision_attempts=0,
    )
    for key, value in kwargs.items():
        setattr(order, key, value)
    return order


def _free_reg_mock() -> MagicMock:
    mock_reg = MagicMock()
    mock_reg.is_configured = lambda: True
    mock_reg.check_domain = AsyncMock(return_value={"status": "free"})
    mock_reg.is_free = lambda c: str((c or {}).get("status") or "").lower() in (
        "free",
        "available",
    )
    mock_reg.resolve_registration_period = lambda p, ext: p
    mock_reg.lookup_order_id_by_domain = AsyncMock(return_value=None)
    mock_reg.register_domain = AsyncMock(
        return_value={
            "id": "new-reg-1",
            "entityid": "new-reg-1",
            "actionstatus": "Success",
            "status": "ACT",
            "nameservers": ["ns1.hubregistrar.com"],
            "nameserverSource": "openprovider",
        },
    )
    mock_reg.get_domain_all_details = AsyncMock(return_value={})
    mock_reg.get_customer = AsyncMock(return_value={})
    mock_reg.create_customer = AsyncMock(return_value="OP-NEW")
    mock_reg.is_private_whois_allowed = AsyncMock(return_value=False)
    mock_reg.friendly_error_from_body = lambda s: s
    return mock_reg


def _official_op_hubregistrar_record(*, provider_id=TARGET_OP_ID, owner_email=TARGET_EMAIL) -> dict:
    """Shape returned by GET /v1beta/domains and GET /v1beta/domains/{id}."""
    return {
        "id": int(provider_id) if str(provider_id).isdigit() else provider_id,
        "status": "ACT",
        "owner_handle": "XX-HUB-IN",
        "admin_handle": "XX-HUB-IN",
        "tech_handle": "XX-HUB-IN",
        "billing_handle": "XX-HUB-IN",
        "owner": {"full_name": "Neminath Akkole", "company_name": ""},
        "domain": {"name": "hubregistrar", "extension": "in"},
        "expiration_date": "2027-08-27 00:00:00",
        "verification_email_name": owner_email,
        "verification_email_status": "not verified",
    }


def _taken_reg_mock(*, provider_id=TARGET_OP_ID, owner_email=TARGET_EMAIL) -> MagicMock:
    mock_reg = _free_reg_mock()
    record = _official_op_hubregistrar_record(provider_id=provider_id, owner_email=owner_email)
    mock_reg.check_domain = AsyncMock(
        return_value={"status": "active", "reason": "in use"},
    )
    mock_reg.lookup_order_id_by_domain = AsyncMock(return_value=str(record["id"]))
    mock_reg.lookup_domain_record_by_fqdn = AsyncMock(return_value=record)
    mock_reg.get_domain_all_details = AsyncMock(return_value=record)
    mock_reg.get_customer = AsyncMock(return_value={"email": owner_email})
    mock_reg.register_domain = AsyncMock()
    return mock_reg


def _service_with_orders(order: DomainRegistrationOrder):
    mock_orders = AsyncMock()
    mock_orders.save = AsyncMock()
    mock_orders.list_by_openprovider_domain_id = AsyncMock(return_value=[])
    mock_orders.get_by_openprovider_domain_id = AsyncMock(return_value=None)
    mock_orders.list_by_razorpay_order_id = AsyncMock(return_value=[order])
    mock_orders.get_by_id = AsyncMock(return_value=order)
    mock_followup = AsyncMock()
    mock_followup.send_lifecycle_emails = AsyncMock()
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.delete = MagicMock()
    service = drs_module.DomainRegistrationService(session=mock_session)
    service._orders = mock_orders
    service._followup = mock_followup
    return service, mock_orders, mock_followup


def test_official_op_details_expose_verification_email_name():
    details = _official_op_hubregistrar_record()
    assert emails_from_provider_details(details) == {TARGET_EMAIL}


def test_decide_provider_link_uses_verification_email_name_without_customer_get():
    details = _official_op_hubregistrar_record()
    decision = decide_provider_link(
        paid=True,
        order_fqdn="hubregistrar.in",
        order_email=TARGET_EMAIL,
        order_handle=None,
        order_already_has_provider_id=None,
        provider_domain_id=TARGET_OP_ID,
        other_order_ids_with_provider_id=[],
        details=details,
        provider_owner_email=None,
    )
    assert decision.action == "reconcile"
    assert decision.reason == "PROVIDER_EMAIL_MATCHES_THIS_ORDER"


def test_decide_provider_link_email_match_this_order_only():
    decision = decide_provider_link(
        paid=True,
        order_fqdn="hubregistrar.in",
        order_email=TARGET_EMAIL,
        order_handle=None,
        order_already_has_provider_id=None,
        provider_domain_id=TARGET_OP_ID,
        other_order_ids_with_provider_id=[],
        details={
            "id": 30145282,
            "domain": {"name": "hubregistrar", "extension": "in"},
            "owner_handle": "XX-HUB-IN",
        },
        provider_owner_email=TARGET_EMAIL,
    )
    assert decision.action == "reconcile"
    assert decision.reason == "PROVIDER_EMAIL_MATCHES_THIS_ORDER"


def test_decide_provider_link_does_not_use_unrelated_owner():
    decision = decide_provider_link(
        paid=True,
        order_fqdn="hubregistrar.in",
        order_email=TARGET_EMAIL,
        order_handle=None,
        order_already_has_provider_id=None,
        provider_domain_id=TARGET_OP_ID,
        other_order_ids_with_provider_id=[],
        details={
            "domain": {"name": "hubregistrar", "extension": "in"},
            "owner_handle": "XX-OTHER",
        },
        provider_owner_email="someone.else@example.com",
    )
    assert decision.action == "attention"
    assert decision.reason == "INSUFFICIENT_CORRELATION"


def test_decide_provider_link_unpaid_never_adopts():
    decision = decide_provider_link(
        paid=False,
        order_fqdn="hubregistrar.in",
        order_email=TARGET_EMAIL,
        order_handle=None,
        order_already_has_provider_id=None,
        provider_domain_id=TARGET_OP_ID,
        other_order_ids_with_provider_id=[],
        details={"domain": {"name": "hubregistrar", "extension": "in"}},
        provider_owner_email=TARGET_EMAIL,
    )
    assert decision.action == "skip"
    assert decision.reason == "UNPAID_DO_NOT_ADOPT"


def test_decide_provider_link_other_order_owns_provider_id():
    other_id = str(uuid4())
    decision = decide_provider_link(
        paid=True,
        order_fqdn="hubregistrar.in",
        order_email=TARGET_EMAIL,
        order_handle=None,
        order_already_has_provider_id=None,
        provider_domain_id=TARGET_OP_ID,
        other_order_ids_with_provider_id=[other_id],
        details={"domain": {"name": "hubregistrar", "extension": "in"}},
        provider_owner_email=TARGET_EMAIL,
    )
    assert decision.action == "attention"
    assert decision.reason == "UNRELATED_ORDER_OWNS_PROVIDER_DOMAIN"


@pytest.mark.asyncio
async def test_target_paid_order_reconciles_matching_provider_domain():
    order = _target_order()
    mock_reg = _taken_reg_mock()
    service, mock_orders, mock_followup = _service_with_orders(order)

    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "is_demo_mode", return_value=False),
        patch.object(drs_module, "_require_registrar_runtime"),
        patch.object(
            drs_module.DomainRegistrationService,
            "_reconcile_registrar_order",
            _confirm_registrar,
        ),
    ):
        meta = await service.provision_order(order, return_meta=True)

    mock_reg.register_domain.assert_not_called()
    assert order.id == TARGET_ORDER_ID
    assert order.razorpay_order_id == TARGET_RZP_ORDER
    assert order.razorpay_payment_id == TARGET_RZP_PAY
    assert order.open_provider_domain_id == TARGET_OP_ID
    assert order.status == RegistrationOrderStatus.ACTIVE
    assert meta["action"] == "reconcile"
    assert meta["registerDomainCalled"] is False
    mock_orders.list_by_openprovider_domain_id.assert_awaited()


@pytest.mark.asyncio
async def test_target_paid_order_reconciles_from_verification_email_name_only():
    """Official OP GET domain fields are enough; do not require get_customer or register."""
    order = _target_order()
    mock_reg = _taken_reg_mock()
    mock_reg.get_customer = AsyncMock(return_value={})
    service, _orders, _followup = _service_with_orders(order)

    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "is_demo_mode", return_value=False),
        patch.object(drs_module, "_require_registrar_runtime"),
        patch.object(
            drs_module.DomainRegistrationService,
            "_reconcile_registrar_order",
            _confirm_registrar,
        ),
    ):
        meta = await service.provision_order(order, return_meta=True)

    mock_reg.register_domain.assert_not_called()
    mock_reg.get_customer.assert_not_awaited()
    assert order.open_provider_domain_id == TARGET_OP_ID
    assert order.status == RegistrationOrderStatus.ACTIVE
    assert meta["action"] == "reconcile"
    assert meta["registerDomainCalled"] is False


@pytest.mark.asyncio
async def test_duplicate_webhook_does_not_reregister_target_order():
    order = _target_order(
        status=RegistrationOrderStatus.ACTIVE,
        open_provider_domain_id=TARGET_OP_ID,
    )
    service, mock_orders, _followup = _service_with_orders(order)
    service.provision_order = AsyncMock()

    with patch(
        "app.service.platform.track_record_service.TrackRecordService.record_from_registration_order",
        new_callable=AsyncMock,
    ):
        with patch("app.integrations.razorpay.client.fetch_order") as mock_fetch:
            mock_fetch.return_value = {"notes": {"type": "registration"}}
            first = await service.complete_payment_from_webhook(
                TARGET_RZP_ORDER, TARGET_RZP_PAY,
            )
            second = await service.complete_payment_from_webhook(
                TARGET_RZP_ORDER, TARGET_RZP_PAY,
            )

    service.provision_order.assert_not_called()
    assert first["results"][0]["skipReason"] == "ALREADY_ACTIVE"
    assert second["results"][0]["skipReason"] == "ALREADY_ACTIVE"
    mock_orders.list_by_razorpay_order_id.assert_awaited_with(TARGET_RZP_ORDER)


@pytest.mark.asyncio
async def test_unrelated_normal_registration_still_registers():
    order = _other_customer_order(
        domain_name="brandnew",
        domain_extension=".com",
        open_provider_handle="OP-NEW",
    )
    mock_reg = _free_reg_mock()
    service, _orders, _followup = _service_with_orders(order)

    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "is_demo_mode", return_value=False),
        patch.object(drs_module, "_require_registrar_runtime"),
        patch.object(
            drs_module.DomainRegistrationService,
            "_reconcile_registrar_order",
            _confirm_registrar,
        ),
    ):
        meta = await service.provision_order(order, return_meta=True)

    mock_reg.register_domain.assert_awaited_once()
    assert order.open_provider_domain_id == "new-reg-1"
    assert order.status == RegistrationOrderStatus.ACTIVE
    assert meta["registerDomainCalled"] is True
    assert meta["action"] in ("register", "register_domain_success")
    assert order.id != TARGET_ORDER_ID


@pytest.mark.asyncio
async def test_unpaid_existing_provider_domain_still_domain_not_free():
    order = _other_customer_order(
        razorpay_payment_id=None,
        status=RegistrationOrderStatus.CREATED,
        domain_name="hubregistrar",
        domain_extension=".in",
        buyer_email=TARGET_EMAIL,
    )
    mock_reg = _taken_reg_mock()
    service, _orders, mock_followup = _service_with_orders(order)

    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "is_demo_mode", return_value=False),
        patch.object(drs_module, "_require_registrar_runtime"),
    ):
        meta = await service.provision_order(order, return_meta=True)

    mock_reg.register_domain.assert_not_called()
    assert order.open_provider_domain_id is None
    assert order.status == RegistrationOrderStatus.PROVISION_FAILED
    assert order.provision_message == "Domain no longer available at registrar"
    assert meta["skipReason"] == "DOMAIN_NOT_FREE"
    mock_followup.send_lifecycle_emails.assert_awaited()


@pytest.mark.asyncio
async def test_provider_domain_owned_by_unrelated_order_is_not_attached():
    order = _target_order()
    owner = _other_customer_order(
        domain_name="hubregistrar",
        domain_extension=".in",
        open_provider_domain_id=TARGET_OP_ID,
        status=RegistrationOrderStatus.ACTIVE,
    )
    mock_reg = _taken_reg_mock()
    service, mock_orders, _followup = _service_with_orders(order)
    mock_orders.list_by_openprovider_domain_id = AsyncMock(return_value=[owner])

    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "is_demo_mode", return_value=False),
        patch.object(drs_module, "_require_registrar_runtime"),
        patch.object(
            drs_module.DomainRegistrationService,
            "_reconcile_registrar_order",
            _confirm_registrar,
        ),
    ):
        meta = await service.provision_order(order, return_meta=True)

    mock_reg.register_domain.assert_not_called()
    assert order.open_provider_domain_id is None
    assert order.id == TARGET_ORDER_ID
    assert owner.open_provider_domain_id == TARGET_OP_ID
    assert owner.status == RegistrationOrderStatus.ACTIVE
    assert meta["action"] == "attention"
    assert meta["skipReason"] == "UNRELATED_ORDER_OWNS_PROVIDER_DOMAIN"
    assert "Requires attention" in (order.provision_message or "")


@pytest.mark.asyncio
async def test_provider_domain_email_mismatch_is_not_attached():
    order = _target_order()
    mock_reg = _taken_reg_mock(owner_email="not.this.buyer@example.com")
    service, _orders, _followup = _service_with_orders(order)

    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "is_demo_mode", return_value=False),
        patch.object(drs_module, "_require_registrar_runtime"),
        patch.object(
            drs_module.DomainRegistrationService,
            "_reconcile_registrar_order",
            _confirm_registrar,
        ),
    ):
        meta = await service.provision_order(order, return_meta=True)

    mock_reg.register_domain.assert_not_called()
    assert order.open_provider_domain_id is None
    assert meta["action"] == "attention"
    assert meta["skipReason"] == "INSUFFICIENT_CORRELATION"


@pytest.mark.asyncio
async def test_webhook_for_target_razorpay_order_does_not_touch_other_orders():
    target = _target_order(status=RegistrationOrderStatus.PROVISION_FAILED)
    other = _other_customer_order(status=RegistrationOrderStatus.PAYMENT_COMPLETED)
    service, mock_orders, _followup = _service_with_orders(target)
    mock_orders.list_by_razorpay_order_id = AsyncMock(return_value=[target])
    mock_orders.get_by_id = AsyncMock(return_value=target)

    async def provision(order, return_meta=False):
        assert order.id == TARGET_ORDER_ID
        assert order.razorpay_order_id == TARGET_RZP_ORDER
        assert other.status == RegistrationOrderStatus.PAYMENT_COMPLETED
        assert other.open_provider_domain_id is None
        return {"action": "reconcile", "registerDomainCalled": False, "skipReason": "EMAIL_MATCH"}

    service.provision_order = AsyncMock(side_effect=provision)

    with patch(
        "app.service.platform.track_record_service.TrackRecordService.record_from_registration_order",
        new_callable=AsyncMock,
    ):
        with patch("app.integrations.razorpay.client.fetch_order") as mock_fetch:
            mock_fetch.return_value = {"notes": {"type": "registration"}}
            outcome = await service.complete_payment_from_webhook(
                TARGET_RZP_ORDER, TARGET_RZP_PAY,
            )

    service.provision_order.assert_awaited_once()
    mock_orders.list_by_razorpay_order_id.assert_awaited_with(TARGET_RZP_ORDER)
    assert outcome["ordersFound"] == 1
    assert outcome["results"][0]["orderId"] == str(TARGET_ORDER_ID)
    assert other.status == RegistrationOrderStatus.PAYMENT_COMPLETED
