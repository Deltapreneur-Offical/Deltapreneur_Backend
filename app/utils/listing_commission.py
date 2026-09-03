"""Listing commission helpers (commission is deducted from sale price)."""

from __future__ import annotations

from app.utils.money import round_inr


def compute_listing_commission(
    listing_price: float,
    commission_percent: float,
) -> tuple[float, float, float]:
    """
    Return (seller_payout_amount, commission_amount, listing_price).
    INR amounts are whole rupees.
    """
    if listing_price < 0:
        raise ValueError("Listing price cannot be negative.")
    if commission_percent < 0:
        raise ValueError("Commission percent cannot be negative.")

    price = round_inr(listing_price)
    commission = round_inr(float(price) * commission_percent / 100.0)
    seller_payout = price - commission
    return float(seller_payout), float(commission), float(price)


def pricing_breakdown(
    *,
    stored_price: float,
    seller_price: float | None,
    commission_percent: float,
) -> dict[str, float | None]:
    """Build API pricing fields for a listing row."""
    if stored_price > 0:
        seller_payout, commission, final_price = compute_listing_commission(
            stored_price, commission_percent
        )
        return {
            "sellerPrice": seller_payout,
            "platformCommissionPercent": commission_percent,
            "platformCommissionAmount": commission,
            "finalListingPrice": final_price,
            "displayPrice": final_price,
        }
    return {
        "sellerPrice": None,
        "platformCommissionPercent": None,
        "platformCommissionAmount": None,
        "finalListingPrice": stored_price,
        "displayPrice": stored_price,
    }
