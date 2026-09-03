"""Registry premium availability must match OpenProvider status semantics."""

from app.integrations.openprovider.client import is_free, extract_is_premium


def test_is_free_registry_premium_free_status() -> None:
    """Available registry/aftermarket premiums return status=free from OpenProvider."""
    result = {
        "domain": "red.shop",
        "status": "free",
        "reason": "premium",
        "is_premium": True,
        "premium": {"price": {"create": 2500}},
        "price": {
            "product": {"price": 2500, "currency": "USD"},
            "reseller": {"price": 252618.89, "currency": "INR"},
        },
    }
    assert extract_is_premium(result) is True
    assert is_free(result) is True


def test_is_free_active_premium_with_create_price_is_taken() -> None:
    """status=active + premium create price still means taken (hustler.online/club pattern)."""
    result_online = {
        "domain": "hustler.online",
        "status": "active",
        "reason": "registry reserved",
        "is_premium": True,
        "premium": {"price": {"create": 1250}},
        "price": {
            "product": {"price": 1250, "currency": "USD"},
            "reseller": {"price": 124848.24, "currency": "INR"},
        },
    }
    assert is_free(result_online) is False

    result_club = {
        "domain": "hustler.club",
        "status": "active",
        "reason": "In use",
        "is_premium": True,
        "premium": {"price": {"create": 3125}},
        "price": {
            "product": {"price": 3125, "currency": "USD"},
            "reseller": {"price": 312120.6, "currency": "INR"},
        },
    }
    assert is_free(result_club) is False


def test_is_free_aftermarket_premium_free_status() -> None:
    result = {
        "domain": "batterify.com",
        "status": "free",
        "is_premium": True,
        "premium": {"price": {"create": 3000000}, "currency": "USD"},
        "price": {
            "product": {"price": 3000000, "currency": "USD"},
            "reseller": {"price": 303142669.47, "currency": "INR"},
        },
    }
    assert is_free(result) is True


def test_is_free_taken_standard_domain() -> None:
    result = {
        "domain": "google.com",
        "status": "active",
        "reason": "Domain exists",
        "price": {
            "product": {"price": 10.46, "currency": "USD"},
            "reseller": {"price": 1056.96, "currency": "INR"},
        },
    }
    assert extract_is_premium(result) is False
    assert is_free(result) is False


def test_is_free_standard_available() -> None:
    result = {
        "domain": "example-free-name.com",
        "status": "free",
        "price": {"reseller": {"price": 1056.96, "currency": "INR"}},
    }
    assert is_free(result) is True


def test_is_free_taken_premium_no_create_price() -> None:
    """
    OpenProvider returns status=active + is_premium=true WITH a non-zero reseller
    price (standard TLD pricing) but WITHOUT a premium.price.create price,
    because the domain is already registered.
    """
    result_online = {
        "domain": "hustler.online",
        "status": "active",
        "reason": "Domain exists",
        "is_premium": True,
        "price": {
            "product": {"price": 13.5, "currency": "USD"},
            "reseller": {"price": 1362.85, "currency": "INR"},
        },
    }
    assert is_free(result_online) is False

    result_club = {
        "domain": "hustler.club",
        "status": "active",
        "reason": "Domain exists",
        "is_premium": True,
        "premium": {"price": {"create": 0}},
        "price": {
            "product": {"price": 3200, "currency": "USD"},
            "reseller": {"price": 323200.0, "currency": "INR"},
        },
    }
    assert is_free(result_club) is False


def test_is_free_taken_with_registered_status() -> None:
    """Domains with status=registered are always taken regardless of premium flag."""
    result = {
        "domain": "taken-premium.club",
        "status": "registered",
        "is_premium": True,
        "premium": {"price": {"create": 50000}},
        "price": {"reseller": {"price": 5000000, "currency": "INR"}},
    }
    assert is_free(result) is False
