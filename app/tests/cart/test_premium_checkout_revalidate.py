"""Checkout must fail when premium GetPrice cannot be verified."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppException
from app.service.cart.cart_checkout_service import CartCheckoutService


@pytest.mark.asyncio
async def test_revalidate_fails_hard_when_premium_get_price_fails():
    item = SimpleNamespace(
        product_id="x",
        metadata_json={
            "domainName": "red.shop",
            "tld": "shop",
            "period": 1,
            "minPeriodYears": 1,
            "price": 999.0,
            "pricePerYear": 999.0,
            "isPremium": False,  # stale cart hint — must not be trusted
        },
    )
    item.metadata_json = dict(item.metadata_json)

    check = SimpleNamespace(status="available", isPremium=True)
    svc = MagicMock()
    svc.check_registration_domain = AsyncMock(return_value=check)
    svc.quote_registration_period_price = AsyncMock(
        side_effect=AppException(
            "Unable to verify the latest premium domain price. Please try again.",
            status_code=502,
        )
    )

    checkout = CartCheckoutService(session=AsyncMock())
    checkout._repo = MagicMock()
    checkout._repo.save = AsyncMock()

    with patch(
        "app.service.domain.domain_registration_service.DomainRegistrationService",
        return_value=svc,
    ):
        with pytest.raises(AppException) as exc:
            await checkout._revalidate_domain_registration_items([item])

    assert "premium domain price" in str(exc.value.message).lower()
    assert exc.value.status_code == 502
    # Must not keep charging the stale cart price.
    assert item.metadata_json.get("price") == 999.0
