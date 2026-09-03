"""Normalize equity percentages for API responses and storage."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def normalize_equity_percent(value: float | int | str | None) -> float | None:
    """Round to 2 decimal places without snapping near-whole values."""
    if value is None:
        return None
    try:
        quantized = Decimal(str(float(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return float(quantized)
    except (TypeError, ValueError):
        return None
