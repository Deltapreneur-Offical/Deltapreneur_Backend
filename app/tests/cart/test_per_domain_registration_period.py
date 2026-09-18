"""Per-domain registration period cart + checkout behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import AppException
from app.service.cart.cart_checkout_service import CartCheckoutService
from app.service.cart.cart_service import CartService
from app.utils.domain_gst import domain_price_breakdown
from app.utils.cart_enums import CartProductType


def _reg_item(*, domain: str, period: int, min_period: int, price: float):
    return SimpleNamespace(
        id=uuid4(),
        product_type=CartProductType.DOMAIN_REGISTRATION,
        product_id=uuid4(),
        metadata_json={
            "domainName": domain,
            "tld": domain.split(".", 1)[1],
            "period": period,
            "minPeriodYears": min_period,
            "price": price,
            "pricePerYear": price / max(1, period),
        },
    )


@pytest.mark.asyncio
async def test_update_domain_registration_period_only_updates_requested_item():
    com = _reg_item(domain="savjiadda.com", period=1, min_period=1, price=1000.0)
    ai = _reg_item(domain="batterify.ai", period=2, min_period=2, price=16000.0)

    repo = AsyncMock()
    repo.get_by_user = AsyncMock(return_value=[com, ai])
    repo.save = AsyncMock()

    service = CartService(session=AsyncMock())
    service._repo = repo
    service.get_cart = AsyncMock(return_value=MagicMock())

    quote = {
        "price": 5000.0,
        "pricePerYear": 1000.0,
        "periodYears": 5,
        "minPeriodYears": 1,
        "priceSource": "openprovider_prices",
        "commissionRate": 0.1,
    }

    with patch(
        "app.service.domain.domain_registration_service.DomainRegistrationService"
    ) as svc_cls:
        svc = svc_cls.return_value
        svc.quote_registration_period_price = AsyncMock(return_value=quote)
        await service.update_domain_registration_period(
            uuid4(),
            5,
            item_id=com.id,
        )

    svc.quote_registration_period_price.assert_awaited_once_with("savjiadda.com", 5)
    assert com.metadata_json["period"] == 5
    assert com.metadata_json["price"] == 5000.0
    # Unselected .ai line must keep its own period.
    assert ai.metadata_json["period"] == 2
    assert ai.metadata_json["price"] == 16000.0


@pytest.mark.asyncio
async def test_revalidate_quotes_each_item_at_its_own_period():
    com = _reg_item(domain="savjiadda.com", period=5, min_period=1, price=5000.0)
    ai = _reg_item(domain="batterify.ai", period=2, min_period=2, price=16000.0)

    checkout = CartCheckoutService(session=AsyncMock())
    checkout._repo = AsyncMock()
    checkout._repo.save = AsyncMock()

    check_ok = SimpleNamespace(status="available", isPremium=False)

    async def _quote(domain, years, **kwargs):
        if domain.endswith(".ai"):
            assert years == 2
            return {
                "price": 17784.37,
                "pricePerYear": 8892.18,
                "periodYears": 2,
                "minPeriodYears": 2,
                "priceSource": "openprovider_prices",
                "commissionRate": 0.1,
                "isPremium": False,
                "registryTier": "standard",
            }
        assert years == 5
        return {
            "price": 5813.3,
            "pricePerYear": 1162.66,
            "periodYears": 5,
            "minPeriodYears": 1,
            "priceSource": "openprovider_prices",
            "commissionRate": 0.1,
            "isPremium": False,
            "registryTier": "standard",
        }

    with patch(
        "app.service.domain.domain_registration_service.DomainRegistrationService"
    ) as svc_cls:
        svc = svc_cls.return_value
        svc.check_registration_domain = AsyncMock(return_value=check_ok)
        svc.quote_registration_period_price = AsyncMock(side_effect=_quote)
        await checkout._revalidate_domain_registration_items([com, ai])

    assert com.metadata_json["period"] == 5
    assert com.metadata_json["price"] == 5813.3
    assert ai.metadata_json["period"] == 2
    assert ai.metadata_json["price"] == 17784.37


@pytest.mark.asyncio
async def test_revalidate_bumps_ai_below_minimum_to_two_years():
    ai = _reg_item(domain="batterify.ai", period=1, min_period=2, price=8892.18)
    checkout = CartCheckoutService(session=AsyncMock())
    checkout._repo = AsyncMock()
    checkout._repo.save = AsyncMock()

    with patch(
        "app.service.domain.domain_registration_service.DomainRegistrationService"
    ) as svc_cls:
        svc = svc_cls.return_value
        svc.check_registration_domain = AsyncMock(
            return_value=SimpleNamespace(status="available", isPremium=False),
        )
        svc.quote_registration_period_price = AsyncMock(
            return_value={
                "price": 17784.37,
                "pricePerYear": 8892.18,
                "periodYears": 2,
                "minPeriodYears": 2,
                "priceSource": "openprovider_prices",
                "isPremium": False,
                "registryTier": "standard",
            },
        )
        await checkout._revalidate_domain_registration_items([ai])

    svc.quote_registration_period_price.assert_awaited_once_with(
        "batterify.ai",
        2,
        require_live_price=True,
    )
    assert ai.metadata_json["period"] == 2


def test_require_registrant_still_works():
    with pytest.raises(AppException):
        CartCheckoutService._require_registrant({"firstName": "A"})


@pytest.mark.asyncio
async def test_normal_domain_provider_base_uses_registration_commission_for_cart_and_checkout():
    item = SimpleNamespace(
        id=uuid4(),
        product_type=CartProductType.DOMAIN_REGISTRATION,
        product_id=uuid4(),
        selected_plan=None,
        addon_services=None,
        co_brother_opt_in=False,
        metadata_json={
            "domainName": "example.com",
            "tld": "com",
            "period": 1,
            "minPeriodYears": 1,
            "price": 1000.0,
            "pricePerYear": 1000.0,
            "providerUnitPriceInr": 1000.0,
            "providerPeriodTotalInr": 1000.0,
            "isPremium": False,
            "registryTier": "standard",
        },
    )

    with patch(
        "app.service.domain.domain_commission_config.get_rate",
        return_value=0.15,
    ):
        cart = CartService(session=AsyncMock())
        response = await cart._build_item_response(item)

        checkout = CartCheckoutService(session=AsyncMock())
        line_total = await checkout._resolve_line_total(item, buyer=SimpleNamespace(id=uuid4()))

    assert response.base_price == 1000.0
    assert response.line_total == 1150.0
    assert line_total == 1150.0
    assert domain_price_breakdown(line_total, years=1)["totalInr"] == 1357.0


@pytest.mark.asyncio
async def test_existing_normal_domain_cart_row_without_provider_meta_gets_registration_commission():
    item = SimpleNamespace(
        id=uuid4(),
        product_type=CartProductType.DOMAIN_REGISTRATION,
        product_id=uuid4(),
        selected_plan=None,
        addon_services=None,
        co_brother_opt_in=False,
        metadata_json={
            "domainName": "hjki.org",
            "tld": "org",
            "period": 1,
            "minPeriodYears": 1,
            "price": 1000.0,
            "pricePerYear": 1000.0,
            "isPremium": False,
            "registryTier": "standard",
        },
    )

    with patch(
        "app.service.domain.domain_commission_config.get_rate",
        return_value=0.15,
    ):
        cart = CartService(session=AsyncMock())
        response = await cart._build_item_response(item)

    assert response.base_price == 1000.0
    assert response.line_total == 1150.0
    assert domain_price_breakdown(response.line_total, years=1)["totalInr"] == 1357.0


@pytest.mark.asyncio
async def test_delta_domain_uses_premium_registration_commission_for_cart_and_checkout():
    item = SimpleNamespace(
        id=uuid4(),
        product_type=CartProductType.DOMAIN_REGISTRATION,
        product_id=uuid4(),
        selected_plan=None,
        addon_services=None,
        co_brother_opt_in=False,
        metadata_json={
            "domainName": "delta.example",
            "tld": "example",
            "period": 1,
            "minPeriodYears": 1,
            "price": 1000.0,
            "pricePerYear": 1000.0,
            "providerUnitPriceInr": 1000.0,
            "providerPeriodTotalInr": 1000.0,
            "isPremium": True,
            "registryTier": "premium",
        },
    )

    def _rate(service, _tld=None):
        if service == "premium_registration":
            return 0.25
        return 0.15

    with patch(
        "app.service.domain.domain_commission_config.get_rate",
        side_effect=_rate,
    ):
        cart = CartService(session=AsyncMock())
        response = await cart._build_item_response(item)

        checkout = CartCheckoutService(session=AsyncMock())
        line_total = await checkout._resolve_line_total(item, buyer=SimpleNamespace(id=uuid4()))

    assert response.base_price == 1000.0
    assert response.line_total == 1250.0
    assert line_total == 1250.0
    assert domain_price_breakdown(line_total, years=1)["totalInr"] == 1475.0
