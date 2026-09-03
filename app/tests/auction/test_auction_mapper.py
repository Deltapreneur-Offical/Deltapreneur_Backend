"""Unit tests for auction API mappers."""

from __future__ import annotations

from types import SimpleNamespace

from app.model.auction.auction_mapper import domain_summary_from_listing


def test_domain_summary_from_listing_includes_resolved_logo():
    listing = SimpleNamespace(
        id="11111111-1111-4111-8111-111111111111",
        domain_name="chrisbadwa",
        domain_extension=".com",
        pricing_demand=None,
        logo="domain-logos/chrisbadwa.png",
        verified=True,
        listed_by=None,
    )

    payload = domain_summary_from_listing(listing)

    assert payload["fullDomain"] == "chrisbadwa.com"
    assert payload["logo"] is not None
    assert "chrisbadwa.png" in payload["logo"]
    assert "description" not in payload


def test_domain_summary_from_listing_does_not_map_pricing_to_description():
    pricing = SimpleNamespace(value="NEGOTIABLE")
    listing = SimpleNamespace(
        id="11111111-1111-4111-8111-111111111111",
        domain_name="example",
        domain_extension=".com",
        pricing_demand=pricing,
        logo=None,
        verified=False,
        listed_by=None,
    )

    payload = domain_summary_from_listing(listing)

    assert payload["pricingDemand"] == "NEGOTIABLE"
    assert "description" not in payload
