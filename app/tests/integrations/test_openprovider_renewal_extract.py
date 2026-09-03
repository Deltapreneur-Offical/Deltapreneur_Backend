"""Renewal price extraction must never reuse registration/create pricing."""

from app.integrations.openprovider.client import (
    extract_getprice_renewal_details,
    extract_renewal_price_details,
    extract_reseller_price_details,
)


def test_extract_renewal_from_check_does_not_use_reseller_price() -> None:
    """domains/check embeds registration in price.reseller.price — not renewal."""
    check = {
        "status": "free",
        "is_premium": True,
        "premium": {"price": {"create": 1999}},
        "price": {
            "reseller": {"price": 199657.31, "currency": "INR"},
            "product": {"price": 1999, "currency": "USD"},
        },
    }
    assert extract_renewal_price_details(check) == (None, "INR")
    # Must not treat registration reseller price as renewal.
    assert extract_reseller_price_details(check)[0] == 199657.31


def test_extract_getprice_renewal_uses_renew_operation_price() -> None:
    """GetPrice(operation=renew) exposes renewal in price.reseller.price."""
    renew_quote = {
        "is_premium": False,
        "price": {
            "product": {"price": 11.2, "currency": "USD"},
            "reseller": {"price": 1118.64, "currency": "INR"},
        },
    }
    unit, currency = extract_getprice_renewal_details(renew_quote)
    assert unit == 1118.64
    assert currency == "INR"


def test_extract_getprice_renewal_prefers_explicit_renew_key() -> None:
    quote = {
        "price": {
            "reseller": {"price": 999.0, "renew": 1118.64, "currency": "INR"},
        },
    }
    unit, currency = extract_getprice_renewal_details(quote)
    assert unit == 1118.64
    assert currency == "INR"


def test_extract_getprice_renewal_never_falls_back_to_premium_create() -> None:
    """GetPrice renew quotes must not read premium.price.create."""
    renew_quote = {
        "is_premium": True,
        "premium": {"price": {"create": 312120.6}},
        "price": {
            "reseller": {"price": 1897.69, "currency": "INR"},
        },
    }
    unit, currency = extract_getprice_renewal_details(renew_quote)
    assert unit == 1897.69
    assert currency == "INR"
