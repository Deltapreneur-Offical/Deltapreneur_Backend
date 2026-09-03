"""Money rounding helpers — INR amounts use whole rupees."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# Snap float noise from FX / percentage math (e.g. 9999.999999 → 10000).
_INR_FLOAT_SNAP_TOLERANCE = Decimal("0.01")


def round_inr(value: float | int | str | None) -> int:
    """Round to whole INR rupees, snapping near-whole float noise."""
    if value is None:
        return 0
    raw = Decimal(str(float(value)))
    nearest = int(raw.to_integral_value(rounding=ROUND_HALF_UP))
    if abs(raw - Decimal(nearest)) < _INR_FLOAT_SNAP_TOLERANCE:
        return nearest
    return nearest


def round_money(value: float | int | str | None) -> float:
    """Round to 2 decimal places."""
    if value is None:
        return 0.0
    return float(Decimal(str(float(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_inr_commission(
    amount: float | int,
    commission_percent: float,
) -> tuple[int, int, int]:
    """Return (amount, commission, net) in whole INR rupees."""
    base = round_inr(amount)
    commission = round_inr(float(base) * float(commission_percent) / 100.0)
    return base, commission, base - commission


def is_likely_truncated_round_inr(deal_value: int | None) -> bool:
    """
    Detect deal values corrupted by legacy int() truncation (e.g. 10000 → 9999).

    Matches amounts one rupee below a round ₹10,000 multiple: 9999, 19999, …
    """
    if deal_value is None or deal_value < 9999:
        return False
    return (deal_value + 1) % 10000 == 0


def repair_truncated_inr_amount(deal_value: int | None) -> int | None:
    """Bump legacy truncated asking prices up by ₹1 when the pattern matches."""
    if deal_value is None:
        return None
    normalized = round_inr(deal_value)
    if is_likely_truncated_round_inr(normalized):
        return normalized + 1
    return normalized
