"""Integration tests for venture create (enum / schema correctness)."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.controller.venture.venture_controller import router as venture_router
from app.utils.venture_enums import VentureStage

CREATION_FEE_ORDER = "order_test_creation_fee"


@pytest.mark.asyncio
async def test_create_regular_venture_ignores_auction_duration(
    integration_user_factory,
    integration_app_factory,
):
    """REGULAR listings must not 500 when client sends auction_duration."""
    user = await integration_user_factory()
    app = integration_app_factory(routers=[venture_router], current_user=user)
    transport = ASGITransport(app=app)

    payload = {
        "brand_details": {"brand_name": "TestCo", "description": "A venture"},
        "contact_info": {"email": "founder@example.com", "phone_number": "+919876543210"},
        "agreement": {"terms": True},
        "stage": VentureStage.IDEA.value,
        "sale_type": "REGULAR",
        "equity_percent_offered": 25,
        "auction_duration": "ONE_DAY",
        "auction_min_bid_price": 1000,
        "roles": [],
    }

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/v1/venture/", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["saleType"] == "REGULAR"
    assert body.get("auctionDuration") is None


@pytest.mark.asyncio
async def test_create_auction_venture_persists_duration(
    integration_user_factory,
    integration_app_factory,
):
    user = await integration_user_factory()
    app = integration_app_factory(routers=[venture_router], current_user=user)
    transport = ASGITransport(app=app)

    payload = {
        "brand_details": {"brand_name": "AuctionCo"},
        "contact_info": {"email": "auction@example.com", "phone_number": "+919876543211"},
        "agreement": {"terms": True},
        "stage": VentureStage.REVENUE_GENERATING.value,
        "sale_type": "AUCTION",
        "auction_duration": "SEVEN_DAYS",
        "auction_min_bid_price": 50000,
        "creationFeeOrderId": CREATION_FEE_ORDER,
        "roles": [],
    }

    with patch(
        "app.service.venture.venture_service.ListingPricingService.acquisition_commission_percent",
        new_callable=AsyncMock,
        return_value=3.0,
    ):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post("/api/v1/venture/", json=payload)

    assert response.status_code == 422, response.text
