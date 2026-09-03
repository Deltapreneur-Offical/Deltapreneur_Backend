"""Shared min/max bid rules for all auction types.

Business rule:
- Reference amount = current active bid if any, else starting price (min bid).
- Minimum next bid = reference + ₹1 (strictly greater than reference).
- Maximum allowed bid = 150% of reference amount.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Union

MAX_BID_ACTIVE_RATIO = Decimal("1.5")
MIN_BID_UNIT_INCREMENT = Decimal("1")
MONEY_QUANT = Decimal("0.01")

Number = Union[Decimal, float, int, str, None]


def as_decimal(value: Number) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return Decimal("0")
    return Decimal(text)


def active_bid_reference(*, current_highest: Number, min_bid_price: Number) -> Decimal:
    """Amount used for min/max calculations (current active bid or starting price)."""
    current = as_decimal(current_highest)
    if current > 0:
        return current.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    minimum = as_decimal(min_bid_price)
    return minimum.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def min_required_bid(*, current_highest: Number, min_bid_price: Number) -> Decimal:
    reference = active_bid_reference(
        current_highest=current_highest,
        min_bid_price=min_bid_price,
    )
    return (reference + MIN_BID_UNIT_INCREMENT).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def max_allowed_bid(*, current_highest: Number, min_bid_price: Number) -> Decimal:
    reference = active_bid_reference(
        current_highest=current_highest,
        min_bid_price=min_bid_price,
    )
    if reference <= 0:
        return Decimal("0")
    return (reference * MAX_BID_ACTIVE_RATIO).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def bid_limit_fields(
    *,
    current_highest: Number,
    min_bid_price: Number,
) -> dict[str, float]:
    reference = active_bid_reference(
        current_highest=current_highest,
        min_bid_price=min_bid_price,
    )
    return {
        "activeBidReference": float(reference),
        "minNextBid": float(
            min_required_bid(
                current_highest=current_highest,
                min_bid_price=min_bid_price,
            )
        ),
        "maxBidPrice": float(
            max_allowed_bid(
                current_highest=current_highest,
                min_bid_price=min_bid_price,
            )
        ),
    }


def bid_amount_in_range(
    amount: Number,
    *,
    current_highest: Number,
    min_bid_price: Number,
) -> tuple[bool, Decimal, Decimal, Decimal]:
    """Return (ok, min_required, max_allowed, normalized_amount)."""
    normalized = as_decimal(amount).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    min_req = min_required_bid(
        current_highest=current_highest,
        min_bid_price=min_bid_price,
    )
    max_allowed = max_allowed_bid(
        current_highest=current_highest,
        min_bid_price=min_bid_price,
    )
    if max_allowed <= 0:
        return False, min_req, max_allowed, normalized
    ok = min_req <= normalized <= max_allowed
    return ok, min_req, max_allowed, normalized


def format_bid_range_error(
    *,
    normalized: Decimal,
    min_required: Decimal,
    max_allowed: Decimal,
) -> str | None:
    if max_allowed <= 0:
        return "Auction starting price is not configured."
    if normalized < min_required:
        return f"Bid must be at least ₹{min_required:,.2f}."
    if normalized > max_allowed:
        return (
            f"Bid cannot exceed ₹{max_allowed:,.2f} "
            f"(150% of the current active bid)."
        )
    return None
