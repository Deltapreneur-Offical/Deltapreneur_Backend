"""Tests for generic ResellPortal technology provisioning in cart checkout."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from app.entity.technology_services.technology_service_entity import TechnologyServiceEntity
from app.service.cart.cart_checkout_service import CartCheckoutService
from app.service.resellportal.product_mapper import get_product_key, is_provider_mapped


def _make_tech_service(slug: str, provider_product_key: str | None = None) -> TechnologyServiceEntity:
    svc = TechnologyServiceEntity()
    svc.id = "11111111-1111-1111-1111-111111111111"
    svc.slug = slug
    svc.name = slug.replace("-", " ").title()
    svc.plans_json = json.dumps([{"code": "starter", "price_monthly": 10, "price_annually": 100}])
    svc.price_override_monthly = None
    svc.price_override_annually = None
    svc.provider_product_key = provider_product_key
    return svc


def _make_cart_item(service_id, slug: str, selected_plan: str = "starter") -> MagicMock:
    item = MagicMock()
    item.id = "22222222-2222-2222-2222-222222222222"
    item.product_type = "TECHNOLOGY"
    item.product_id = service_id
    item.selected_plan = selected_plan
    item.addon_services = None
    item.co_brother_opt_in = False
    item.metadata_json = {
        "productName": slug.replace("-", " ").title(),
        "serviceSlug": slug,
        "billingCycle": "monthly",
        "planCode": selected_plan,
    }
    return item


def _make_buyer():
    buyer = MagicMock()
    buyer.id = "33333333-3333-3333-3333-333333333333"
    buyer.email = "buyer@cobrother.com"
    buyer.firstname = "Test"
    buyer.lastname = "Buyer"
    buyer.phone_number = "+919999999999"
    return buyer


@pytest.mark.asyncio
async def test_generic_provisioning_uses_product_mapper():
    """Verify that cart checkout uses the centralized product mapper for any mapped service."""
    service_id = "11111111-1111-1111-1111-111111111111"
    slug = "website-builder"
    product_key = get_product_key(slug)
    assert product_key == "website_builder"

    svc = _make_tech_service(slug, provider_product_key=product_key)
    item = _make_cart_item(service_id, slug)
    buyer = _make_buyer()

    mock_prov_res = {
        "success": True,
        "status": "ACTIVE",
        "provider_order_id": "RSP-ORD-TEST123",
        "provider_subscription_id": "RSP-SUB-TEST123",
        "credentials": {"access_url": "https://workspace.cobrother.com/app/website-builder/test?token=abc"},
        "current_period_start": datetime.now(timezone.utc),
        "current_period_end": datetime.now(timezone.utc),
        "is_mock": True,
    }

    with patch("app.service.cart.cart_checkout_service.CartService") as MockCartService, \
         patch("app.service.cart.cart_checkout_service.CartItemRepository") as MockRepo, \
         patch("app.integrations.resellportal.client.get_resellportal_client") as mock_get_client, \
         patch("app.service.auth.mail_service.MailService") as MockMail, \
         patch("app.repository.software_purchase_repository.SoftwarePurchaseRepository") as MockPurchaseRepo, \
         patch("app.repository.cobrother_request_repository.CoBrotherRequestRepository") as MockCobrotherRepo:

        mock_cart_svc = MockCartService.return_value
        mock_cart_svc._get_technology_service = AsyncMock(return_value=svc)
        mock_cart_svc._get_technology_service_fallback = AsyncMock(return_value=None)

        mock_repo = MockRepo.return_value
        mock_repo.get_by_user_for_update.return_value = [item]

        mock_purchase_repo = MagicMock()
        mock_purchase_repo.get_by_razorpay_payment_id = AsyncMock(return_value=None)
        MockPurchaseRepo.return_value = mock_purchase_repo

        mock_cobrother_repo = MagicMock()
        mock_cobrother_repo.create = AsyncMock()
        MockCobrotherRepo.return_value = mock_cobrother_repo

        mock_client = MagicMock()
        mock_client.provision_service.return_value = mock_prov_res
        mock_client.reconcile_pending_provisioning.return_value = {
            "reconciled": False,
            "provider_order_id": None,
        }
        mock_get_client.return_value = mock_client

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        ))
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        service = CartCheckoutService(mock_session)
        result = await service._complete_technology_purchase(
            item=item,
            buyer=buyer,
            razorpay_payment_id="rzp_test_123",
            buyer_name="Test Buyer",
            buyer_email="buyer@cobrother.com",
            buyer_phone="+919999999999",
        )

        assert result["type"] == "TECHNOLOGY"
        mock_client.provision_service.assert_called_once()
        call_kwargs = mock_client.provision_service.call_args
        assert call_kwargs.kwargs["product_key"] == "website_builder"
        assert call_kwargs.kwargs["service_slug"] == slug


@pytest.mark.asyncio
async def test_unmapped_service_skips_provisioning():
    """Verify that unmapped services do not trigger ResellPortal provisioning."""
    service_id = "44444444-4444-4444-4444-444444444444"
    slug = "wordpress-plugin-pack"
    svc = _make_tech_service(slug, provider_product_key=None)
    item = _make_cart_item(service_id, slug)
    buyer = _make_buyer()

    with patch("app.service.cart.cart_checkout_service.CartService") as MockCartService, \
         patch("app.service.cart.cart_checkout_service.CartItemRepository") as MockRepo, \
         patch("app.integrations.resellportal.client.get_resellportal_client") as mock_get_client, \
         patch("app.repository.software_purchase_repository.SoftwarePurchaseRepository") as MockPurchaseRepo, \
         patch("app.repository.cobrother_request_repository.CoBrotherRequestRepository") as MockCobrotherRepo:

        mock_cart_svc = MockCartService.return_value
        mock_cart_svc._get_technology_service = AsyncMock(return_value=svc)
        mock_cart_svc._get_technology_service_fallback = AsyncMock(return_value=None)

        mock_repo = MockRepo.return_value
        mock_repo.get_by_user_for_update.return_value = [item]

        mock_purchase_repo = MagicMock()
        mock_purchase_repo.get_by_razorpay_payment_id = AsyncMock(return_value=None)
        MockPurchaseRepo.return_value = mock_purchase_repo

        mock_cobrother_repo = MagicMock()
        mock_cobrother_repo.create = AsyncMock()
        MockCobrotherRepo.return_value = mock_cobrother_repo

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        ))
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        service = CartCheckoutService(mock_session)
        result = await service._complete_technology_purchase(
            item=item,
            buyer=buyer,
            razorpay_payment_id="rzp_test_456",
            buyer_name="Test Buyer",
            buyer_email="buyer@cobrother.com",
            buyer_phone="+919999999999",
        )

        assert result["type"] == "TECHNOLOGY"
        mock_get_client.assert_not_called()
