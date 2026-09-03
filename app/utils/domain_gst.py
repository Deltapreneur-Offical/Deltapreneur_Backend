"""GST breakdown for domain registration storefront checkout."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.utils.money import round_money


def domain_gst_enabled() -> bool:
    return bool(settings.DOMAIN_GST_ENABLED) and float(settings.DOMAIN_GST_RATE) > 0


def domain_price_breakdown(
    unit_base_inr: float,
    *,
    years: int = 1,
) -> dict[str, Any]:
    """Return subtotal, GST, and total for a registration quote or order."""
    years = max(1, int(years))
    subtotal = round_money(float(unit_base_inr) * years)
    if not domain_gst_enabled():
        return {
            "subtotalInr": subtotal,
            "gstInr": 0.0,
            "totalInr": subtotal,
            "gstRate": None,
            "gstEnabled": False,
        }

    rate = float(settings.DOMAIN_GST_RATE)
    if settings.DOMAIN_PRICE_GST_INCLUSIVE:
        total = subtotal
        gst = round_money(total - total / (1 + rate / 100))
        subtotal = round_money(total - gst)
    else:
        gst = round_money(subtotal * rate / 100)
        total = round_money(subtotal + gst)

    return {
        "subtotalInr": subtotal,
        "gstInr": gst,
        "totalInr": total,
        "gstRate": rate,
        "gstEnabled": True,
    }


def order_gst_payload(order: Any) -> dict[str, Any]:
    """Serialize GST fields from a DomainRegistrationOrder row."""
    subtotal = getattr(order, "subtotal_inr", None)
    gst = getattr(order, "gst_inr", None)
    price_inr = float(getattr(order, "price_inr", 0) or 0)
    if subtotal is None:
        subtotal = price_inr
        gst = 0.0
    gst_val = float(gst if gst is not None else 0.0)
    return {
        "priceInr": price_inr,
        "subtotalInr": float(subtotal),
        "gstInr": gst_val,
        "gstRate": float(settings.DOMAIN_GST_RATE) if gst_val > 0 else None,
        "gstEnabled": gst_val > 0,
        "cobrotherGstin": (settings.COBROTHER_GSTIN or "").strip() or None,
    }


def gst_settings_for_client() -> dict[str, Any]:
    gstin = (settings.COBROTHER_GSTIN or "").strip()
    return {
        "enabled": domain_gst_enabled(),
        "rate": float(settings.DOMAIN_GST_RATE),
        "priceInclusive": bool(settings.DOMAIN_PRICE_GST_INCLUSIVE),
        "gstin": gstin or None,
        "legalName": (settings.COBROTHER_BILLING_LEGAL_NAME or "").strip() or None,
    }
