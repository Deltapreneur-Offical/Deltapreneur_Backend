"""Unit tests for domain registration GST breakdown."""

from __future__ import annotations

from unittest.mock import patch

from app.utils.domain_gst import domain_price_breakdown, order_gst_payload


def test_domain_price_breakdown_marketplace_10000_example():
    with patch("app.utils.domain_gst.settings") as mock_settings:
        mock_settings.DOMAIN_GST_ENABLED = True
        mock_settings.DOMAIN_GST_RATE = 18.0
        mock_settings.DOMAIN_PRICE_GST_INCLUSIVE = False

        result = domain_price_breakdown(10000.0, years=1)

    assert result["subtotalInr"] == 10000.0
    assert result["gstInr"] == 1800.0
    assert result["totalInr"] == 11800.0


def test_domain_price_breakdown_exclusive_18_percent():
    with patch("app.utils.domain_gst.settings") as mock_settings:
        mock_settings.DOMAIN_GST_ENABLED = True
        mock_settings.DOMAIN_GST_RATE = 18.0
        mock_settings.DOMAIN_PRICE_GST_INCLUSIVE = False

        result = domain_price_breakdown(799.0, years=1)

    assert result["subtotalInr"] == 799.0
    assert result["gstInr"] == 143.82
    assert result["totalInr"] == 942.82
    assert result["gstEnabled"] is True
    assert result["gstRate"] == 18.0


def test_domain_price_breakdown_multi_year():
    with patch("app.utils.domain_gst.settings") as mock_settings:
        mock_settings.DOMAIN_GST_ENABLED = True
        mock_settings.DOMAIN_GST_RATE = 18.0
        mock_settings.DOMAIN_PRICE_GST_INCLUSIVE = False

        result = domain_price_breakdown(100.0, years=2)

    assert result["subtotalInr"] == 200.0
    assert result["gstInr"] == 36.0
    assert result["totalInr"] == 236.0


def test_domain_price_breakdown_disabled():
    with patch("app.utils.domain_gst.settings") as mock_settings:
        mock_settings.DOMAIN_GST_ENABLED = False
        mock_settings.DOMAIN_GST_RATE = 18.0
        mock_settings.DOMAIN_PRICE_GST_INCLUSIVE = False

        result = domain_price_breakdown(799.0, years=1)

    assert result["subtotalInr"] == 799.0
    assert result["gstInr"] == 0.0
    assert result["totalInr"] == 799.0
    assert result["gstEnabled"] is False


def test_order_gst_payload_from_order_row():
    class _Order:
        price_inr = 942.82
        subtotal_inr = 799.0
        gst_inr = 143.82

    with patch("app.utils.domain_gst.settings") as mock_settings:
        mock_settings.DOMAIN_GST_RATE = 18.0
        mock_settings.COBROTHER_GSTIN = "27AAAAA0000A1Z5"

        payload = order_gst_payload(_Order())

    assert payload["priceInr"] == 942.82
    assert payload["subtotalInr"] == 799.0
    assert payload["gstInr"] == 143.82
    assert payload["gstEnabled"] is True
    assert payload["cobrotherGstin"] == "27AAAAA0000A1Z5"


def test_order_gst_payload_legacy_row_without_columns():
    class _Order:
        price_inr = 799.0
        subtotal_inr = None
        gst_inr = None

    payload = order_gst_payload(_Order())

    assert payload["priceInr"] == 799.0
    assert payload["subtotalInr"] == 799.0
    assert payload["gstInr"] == 0.0
    assert payload["gstEnabled"] is False
