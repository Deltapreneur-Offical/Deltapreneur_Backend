"""Deductive acquisition commission — fee taken from asking price."""

from __future__ import annotations

from app.utils.money import round_inr


def compute_deductive_commission(
    asking_price: float,
    commission_percent: float,
) -> tuple[float, float, float]:
    """
    Return (asking_price, commission_amount, seller_receives).
    Example: ₹10,000 @ 3% → commission ₹300, seller receives ₹9,700.
    """
    if asking_price < 0:
        raise ValueError("Asking price cannot be negative.")
    if commission_percent < 0:
        raise ValueError("Commission percent cannot be negative.")
    price = round_inr(asking_price)
    commission = round_inr(float(price) * commission_percent / 100.0)
    seller_receives = price - commission
    return float(price), float(commission), float(seller_receives)
