"""Unit tests for Razorpay domain recovery helpers (no DB)."""

from __future__ import annotations

from app.service.platform.track_record_service import (
    domain_display_from_item_name,
    extract_domains_from_razorpay_payload,
)


def test_extract_domain_from_cart_items_note():
    domains = extract_domains_from_razorpay_payload(
        pay={"notes": {}, "email": "buyer@gmail.com"},
        order={
            "notes": {
                "items": "Domain Registration: neeligin.com",
                "categories": "Domain Registration",
                "buyerEmail": "buyer@gmail.com",
            },
            "description": "Domain Registration — neeligin.com",
        },
    )
    assert "neeligin.com" in domains
    assert "gmail.com" not in domains


def test_extract_multiple_domains_from_items_summary():
    domains = extract_domains_from_razorpay_payload(
        pay={
            "notes": {
                "items": "foo.com, bar.co.in (+1 more)",
            }
        },
        order=None,
    )
    assert "foo.com" in domains
    assert "bar.co.in" in domains


def test_domain_display_ignores_payment_placeholder():
    assert domain_display_from_item_name("Payment #pay_TM3oRxO3JS4ERk") is None
    assert domain_display_from_item_name("neeligin.com") == "neeligin.com"
