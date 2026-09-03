from app.utils.listing_commission import compute_listing_commission
from app.utils.domain_gst import domain_price_breakdown


def test_listing_commission_deducts_from_sale_price_examples():
    assert compute_listing_commission(1000, 15) == (850, 150, 1000)
    assert compute_listing_commission(5000, 15) == (4250, 750, 5000)
    assert compute_listing_commission(10000, 15) == (8500, 1500, 10000)


def test_listing_commission_uses_configured_percent_not_hardcoded():
    assert compute_listing_commission(10000, 20) == (8000, 2000, 10000)
    assert compute_listing_commission(10000, 10) == (9000, 1000, 10000)


def test_marketplace_buyer_payable_example_10000_at_18_percent_gst():
    from unittest.mock import patch

    with patch("app.utils.domain_gst.settings") as mock_settings:
        mock_settings.DOMAIN_GST_ENABLED = True
        mock_settings.DOMAIN_GST_RATE = 18.0
        mock_settings.DOMAIN_PRICE_GST_INCLUSIVE = False
        tax = domain_price_breakdown(10000.0, years=1)

    payout, commission, listing = compute_listing_commission(10000, 15)
    assert listing == 10000
    assert commission == 1500
    assert payout == 8500
    assert tax["subtotalInr"] == 10000.0
    assert tax["gstInr"] == 1800.0
    assert tax["totalInr"] == 11800.0
