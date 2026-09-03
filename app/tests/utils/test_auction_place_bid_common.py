"""Tests for shared auction bid helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.utils.auction_place_bid_common import (
    apply_anti_snipe,
    build_bid_placed_ws_event,
    normalize_bid_amount,
)
from app.utils.enums import AuctionStatus


def test_apply_anti_snipe_extends_end_time() -> None:
    now = datetime.now(timezone.utc)
    end = now + timedelta(minutes=2)
    new_end, new_status, extended = apply_anti_snipe(
        end,
        now,
        status=AuctionStatus.ACTIVE,
        extended_status=AuctionStatus.EXTENDED,
    )
    assert extended is True
    assert new_status == AuctionStatus.EXTENDED
    assert new_end == end + timedelta(minutes=5)


def test_apply_anti_snipe_skips_when_time_remains() -> None:
    now = datetime.now(timezone.utc)
    end = now + timedelta(minutes=30)
    new_end, new_status, extended = apply_anti_snipe(
        end,
        now,
        status=AuctionStatus.ACTIVE,
        extended_status=AuctionStatus.EXTENDED,
    )
    assert extended is False
    assert new_status == AuctionStatus.ACTIVE
    assert new_end == end


def test_normalize_bid_amount_rejects_low_bid() -> None:
    with pytest.raises(ValueError, match="at least"):
        normalize_bid_amount(
            100,
            current_highest=200,
            min_bid_price=50,
        )


def test_build_bid_placed_ws_event_shape() -> None:
    now = datetime.now(timezone.utc)
    payload = build_bid_placed_ws_event(
        auction_id="abc",
        status=AuctionStatus.ACTIVE,
        current_highest_bid=500,
        total_bids=3,
        end_time=now,
        bidder_name="Ada Lovelace",
        amount=500,
        bid_time=now,
        extended=True,
    )
    assert payload["type"] == "BID_PLACED"
    assert payload["auctionId"] == "abc"
    assert payload["extended"] is True
    assert payload["latestBid"]["bidderName"] == "Ada Lovelace"
