"""Marketplace listing API keeps asking_price ex-GST and exposes buyer payable."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.model.marketplace.domain_listing_mapper import build_domain_listing_response
from app.utils.marketplace_enums import (
    DomainListingStatus,
    DomainListingVerificationStatus,
    SaleType,
)


def _listing(*, asking_price: float, commission_percentage: float = 15.0) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    payout = round(asking_price - asking_price * commission_percentage / 100.0, 2)
    return SimpleNamespace(
        id=uuid.uuid4(),
        domain_name="example",
        domain_extension=".com",
        domain_category=None,
        asking_price=asking_price,
        seller_price=payout,
        listing_price=asking_price,
        commission_percentage=commission_percentage,
        commission_amount=round(asking_price * commission_percentage / 100.0, 2),
        seller_payout_amount=payout,
        pricing_demand=None,
        domain_status=DomainListingStatus.AVAILABLE,
        logo=None,
        logo_text=None,
        status=True,
        views=0,
        payment_status=None,
        purchased_by_user_id=None,
        sold_at=None,
        verified=False,
        verification_method=None,
        verified_at=None,
        whois_email=None,
        verification_status=DomainListingVerificationStatus.PENDING,
        sale_type=SaleType.ONE_TIME,
        featured=False,
        admin_listed=False,
        taken_down=False,
        take_down_reason=None,
        created_at=now,
        updated_at=now,
        contact_info=None,
        agreement=None,
        listed_by=None,
        listed_by_user_id=uuid.uuid4(),
    )


def test_listing_response_keeps_asking_price_and_adds_inclusive_buyer_payable():
    listing = _listing(asking_price=10000.0, commission_percentage=15.0)
    with patch("app.model.marketplace.domain_listing_mapper.domain_price_breakdown") as mock_tax:
        mock_tax.return_value = {
            "subtotalInr": 10000.0,
            "gstInr": 1800.0,
            "totalInr": 11800.0,
            "gstRate": 18.0,
            "gstEnabled": True,
        }
        payload = build_domain_listing_response(listing)

    assert payload.asking_price == 10000.0
    assert payload.seller_payout_amount == 8500.0
    assert payload.commission_amount == 1500.0
    assert payload.gst_inr == 1800.0
    assert payload.buyer_payable_inr == 11800.0


def test_listing_response_commission_20_percent_does_not_change_buyer_price():
    listing = _listing(asking_price=10000.0, commission_percentage=20.0)
    with patch("app.model.marketplace.domain_listing_mapper.domain_price_breakdown") as mock_tax:
        mock_tax.return_value = {
            "subtotalInr": 10000.0,
            "gstInr": 1800.0,
            "totalInr": 11800.0,
            "gstRate": 18.0,
            "gstEnabled": True,
        }
        payload = build_domain_listing_response(listing)

    assert payload.asking_price == 10000.0
    assert payload.seller_payout_amount == 8000.0
    assert payload.commission_amount == 2000.0
    assert payload.buyer_payable_inr == 11800.0


def test_existing_listing_without_payout_snapshot_still_computes_gst_on_read():
    listing = _listing(asking_price=10000.0, commission_percentage=15.0)
    listing.seller_payout_amount = None
    listing.commission_amount = None
    stored_asking = listing.asking_price

    with patch("app.model.marketplace.domain_listing_mapper.domain_price_breakdown") as mock_tax:
        mock_tax.return_value = {
            "subtotalInr": 10000.0,
            "gstInr": 1800.0,
            "totalInr": 11800.0,
            "gstRate": 18.0,
            "gstEnabled": True,
        }
        payload = build_domain_listing_response(listing)

    assert listing.asking_price == stored_asking
    assert payload.asking_price == 10000.0
    assert payload.seller_payout_amount == 8500.0
    assert payload.commission_amount == 1500.0
    assert payload.buyer_payable_inr == 11800.0
    mock_tax.assert_called_once_with(10000.0, years=1)


def test_cart_razorpay_gst_and_seller_payout_use_listing_not_inclusive_price():
    """Cart charges L+GST; payout snapshot stays on pre-GST L. No double GST."""
    from app.utils.domain_gst import domain_price_breakdown
    from app.utils.listing_commission import compute_listing_commission

    listing_price = 10000.0
    with patch("app.utils.domain_gst.settings") as mock_settings:
        mock_settings.DOMAIN_GST_ENABLED = True
        mock_settings.DOMAIN_GST_RATE = 18.0
        mock_settings.DOMAIN_PRICE_GST_INCLUSIVE = False
        listing_tax = domain_price_breakdown(listing_price, years=1)

    assert listing_tax["subtotalInr"] == 10000.0
    assert listing_tax["gstInr"] == 1800.0
    assert listing_tax["totalInr"] == 11800.0

    payout_15, fee_15, stored_l_15 = compute_listing_commission(listing_price, 15)
    payout_20, fee_20, stored_l_20 = compute_listing_commission(listing_price, 20)

    assert stored_l_15 == listing_price
    assert stored_l_20 == listing_price
    assert payout_15 == 8500.0
    assert fee_15 == 1500.0
    assert payout_20 == 8000.0
    assert fee_20 == 2000.0
    assert listing_tax["totalInr"] == 11800.0
