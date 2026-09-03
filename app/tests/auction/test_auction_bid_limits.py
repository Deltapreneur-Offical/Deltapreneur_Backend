from decimal import Decimal

from app.utils.auction_bid_limits import (
    bid_amount_in_range,
    max_allowed_bid,
    min_required_bid,
)


def test_first_bid_limits_from_starting_price():
    assert min_required_bid(current_highest=0, min_bid_price=1000) == Decimal("1001.00")
    assert max_allowed_bid(current_highest=0, min_bid_price=1000) == Decimal("1500.00")

    ok, min_req, max_allowed, amount = bid_amount_in_range(
        1400,
        current_highest=0,
        min_bid_price=1000,
    )
    assert ok is True
    assert min_req == Decimal("1001.00")
    assert max_allowed == Decimal("1500.00")
    assert amount == Decimal("1400.00")


def test_second_bid_limits_from_active_bid():
    assert min_required_bid(current_highest=1400, min_bid_price=1000) == Decimal("1401.00")
    assert max_allowed_bid(current_highest=1400, min_bid_price=1000) == Decimal("2100.00")

    ok, _, max_allowed, _ = bid_amount_in_range(
        2000,
        current_highest=1400,
        min_bid_price=1000,
    )
    assert ok is True
    assert max_allowed == Decimal("2100.00")

    ok_high, _, _, _ = bid_amount_in_range(
        2101,
        current_highest=1400,
        min_bid_price=1000,
    )
    assert ok_high is False


def test_third_bid_limits_after_2000_active_bid():
    assert min_required_bid(current_highest=2000, min_bid_price=1000) == Decimal("2001.00")
    assert max_allowed_bid(current_highest=2000, min_bid_price=1000) == Decimal("3000.00")
