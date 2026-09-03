"""Unit tests for domain auction winner payment amount resolution."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.exceptions import AppException
from app.service.auction.auction_payment_service import AuctionPaymentService


def test_winner_payment_amount_from_highest_bid():
    auction = SimpleNamespace(current_highest_bid=Decimal("15000.50"))
    assert AuctionPaymentService._winner_payment_amount(auction) == Decimal("15000.50")


def test_winner_payment_amount_rejects_missing_bid():
    auction = SimpleNamespace(current_highest_bid=None)
    with pytest.raises(AppException) as exc:
        AuctionPaymentService._winner_payment_amount(auction)
    assert exc.value.status_code == 409


def test_winner_payment_amount_rejects_zero_bid():
    auction = SimpleNamespace(current_highest_bid=Decimal("0"))
    with pytest.raises(AppException) as exc:
        AuctionPaymentService._winner_payment_amount(auction)
    assert exc.value.status_code == 409
