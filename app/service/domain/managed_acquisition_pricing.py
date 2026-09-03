"""Shared pricing gate for managed domain acquisitions (> ₹5L payable)."""

from __future__ import annotations

from typing import Any

from app.utils.domain_gst import domain_price_breakdown

# Strictly greater than ₹5L (align with marketplace premium gate).
MANAGED_ACQUISITION_MIN_PRICE_INR = 500_000.0


def registration_payable_inr(quoted_price_inr: float) -> dict[str, Any]:
    """GST-inclusive payable for a DOMAIN_REGISTRATION line (price already period-total)."""
    return domain_price_breakdown(float(quoted_price_inr or 0), years=1)


def is_managed_acquisition_payable(quoted_price_inr: float) -> bool:
    payable = float(registration_payable_inr(quoted_price_inr)["totalInr"])
    return payable > MANAGED_ACQUISITION_MIN_PRICE_INR


def is_openprovider_managed_registration(metadata: dict[str, Any] | None) -> bool:
    """True when DOMAIN_REGISTRATION cart meta payable exceeds ₹5L."""
    meta = metadata or {}
    if meta.get("isManagedAcquisition") is True:
        return True
    try:
        price = float(meta.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    return is_managed_acquisition_payable(price)


def build_pricing_snapshot(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Persist full quote used at submit — do not re-read OpenProvider later."""
    meta = dict(metadata or {})
    try:
        quoted = float(meta.get("price") or 0)
    except (TypeError, ValueError):
        quoted = 0.0
    breakdown = registration_payable_inr(quoted)
    try:
        price_per_year = float(meta.get("pricePerYear") or 0) or None
    except (TypeError, ValueError):
        price_per_year = None
    try:
        provider_unit = float(meta.get("providerUnitPriceInr") or 0) or None
    except (TypeError, ValueError):
        provider_unit = None
    try:
        commission = float(meta.get("commissionRate") or 0) or None
    except (TypeError, ValueError):
        commission = None

    is_premium = bool(meta.get("isPremium") or meta.get("registryTier") == "premium")
    registry_tier = str(meta.get("registryTier") or ("premium" if is_premium else "standard"))

    return {
        "quoted_price_inr": quoted,
        "payable_inr": float(breakdown["totalInr"]),
        "gst_inr": float(breakdown.get("gstInr") or 0),
        "gst_rate": breakdown.get("gstRate"),
        "price_per_year_inr": price_per_year,
        "provider_unit_price_inr": provider_unit,
        "commission_rate": commission,
        "price_source": meta.get("priceSource"),
        "registry_tier": registry_tier,
        "is_registry_premium": is_premium,
        "period_years": max(1, int(meta.get("period") or 1)),
        "pricing_snapshot_json": {
            **meta,
            "_payableBreakdown": breakdown,
            "_snapshottedAtConfirm": True,
        },
    }
