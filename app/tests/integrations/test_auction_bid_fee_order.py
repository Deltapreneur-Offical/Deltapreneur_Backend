"""Mocked auction fee / platform settings tests — no database, no real Razorpay."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from app.entity.auction.auction_fee_payment_entity import AuctionFeeAuctionType
from app.service.auction.auction_fee_service import AuctionFeeService


@pytest.mark.asyncio
async def test_create_bid_fee_order_charges_admin_bid_fee_not_full_bid():
    session = AsyncMock()
    session.commit = AsyncMock()
    service = AuctionFeeService(session)
    service._settings = SimpleNamespace(auction_bid_fee_inr=AsyncMock(return_value=20.0))
    service._repo = SimpleNamespace(create=AsyncMock())

    user = SimpleNamespace(id=uuid.uuid4(), role=None)
    auction_id = uuid.uuid4()
    bid_amount = 2_300_000

    with (
        patch("app.service.auction.auction_fee_service.rzp") as rzp,
        patch(
            "app.service.user.edge_points_service.EdgePointsService.calculate_redemption",
            new_callable=AsyncMock,
            return_value=(20.0, 0),
        ),
    ):
        rzp.is_configured.return_value = True
        rzp.is_test_mode.return_value = False
        rzp.get_key_id.return_value = "rzp_test"
        rzp.create_order.return_value = {"id": "order_bid_fee_1"}

        result = await service.create_bid_fee_order(
            auction_type=AuctionFeeAuctionType.DOMAIN,
            auction_id=auction_id,
            bid_amount=bid_amount,
            user=user,
        )

    rzp.create_order.assert_called_once()
    assert rzp.create_order.call_args.kwargs["amount_inr"] == 20.0
    assert result["amount"] == 20.0
    assert result["bidAmount"] == float(bid_amount)

    row = service._repo.create.await_args.args[0]
    assert float(row.fee_amount_inr) == 20.0
    assert float(row.bid_amount) == float(bid_amount)


@pytest.mark.asyncio
async def test_update_listing_fees_commits_without_participation_fee():
    from app.service.platform.platform_settings_service import PlatformSettingsService

    session = AsyncMock()
    session.commit = AsyncMock()
    service = PlatformSettingsService(session)
    service._repo = SimpleNamespace(set=AsyncMock(), get=AsyncMock(return_value=None))
    service.get_listing_fees_and_charges = AsyncMock(
        return_value={
            "auctionBidFeeInr": 25.0,
            "listingCommissionPercent": 15.0,
            "softwareOnetimeCommissionPercent": 12.0,
        }
    )

    result = await service.update_listing_fees_and_charges(
        auction_bid_fee_inr=25.0,
        software_onetime_commission_percent=12.0,
    )

    session.commit.assert_awaited()
    assert result["auctionBidFeeInr"] == 25.0
    assert result["softwareOnetimeCommissionPercent"] == 12.0
    # Domains and Technology keys are independent — only tech was updated here
    set_keys = [call.args[0] for call in service._repo.set.await_args_list]
    assert "auction_bid_fee_inr" in set_keys
    assert "software_onetime_commission_percent" in set_keys
