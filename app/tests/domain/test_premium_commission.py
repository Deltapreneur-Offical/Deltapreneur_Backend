"""Tests for calculate_customer_price and premium commission separation."""

from app.service.domain.domain_commission_config import (
    CommissionService,
    apply_markup,
    calculate_customer_price,
    registration_service_for_premium,
)


def test_registration_service_for_premium():
    assert registration_service_for_premium(True) == CommissionService.PREMIUM_REGISTRATION
    assert registration_service_for_premium(False) == CommissionService.REGISTRATION


def test_calculate_customer_price_standard_vs_premium(monkeypatch):
    rates = {
        CommissionService.REGISTRATION: 0.10,
        CommissionService.PREMIUM_REGISTRATION: 0.05,
    }

    def fake_get_rate(service, tld=None):
        return rates[service]

    monkeypatch.setattr(
        "app.service.domain.domain_commission_config.get_rate",
        fake_get_rate,
    )

    standard = calculate_customer_price(
        1000.0,
        is_premium=False,
        service=CommissionService.REGISTRATION,
        currency="INR",
        tld="com",
    )
    premium = calculate_customer_price(
        1000.0,
        is_premium=True,
        service=CommissionService.REGISTRATION,
        currency="INR",
        tld="com",
    )

    assert standard["customerUnitInr"] == apply_markup(1000.0, 0.10)
    assert premium["customerUnitInr"] == apply_markup(1000.0, 0.05)
    assert standard["registryTier"] == "standard"
    assert premium["registryTier"] == "premium"
    assert standard["commissionService"] == CommissionService.REGISTRATION
    assert premium["commissionService"] == CommissionService.PREMIUM_REGISTRATION
