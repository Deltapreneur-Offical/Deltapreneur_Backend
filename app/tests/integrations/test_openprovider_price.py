"""OpenProvider price extraction from domains/check responses."""

from app.integrations.openprovider.client import (
    extract_create_price_details,
    extract_reseller_price,
    extract_reseller_price_details,
    resolve_registration_period,
    tld_min_registration_years,
    yearly_create_price_from_check,
)


def test_extract_reseller_price_prefers_reseller_block() -> None:
    result = {
        "status": "free",
        "price": {
            "product": {"currency": "USD", "price": 8.57},
            "reseller": {"currency": "INR", "price": 799.0},
        },
    }
    assert extract_reseller_price(result) == 799.0
    unit, currency = extract_reseller_price_details(result)
    assert unit == 799.0
    assert currency == "INR"


def test_extract_reseller_price_falls_back_to_product() -> None:
    result = {
        "status": "free",
        "price": {"product": {"currency": "USD", "price": 12.5}},
    }
    assert extract_reseller_price(result) == 12.5


def test_extract_create_price_panel_inr_uplift(monkeypatch) -> None:
    from app.core.config import settings
    monkeypatch.setattr(settings, "OPENPROVIDER_PANEL_INR_FACTOR", 1.114074)
    quote = {
        "price": {
            "product": {"currency": "USD", "price": 8.29},
            "reseller": {"currency": "INR", "price": 675.02},
        },
        "is_promotion": True,
    }
    unit, currency, source = extract_create_price_details(quote)
    assert currency == "INR"
    assert unit == 752.0
    assert source == "openprovider_panel_inr"


def test_extract_create_price_no_uplift_when_factor_one(monkeypatch) -> None:
    from app.core.config import settings
    monkeypatch.setattr(settings, "OPENPROVIDER_PANEL_INR_FACTOR", 1.0)
    quote = {
        "price": {
            "product": {"currency": "USD", "price": 8.29},
            "reseller": {"currency": "INR", "price": 675.02},
        },
        "is_promotion": True,
    }
    unit, currency, source = extract_create_price_details(quote)
    assert currency == "INR"
    assert unit == 675.02
    assert source == "openprovider_prices"


def test_extract_reseller_price_premium_prefers_reseller() -> None:
    """OP support: reseller is billable base; is_premium is an independent flag."""
    result = {
        "status": "free",
        "is_premium": True,
        "premium": {"price": {"create": 25000.0}},
        "price": {
            "product": {"price": 2500.0, "currency": "USD"},
            "reseller": {"price": 2500.0, "currency": "USD"},
        },
    }
    assert extract_reseller_price(result) == 2500.0
    unit, currency = extract_reseller_price_details(result)
    assert unit == 2500.0
    assert currency == "USD"


def test_extract_reseller_price_premium_fallback_without_reseller() -> None:
    result = {
        "status": "free",
        "is_premium": True,
        "premium": {"price": {"create": 25000.0}},
    }
    assert extract_reseller_price(result) == 25000.0


def test_extract_is_premium() -> None:
    from app.integrations.openprovider.client import extract_is_premium

    assert extract_is_premium({"is_premium": True}) is True
    assert extract_is_premium({"is_premium": False}) is False
    assert extract_is_premium({}) is False
    assert extract_is_premium(None) is False


def test_yearly_create_price_from_check_normalizes_ai_min_period() -> None:
    assert tld_min_registration_years("ai") == 2
    assert tld_min_registration_years("com") == 1
    assert resolve_registration_period(1, "ai") == 2
    assert resolve_registration_period(1, "com") == 1
    # Live OP check for .ai returns the 2-year total; storefront needs 1-year unit.
    assert yearly_create_price_from_check(16167.61, "ai") == 8083.81
    assert yearly_create_price_from_check(8083.8, "com") == 8083.8


def test_parse_tld_min_period_from_api_payload() -> None:
    from app.integrations.openprovider import client as op

    assert op._parse_tld_min_period({"min_period": 2}) == 2
    assert op._parse_tld_min_period({"minPeriod": 5}) == 5
    assert op._parse_tld_min_period({"min_period": 0}) is None
    assert op._parse_tld_min_period({}) is None
    assert op._parse_tld_min_period(None) is None


def test_tld_min_registration_years_prefers_api_cache(monkeypatch) -> None:
    from app.integrations.openprovider import client as op

    monkeypatch.setitem(op._TLD_MIN_PERIOD_CACHE, "io", 2)
    assert op.tld_min_registration_years("io") == 2
    assert op.resolve_registration_period(1, "io") == 2
    op._TLD_MIN_PERIOD_CACHE.pop("io", None)