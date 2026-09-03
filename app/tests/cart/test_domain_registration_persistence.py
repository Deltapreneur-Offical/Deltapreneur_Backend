"""Tests verifying domain registration order persistence upon successful Razorpay payment."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

pytest_plugins = ("pytest_asyncio",)
import pytest

from app.entity.cart.cart_item_entity import CartItem
from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.entity.user.app_user import AppUser
from app.service.cart.cart_checkout_service import CartCheckoutService
from app.service.domain.domain_registration_ops_service import DomainRegistrationOpsService
from app.service.domain.domain_registration_service import DomainRegistrationService
from app.utils.cart_enums import CartProductType
from app.utils.registration_enums import RegistrationOrderStatus


@pytest.mark.asyncio
async def test_complete_domain_registration_persists_order_on_payment_success():
    """Verify that domain registration order is created and committed immediately after payment."""
    buyer = AppUser(
        id=uuid.uuid4(),
        email="testbuyer@example.com",
        firstname="Test",
        lastname="Buyer",
    )
    cart_item = CartItem(
        id=uuid.uuid4(),
        user_id=buyer.id,
        product_type=CartProductType.DOMAIN_REGISTRATION,
        product_id=uuid.uuid4(),
        metadata_json={
            "domainName": "melligen.com",
            "price": 899.0,
            "period": 1,
            "_checkout_razorpay_order_id": "order_rzp_123456",
            "_checkout_registrant": {
                "firstName": "Melligen",
                "lastName": "User",
                "email": "melligen@example.com",
                "phone": "9876543210",
                "street": "123 Main St",
                "city": "Mumbai",
                "state": "MH",
                "zip": "400001",
                "country": "IN",
            },
        },
    )

    created_orders = []

    async def fake_create(order):
        order.id = uuid.uuid4()
        created_orders.append(order)
        return order

    async def fake_save(order):
        return order

    session = SimpleNamespace(
        add=MagicMock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
        refresh=AsyncMock(),
    )
    checkout_svc = CartCheckoutService(session)
    checkout_svc._repo = SimpleNamespace(
        save=AsyncMock(),
        delete_items_by_ids=AsyncMock(),
    )

    with patch(
        "app.repository.domain_registration_order_repository.DomainRegistrationOrderRepository.create",
        side_effect=fake_create,
    ), patch(
        "app.repository.domain_registration_order_repository.DomainRegistrationOrderRepository.save",
        side_effect=fake_save,
    ), patch.object(
        DomainRegistrationService,
        "provision_order",
        new=AsyncMock(return_value=None),
    ):
        res = await checkout_svc._complete_domain_registration(
            cart_item, buyer, "pay_rzp_987654"
        )

    assert res["success"] is True
    assert res["domain"] == "melligen.com"
    assert len(created_orders) == 1
    assert created_orders[0].domain_name == "melligen"
    assert created_orders[0].domain_extension == ".com"
    assert created_orders[0].razorpay_payment_id == "pay_rzp_987654"
    assert created_orders[0].razorpay_order_id == "order_rzp_123456"
    assert session.commit.called


@pytest.mark.asyncio
async def test_complete_domain_registration_persists_order_even_if_openprovider_fails():
    """Verify that if OpenProvider provisioning fails, the DB record is STILL persisted with PROVISION_FAILED."""
    buyer = AppUser(
        id=uuid.uuid4(),
        email="testbuyer@example.com",
        firstname="Test",
        lastname="Buyer",
    )
    cart_item = CartItem(
        id=uuid.uuid4(),
        user_id=buyer.id,
        product_type=CartProductType.DOMAIN_REGISTRATION,
        product_id=uuid.uuid4(),
        metadata_json={
            "domainName": "melligen.com",
            "price": 899.0,
            "period": 1,
            "_checkout_razorpay_order_id": "order_rzp_123456",
            "_checkout_registrant": {
                "firstName": "Melligen",
                "lastName": "User",
                "email": "melligen@example.com",
                "phone": "9876543210",
                "street": "123 Main St",
                "city": "Mumbai",
                "state": "MH",
                "zip": "400001",
                "country": "IN",
            },
        },
    )

    created_orders = []

    async def fake_create(order):
        order.id = uuid.uuid4()
        created_orders.append(order)
        return order

    async def fake_save(order):
        return order

    async def fake_get_by_id(*args):
        order_id = args[-1]
        for o in created_orders:
            if o.id == order_id:
                return o
        return None

    execute_result = MagicMock()
    execute_result.scalar_one_or_none = MagicMock(
        side_effect=lambda: created_orders[-1] if created_orders else None
    )
    session = SimpleNamespace(
        add=MagicMock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
        refresh=AsyncMock(),
        execute=AsyncMock(return_value=execute_result),
    )
    checkout_svc = CartCheckoutService(session)

    with patch(
        "app.repository.domain_registration_order_repository.DomainRegistrationOrderRepository.create",
        side_effect=fake_create,
    ), patch(
        "app.repository.domain_registration_order_repository.DomainRegistrationOrderRepository.save",
        side_effect=fake_save,
    ), patch(
        "app.repository.domain_registration_order_repository.DomainRegistrationOrderRepository.get_by_id",
        side_effect=fake_get_by_id,
    ), patch.object(
        DomainRegistrationService,
        "provision_order",
        side_effect=RuntimeError("OpenProvider API connection timeout"),
    ):
        res = await checkout_svc._complete_domain_registration(
            cart_item, buyer, "pay_rzp_987654"
        )

    assert res["success"] is True
    assert res["provisionSuccess"] is False
    assert len(created_orders) == 1
    assert created_orders[0].domain_name == "melligen"
    assert created_orders[0].status == RegistrationOrderStatus.PROVISION_FAILED
    assert "OpenProvider API connection timeout" in created_orders[0].provision_message
    assert session.commit.called


@pytest.mark.asyncio
async def test_admin_list_orders_returns_enriched_tracking_fields():
    """Verify that Admin list orders returns full buyer, payment, registrar, and timestamp info."""
    buyer = AppUser(
        id=uuid.uuid4(),
        email="buyer@example.com",
        firstname="John",
        lastname="Doe",
    )
    order = DomainRegistrationOrder(
        id=uuid.uuid4(),
        domain_name="melligen",
        domain_extension=".com",
        buyer_id=buyer.id,
        buyer_full_name="John Doe",
        buyer_email="buyer@example.com",
        buyer_phone="9876543210",
        price_inr=999.0,
        status=RegistrationOrderStatus.PAYMENT_COMPLETED,
        razorpay_order_id="order_123",
        razorpay_payment_id="pay_123",
        open_provider_domain_id="OP-999",
        open_provider_status="PENDING",
        provision_message="Submitted to registrar",
        provision_attempts=1,
        buyer=buyer,
    )

    session = SimpleNamespace(
        execute=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    ops_svc = DomainRegistrationOpsService(session)
    ops_svc._orders = SimpleNamespace(
        list_all=AsyncMock(return_value=[order])
    )

    orders = await ops_svc.admin_list_orders()
    assert len(orders) == 1
    rec = orders[0]
    assert rec["domain"] == "melligen.com"
    assert rec["buyerName"] == "John Doe"
    assert rec["buyerEmail"] == "buyer@example.com"
    assert rec["buyerPhone"] == "9876543210"
    assert rec["razorpayOrderId"] == "order_123"
    assert rec["razorpayPaymentId"] == "pay_123"
    assert rec["registrar"] == "OpenProvider"
    assert rec["openProviderDomainId"] == "OP-999"
    assert rec["openProviderStatus"] == "PENDING"
    assert rec["provisionMessage"] == "Submitted to registrar"
