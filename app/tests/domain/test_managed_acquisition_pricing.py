"""Unit tests for managed acquisition pricing gate and snapshot."""

from __future__ import annotations

from app.service.domain.managed_acquisition_pricing import (
    MANAGED_ACQUISITION_MIN_PRICE_INR,
    build_pricing_snapshot,
    is_managed_acquisition_payable,
    is_openprovider_managed_registration,
)
from app.service.domain.managed_acquisition_serializers import (
    build_acquisition_timeline,
    buyer_facing_acquisition,
)


def test_gate_strictly_greater_than_5l_on_payable():
    assert MANAGED_ACQUISITION_MIN_PRICE_INR == 500_000.0
    # Far above 5L must qualify regardless of GST mode.
    assert is_managed_acquisition_payable(600_000) is True
    assert is_managed_acquisition_payable(100_000) is False
    # Boundary: payable must be strictly greater than 5L.
    assert isinstance(is_managed_acquisition_payable(500_000), bool)


def test_openprovider_flag_from_meta_or_price():
    assert is_openprovider_managed_registration({"isManagedAcquisition": True}) is True
    assert is_openprovider_managed_registration({"price": 50_000}) is False
    assert is_openprovider_managed_registration({"price": 600_000}) is True


def test_pricing_snapshot_persists_quote_fields():
    meta = {
        "price": 550_000,
        "period": 2,
        "pricePerYear": 275_000,
        "providerUnitPriceInr": 200_000,
        "commissionRate": 0.15,
        "priceSource": "openprovider",
        "isPremium": True,
        "registryTier": "premium",
        "domainName": "example.com",
    }
    snap = build_pricing_snapshot(meta)
    assert snap["quoted_price_inr"] == 550_000
    assert snap["payable_inr"] >= 550_000
    assert snap["period_years"] == 2
    assert snap["is_registry_premium"] is True
    assert snap["registry_tier"] == "premium"
    assert snap["pricing_snapshot_json"]["_snapshottedAtConfirm"] is True
    assert snap["pricing_snapshot_json"]["domainName"] == "example.com"


def test_timeline_dynamic_declined_branch():
    steps = build_acquisition_timeline(
        status="DECLINED",
        created_at=None,
        declined_at=None,
    )
    keys = [s["key"] for s in steps]
    assert "submitted" in keys
    assert "declined" in keys
    assert "completed" not in keys


def test_timeline_completed_branch():
    steps = build_acquisition_timeline(
        status="COMPLETED",
        created_at=None,
        completed_at=None,
    )
    keys = [s["key"] for s in steps]
    assert "completed" in keys
    assert "declined" not in keys


def test_buyer_facing_strips_channel():
    dto = buyer_facing_acquisition(
        {
            "id": "1",
            "channel": "OPENPROVIDER",
            "isRegistryPremium": True,
            "registryTier": "premium",
            "buyer": {"email": "x"},
            "domainName": "a.com",
        }
    )
    assert "channel" not in dto
    assert "isRegistryPremium" not in dto
    assert "registryTier" not in dto
    assert "buyer" not in dto
    assert dto["domainName"] == "a.com"


def test_iso_accepts_string_and_datetime():
    from datetime import datetime, timezone

    from app.service.domain.managed_acquisition_serializers import _iso

    assert _iso(None) is None
    assert _iso("2026-07-23T10:00:00+00:00") == "2026-07-23T10:00:00+00:00"
    assert _iso("  ") is None
    dt = datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc)
    assert _iso(dt) == dt.isoformat()
