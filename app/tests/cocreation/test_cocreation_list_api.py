from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controller.cocreation import cocreation_alias_controller, cocreation_controller
from app.core.database import get_async_db, get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import register_exception_handlers
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.model.cocreation.cocreation_request import CreateSoftwareRequest
from app.utils.cocreation_enums import (
    SoftwareCategory,
    SoftwarePricingDemand,
    SoftwarePurchaseType,
    SoftwareStatus,
)


def _user() -> AppUser:
    return AppUser(
        id=uuid.uuid4(),
        email="lister@test.local",
        role=UserRole.USER,
        active=True,
        email_verified=True,
        profile_complete=True,
    )


def _software(name: str = "InvoiceFlow") -> SimpleNamespace:
    from app.utils.cocreation_enums import TechnologyType
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        description="desc",
        video_link=None,
        what_it_does="x",
        how_it_helps="y",
        github_link="https://github.com/org/repo",
        image_url=None,
        live_demo_link=None,
        tech_stack="Python",
        category=SoftwareCategory.SAAS,
        pricing_demand=SoftwarePricingDemand.FIXED,
        price=1000.0,
        seller_price=None,
        software_status=SoftwareStatus.AVAILABLE,
        purchase_type=SoftwarePurchaseType.ONE_TIME,
        technology_type=TechnologyType.SOFTWARE,
        status=True,
        views=0,
        official=False,
        featured=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        agreement=SimpleNamespace(id=uuid.uuid4(), terms=True),
        listed_by=SimpleNamespace(
            id=uuid.uuid4(),
            email="lister@test.local",
            firstname="Li",
            lastname="Ster",
            role=UserRole.USER,
        ),
        listed_by_user_id=uuid.uuid4(),
        taken_down=False,
        is_deleted=False,
        verified=False,
        verified_at=None,
        currency="INR",
        pricing_plans=[],
        documentation_urls=None,
        download_urls=None,
    )


class _CocreationServiceStub:
    def __init__(self, items: list | None = None) -> None:
        self.items = items or []
        self.created = None

    async def list_all(self):
        return self.items

    async def list_public_page(self, *, page=1, page_size=None, featured_only=False):
        if page_size is None:
            return len(self.items), list(self.items)
        off = max(0, (page - 1) * page_size)
        chunk = list(self.items)[off : off + page_size]
        return len(self.items), chunk

    async def list_my(self, _user):
        return self.items

    async def create_software(self, payload, *, lister):
        self.created = (payload, lister)
        return _software(payload.name)


class _PurchaseRepoStub:
    async def count_completed_by_software_ids(self, software_ids):
        return {sid: 2 for sid in software_ids}


class _AuctionRepoStub:
    async def map_by_software_ids(self, software_ids):
        return {}


async def _override_async_db():
    yield MagicMock()


@pytest.fixture
def cocreation_client():
    user = _user()
    service = _CocreationServiceStub([_software()])
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(cocreation_alias_controller.router, prefix="/api/v1/cocreation")
    app.include_router(cocreation_controller.router, prefix="/api/v1/cocreation")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_async_db] = _override_async_db
    app.dependency_overrides[cocreation_controller.get_cocreation_service] = lambda: service
    app.dependency_overrides[cocreation_alias_controller.get_cocreation_service] = lambda: service
    app.dependency_overrides[cocreation_controller.get_purchase_repo] = _PurchaseRepoStub
    app.dependency_overrides[cocreation_alias_controller.get_purchase_repo] = _PurchaseRepoStub
    app.dependency_overrides[cocreation_controller.get_auction_repo] = _AuctionRepoStub
    app.dependency_overrides[cocreation_controller.get_db] = lambda: MagicMock()
    try:
        with TestClient(app) as client:
            yield client, service, user
    finally:
        app.dependency_overrides.clear()


def test_list_all_returns_frontend_data_array(cocreation_client) -> None:
    client, _, _ = cocreation_client
    res = client.get("/api/v1/cocreation/all")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 1
    assert body["data"][0]["name"] == "InvoiceFlow"
    assert body["items"][0]["id"] == body["data"][0]["id"]


def test_my_listings_returns_purchase_count(cocreation_client) -> None:
    client, _, _ = cocreation_client
    res = client.get("/api/v1/cocreation/my-listings")
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["data"], list)
    assert body["data"][0]["purchaseCount"] == 2


def test_create_accepts_without_trailing_slash(cocreation_client) -> None:
    client, service, user = cocreation_client
    payload = {
        "name": "New Tool",
        "description": "A product",
        "whatItDoes": "Automates",
        "howItHelps": "Saves time",
        "githubLink": "https://github.com/org/repo",
        "category": "SAAS",
        "pricingDemand": "FIXED",
        "price": "2500",
        "currency": "INR",
        "agreement": {"terms": True},
    }
    res = client.post("/api/v1/cocreation", json=payload)
    assert res.status_code == 201, res.text
    assert service.created is not None
    assert service.created[1] is user


def test_analytics_returns_flat_metrics_for_frontend(cocreation_client) -> None:
    client, _, user = cocreation_client
    software_id = uuid.uuid4()

    class _AnalyticsServiceStub(_CocreationServiceStub):
        async def get_analytics(self, software_id, *, actor, db):
            return {
                "softwareId": str(software_id),
                "softwareName": "InvoiceFlow",
                "totalViews": 3,
                "totalSales": 0,
                "totalRevenue": 0.0,
                "completionStatus": "Available",
                "viewsByDay": {},
                "byIndustry": {},
                "byRole": {},
            }

    app = client.app
    app.dependency_overrides[cocreation_controller.get_cocreation_service] = (
        lambda: _AnalyticsServiceStub()
    )
    app.dependency_overrides[cocreation_controller.get_db] = lambda: MagicMock()

    res = client.get(f"/api/v1/cocreation/{software_id}/analytics")
    assert res.status_code == 200
    body = res.json()
    assert body["totalRevenue"] == 0.0
    assert body["totalViews"] == 3
    assert body["softwareName"] == "InvoiceFlow"
    assert body["success"] is True


def test_create_payload_coerces_empty_select_values() -> None:
    payload = CreateSoftwareRequest.model_validate(
        {
            "name": "Tool",
            "price": "",
            "category": "",
            "pricingDemand": "",
            "githubLink": "https://github.com/org/repo",
            "currency": "INR",
        }
    )
    assert payload.price == 0
    assert payload.category is None
    assert payload.pricing_demand is None
