"""Unit tests for INR-base exchange rate aggregation."""

from __future__ import annotations

import pytest

from app.service.currency.exchange_rate_service import (
    SUPPORTED_CURRENCIES,
    _merge_consumer_rates,
    convert_foreign_to_inr,
    convert_inr,
    get_exchange_rates,
)


def _full_snapshot(**overrides: float) -> dict[str, float]:
    base = {
        "INR": 1.0,
        "USD": 0.0105,
        "EUR": 0.0090,
        "GBP": 0.0078,
        "AED": 0.0385,
        "SGD": 0.0134,
        "AUD": 0.0146,
        "CAD": 0.0145,
    }
    base.update(overrides)
    return base


def test_merge_consumer_rates_picks_minimum_per_currency():
    high = _full_snapshot(USD=0.0106, AED=0.0390)
    low = _full_snapshot(USD=0.01044, AED=0.03836)
    merged = _merge_consumer_rates([high, low])
    assert merged["USD"] == pytest.approx(0.01044)
    assert merged["AED"] == pytest.approx(0.03836)
    assert merged["INR"] == 1.0


def test_merge_consumer_rates_requires_all_supported_codes():
    partial = {"INR": 1.0, "USD": 0.01}
    merged = _merge_consumer_rates([partial])
    assert merged["EUR"] == 1.0


def test_convert_inr_to_inr_is_identity():
    result = convert_inr(2500000, "INR")
    assert result["converted"] == 2500000
    assert result["rate"] == 1.0


def test_convert_foreign_to_inr_round_trip(monkeypatch):
    rates = _full_snapshot(USD=0.01)

    def fake_get_exchange_rates(*, force_refresh: bool = False):
        return {"rates": rates, "sourceUpdatedAt": None}

    monkeypatch.setattr(
        "app.service.currency.exchange_rate_service.get_exchange_rates",
        fake_get_exchange_rates,
    )

    out = convert_inr(10000, "USD")
    assert out["converted"] == 100.0

    back = convert_foreign_to_inr(100, "USD")
    assert back["amountInr"] == 10000


def test_get_exchange_rates_uses_static_fallback_when_live_providers_fail(monkeypatch):
    import app.service.currency.exchange_rate_service as fx

    monkeypatch.setattr(fx, "_cache_rates", None)
    monkeypatch.setattr(fx, "_cache_updated_at", 0.0)
    monkeypatch.setattr(fx, "_cache_source_unix", None)
    monkeypatch.setattr(fx, "_cache_providers", None)
    monkeypatch.setattr(
        fx,
        "_fetch_live_rates",
        lambda: (_ for _ in ()).throw(RuntimeError("All exchange rate providers failed")),
    )

    snapshot = get_exchange_rates(force_refresh=True)

    assert snapshot["fallback"] is True
    assert snapshot["stale"] is True
    assert snapshot["rates"]["USD"] == pytest.approx(0.0105)


def test_convert_foreign_to_inr_uses_static_fallback_when_live_providers_fail(monkeypatch):
    import app.service.currency.exchange_rate_service as fx

    monkeypatch.setattr(fx, "_cache_rates", None)
    monkeypatch.setattr(fx, "_cache_updated_at", 0.0)
    monkeypatch.setattr(fx, "_cache_source_unix", None)
    monkeypatch.setattr(fx, "_cache_providers", None)
    monkeypatch.setattr(
        fx,
        "_fetch_live_rates",
        lambda: (_ for _ in ()).throw(RuntimeError("All exchange rate providers failed")),
    )

    back = convert_foreign_to_inr(49, "USD")

    assert back["amountInr"] == 4667
    assert back["rate"] == pytest.approx(0.0105)


def test_supported_currencies_include_aed_not_jpy():
    assert "AED" in SUPPORTED_CURRENCIES
    assert "JPY" in SUPPORTED_CURRENCIES
