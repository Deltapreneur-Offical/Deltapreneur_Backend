"""Unit tests for software auction winner payment helpers."""

from types import SimpleNamespace

import pytest

from app.core.exceptions import AppException
from app.service.cocreation.software_auction_service import SoftwareAuctionService


def test_winner_payment_amount_from_highest_bid():
    auction = SimpleNamespace(current_highest_bid=25000.0)
    assert SoftwareAuctionService._winner_payment_amount(auction) == 25000.0


def test_winner_payment_amount_rejects_missing_bid():
    auction = SimpleNamespace(current_highest_bid=0)
    with pytest.raises(AppException) as exc:
        SoftwareAuctionService._winner_payment_amount(auction)
    assert exc.value.status_code == 400
