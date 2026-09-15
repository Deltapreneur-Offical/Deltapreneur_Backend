"""Guards: customer cards show GST-inclusive totals; cart units stay ex-GST."""

from __future__ import annotations

from unittest.mock import patch

from app.service.domain.domain_registration_service import (
    _attach_tld_item_gst_fields,
    _registration_pricing_fields,
    _renewal_customer_pricing,
)


def test_registration_pricing_fields_575_card_total_keeps_ex_gst_unit():
    with patch("app.utils.domain_gst.settings") as mock_settings:
        mock_settings.DOMAIN_GST_ENABLED = True
        mock_settings.DOMAIN_GST_RATE = 18.0
        mock_settings.DOMAIN_PRICE_GST_INCLUSIVE = False

        fields = _registration_pricing_fields(575.0, years=1)

    assert fields["unitPrice"] == 575.0
    assert fields["subtotalInr"] == 575.0
    assert fields["gstInr"] == 103.5
    assert fields["totalInr"] == 678.5
    assert fields["price"] == 678.5
    assert fields["gstEnabled"] is True


def test_attach_tld_item_keeps_wholesale_renewal_and_ex_gst_registration():
    item = {
        "tld": ".in",
        "registrationPrice": 575.0,
        "renewalPrice": 500.0,
    }
    with (
        patch("app.utils.domain_gst.settings") as mock_settings,
        patch(
            "app.service.domain.domain_commission_config.get_rate",
            return_value=0.15,
        ),
    ):
        mock_settings.DOMAIN_GST_ENABLED = True
        mock_settings.DOMAIN_GST_RATE = 18.0
        mock_settings.DOMAIN_PRICE_GST_INCLUSIVE = False
        _attach_tld_item_gst_fields(item)

    assert item["registrationPrice"] == 575.0
    assert item["totalInr"] == 678.5
    assert item["gstInr"] == 103.5
    assert item["renewalPrice"] == 500.0
    assert item["renewalTotalInr"] == 678.5


def test_renewal_customer_pricing_applies_commission_then_gst():
    with (
        patch("app.utils.domain_gst.settings") as mock_settings,
        patch(
            "app.service.domain.domain_commission_config.get_rate",
            return_value=0.15,
        ),
    ):
        mock_settings.DOMAIN_GST_ENABLED = True
        mock_settings.DOMAIN_GST_RATE = 18.0
        mock_settings.DOMAIN_PRICE_GST_INCLUSIVE = False
        unit, total = _renewal_customer_pricing(500.0, "in")

    assert unit == 575.0
    assert total == 678.5


def test_attach_tld_item_gst_off_matches_unit():
    item = {
        "tld": ".in",
        "registrationPrice": 575.0,
        "renewalPrice": 500.0,
    }
    with (
        patch("app.utils.domain_gst.settings") as mock_settings,
        patch(
            "app.service.domain.domain_commission_config.get_rate",
            return_value=0.0,
        ),
    ):
        mock_settings.DOMAIN_GST_ENABLED = False
        mock_settings.DOMAIN_GST_RATE = 18.0
        mock_settings.DOMAIN_PRICE_GST_INCLUSIVE = False
        _attach_tld_item_gst_fields(item)

    assert item["registrationPrice"] == 575.0
    assert item["totalInr"] == 575.0
    assert item["gstEnabled"] is False
    assert item["renewalPrice"] == 500.0
    assert item["renewalTotalInr"] == 500.0
