from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.service.domain.marketplace_payment_service import MarketplacePaymentService
from app.utils.marketplace_enums import DomainListingStatus


@pytest.mark.asyncio
@patch("app.service.domain.marketplace_payment_service.rzp.create_order")
@patch("app.service.domain.marketplace_payment_service.rzp.is_configured", return_value=True)
@patch("app.service.domain.marketplace_payment_service.rzp.get_key_id", return_value="rzp_test_key")
async def test_create_purchase_order_allows_unverified_listing(
    _mock_key,
    _mock_configured,
    mock_create_order,
):
    listing_id = uuid.uuid4()
    buyer_id = uuid.uuid4()
    listing = SimpleNamespace(
        id=listing_id,
        listed_by_user_id=uuid.uuid4(),
        verified=False,
        domain_status=DomainListingStatus.AVAILABLE,
        asking_price=121.0,
        purchase_buyer_name=None,
        purchase_buyer_email=None,
        purchase_buyer_phone=None,
        purchase_addon_services=None,
        razorpay_order_id=None,
        payment_status=None,
        purchased_by_user_id=None,
    )
    buyer = SimpleNamespace(id=buyer_id, email="buyer@example.com", phone_number="+918000000000")

    mock_create_order.return_value = {"id": "order_123"}

    service = MarketplacePaymentService(SimpleNamespace(commit=AsyncMock()))
    service._repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=listing),
        save=AsyncMock(return_value=listing),
    )

    result = await service.create_purchase_order(
        listing_id,
        buyer=buyer,
        buyer_name="Buyer",
        buyer_email="buyer@example.com",
        buyer_phone="8088117744",
    )

    assert result["orderId"] == "order_123"
    assert listing.domain_status == DomainListingStatus.PENDING
    assert listing.purchased_by_user_id == buyer_id
    assert listing.verified is False
