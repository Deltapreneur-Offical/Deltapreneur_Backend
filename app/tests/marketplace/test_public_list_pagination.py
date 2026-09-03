"""Pagination on public domain / technology / venture list endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controller.cocreation.cocreation_controller import router as tech_router
from app.controller.domain.domain_controller import router as domain_router
from app.controller.venture.venture_controller import router as venture_router
from app.core.database import get_async_db, get_db
from app.core.exceptions import register_exception_handlers
from app.service.cocreation.cocreation_service import CocreationService
from app.service.domain.marketplace_domain_service import MarketplaceDomainService
from app.service.venture.venture_service import VentureService
from app.utils.cocreation_enums import SoftwareCategory, SoftwarePurchaseType, SoftwareStatus
from app.utils.marketplace_enums import DomainListingStatus


def _domain_listing(name: str = "alpha") -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        domain_name=name,
        domain_extension=".com",
        asking_price=1000.0,
        seller_price=None,
        domain_status=DomainListingStatus.AVAILABLE,
        status=True,
        taken_down=False,
        is_deleted=False,
        created_at=now,
        updated_at=now,
        listed_by=None,
        listed_by_user_id=uuid.uuid4(),
        verified=False,
        featured=False,
        views=0,
        sale_type="ONE_TIME",
        pricing_demand=None,
        logo=None,
        description="",
        contact_info=None,
        purchased_by_user_id=None,
        payment_status=None,
        sold_at=None,
        currency="INR",
        admin_listed=False,
        domain_category=None,
        verification_method=None,
        verified_at=None,
        whois_email=None,
        take_down_reason=None,
        agreement=None,
    )


class _DomainPageService:
    def __init__(self, items: list) -> None:
        self._items = items

    async def list_public_page(self, *, page=1, page_size=None, featured_only=False):
        if page_size is None:
            return len(self._items), list(self._items)
        off = max(0, (page - 1) * page_size)
        chunk = list(self._items)[off : off + page_size]
        return len(self._items), chunk


class _TechPageService:
    def __init__(self, count: int) -> None:
        self._count = count

    async def list_public_page(self, *, page=1, page_size=None, featured_only=False):
        if page_size is None:
            return self._count, [_software(f"s{i}") for i in range(self._count)]
        off = max(0, (page - 1) * page_size)
        end = min(self._count, off + page_size)
        items = [_software(f"s{i}") for i in range(off, end)]
        return self._count, items


def _software(name: str) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        description="d",
        video_link=None,
        what_it_does="w",
        how_it_helps="h",
        github_link="https://github.com/x/y",
        image_url=None,
        live_demo_link=None,
        tech_stack="Py",
        category=SoftwareCategory.SAAS,
        pricing_demand=None,
        price=100.0,
        software_status=SoftwareStatus.AVAILABLE,
        purchase_type=SoftwarePurchaseType.ONE_TIME,
        status=True,
        views=0,
        official=False,
        featured=False,
        created_at=now,
        updated_at=now,
        agreement=SimpleNamespace(id=uuid.uuid4(), terms=True),
        listed_by=SimpleNamespace(
            id=uuid.uuid4(),
            email="a@b.c",
            firstname="A",
            lastname="B",
        ),
        listed_by_user_id=uuid.uuid4(),
        taken_down=False,
        is_deleted=False,
    )


class _VenturePageService:
    def __init__(self, count: int) -> None:
        self._count = count

    async def list_public_page(self, *, page=1, page_size=None):
        if page_size is None:
            return self._count, [SimpleNamespace(id=uuid.uuid4()) for _ in range(self._count)]
        off = max(0, (page - 1) * page_size)
        end = min(self._count, off + page_size)
        return self._count, [SimpleNamespace(id=uuid.uuid4()) for _ in range(end - off)]


@pytest.fixture
def domain_client():
    items = [_domain_listing(f"d{i}") for i in range(5)]
    service = _DomainPageService(items)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(domain_router)
    app.dependency_overrides[get_async_db] = lambda: MagicMock()
    app.dependency_overrides[get_db] = lambda: MagicMock()
    from app.controller.domain import domain_controller

    app.dependency_overrides[domain_controller.get_marketplace_service] = lambda: service
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_domain_all_without_page_size_returns_legacy_shape(domain_client) -> None:
    res = domain_client.get("/api/v1/domain/all")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert len(body["data"]) == 5
    assert body["total"] == 5


def test_domain_all_with_page_size(domain_client) -> None:
    res = domain_client.get("/api/v1/domain/all", params={"page": 2, "page_size": 2})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 5
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert len(body["items"]) == 2
