"""Display-only storefront price cache. Checkout still uses live quotes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.service.domain import domain_registration_service as svc


@pytest.fixture(autouse=True)
def _clear_prices_cache():
    svc.clear_storefront_prices_cache()
    yield
    svc.clear_storefront_prices_cache()


def test_storefront_cache_ttl_zero_skips_put():
    svc._storefront_prices_cache_put("k", {"registration": {"unitInr": 799}}, 0)
    assert svc._storefront_prices_cache_get("k") is None


def test_storefront_cache_returns_copy_and_expires():
    payload = {"registration": {"byTld": {".com": 799.0}, "unitInr": 799.0}}
    svc._storefront_prices_cache_put("k", payload, 180)
    first = svc._storefront_prices_cache_get("k")
    assert first == payload
    first["registration"]["unitInr"] = 1
    second = svc._storefront_prices_cache_get("k")
    assert second["registration"]["unitInr"] == 799.0

    svc._storefront_prices_cache["k"] = (0.0, payload)
    assert svc._storefront_prices_cache_get("k") is None


def test_clear_tld_search_cache_also_clears_storefront_prices():
    svc._storefront_prices_cache_put("k", {"email": {"unitInr": 100}}, 180)
    svc.clear_tld_search_cache()
    assert svc._storefront_prices_cache_get("k") is None


def test_storefront_cache_key_includes_gst_flags():
    with patch("app.service.domain.domain_registration_service.settings") as mock_settings:
        mock_settings.DOMAIN_GST_ENABLED = True
        mock_settings.DOMAIN_GST_RATE = 18.0
        mock_settings.DOMAIN_PRICE_GST_INCLUSIVE = False
        key_a = svc._storefront_prices_cache_key()
        mock_settings.DOMAIN_GST_RATE = 5.0
        key_b = svc._storefront_prices_cache_key()
    assert key_a != key_b
    assert "18.0" in key_a or "18" in key_a
    assert "5.0" in key_b or "5" in key_b


@pytest.mark.asyncio
async def test_get_service_prices_serves_cached_catalog_without_second_ssl_fetch():
    ssl_calls = {"n": 0}

    async def fake_ssl(self, _apply):
        ssl_calls["n"] += 1
        return {"standard": {"unitInr": 1100.0}, "label": "SSL"}

    fake_reg = MagicMock()
    fake_reg.is_configured.return_value = False

    with (
        patch("app.integrations.domain_registrar.active_registrar", return_value=fake_reg),
        patch.object(svc.DomainRegistrationService, "_build_live_ssl_price_block", fake_ssl),
        patch("app.service.domain.domain_registration_service.settings") as mock_settings,
    ):
        mock_settings.DOMAIN_GST_ENABLED = True
        mock_settings.DOMAIN_GST_RATE = 18.0
        mock_settings.DOMAIN_PRICE_GST_INCLUSIVE = False
        mock_settings.STOREFRONT_PRICES_CACHE_TTL_SECONDS = 180.0
        mock_settings.DOMAIN_STOREFRONT_RENEWAL_FALLBACK_UNIT_INR = 100.0

        service = svc.DomainRegistrationService(AsyncMock())
        first = await service.get_service_prices()
        second = await service.get_service_prices()

    assert ssl_calls["n"] == 1
    assert first["registration"]["byTld"][".com"] == second["registration"]["byTld"][".com"]
    assert first["registration"]["byTldInclusive"]
    assert first["email"]["unitInr"] == second["email"]["unitInr"]
    assert "ssl" in first
    first["registration"]["unitInr"] = 1
    assert second["registration"]["unitInr"] != 1
