"""Operations virtual-assistant catalog tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppException
from app.model.operations.operations_service_mapper import build_operations_service_response
from app.model.operations.operations_service_request import (
    OperationsServiceAvailabilityRequest,
    OperationsServiceCreateRequest,
    OperationsServiceUpdateRequest,
)
from app.service.operations.operations_service_service import (
    CATEGORY_DEFAULT_ICONS,
    OperationsServiceService,
)


def _row(**overrides):
    base = {
        "id": uuid.uuid4(),
        "name": "Virtual SEO Specialist",
        "category": "marketing",
        "description": "Dedicated SEO professional.",
        "price": 16999.0,
        "is_available": True,
        "icon": "Search",
        "display_order": 11,
        "skills": "seo search ranking google",
        "service_type": "virtual_assistance",
        "government_fees_applicable": False,
        "government_fee_text": "Government fees applicable",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_va_create_request_requires_positive_price():
    with pytest.raises(ValueError):
        OperationsServiceCreateRequest(
            name="Virtual HR Manager",
            category="people",
            price=0,
            isAvailable=True,
            serviceType="virtual_assistance",
        )


def test_compliance_create_request_allows_zero_price():
    payload = OperationsServiceCreateRequest(
        name="Trademark Registration",
        category="compliance",
        price=0,
        isAvailable=True,
        serviceType="compliance",
    )
    assert payload.price == 0
    assert payload.service_type == "compliance"


def test_va_update_request_rejects_zero_price():
    with pytest.raises(ValueError):
        OperationsServiceUpdateRequest(
            name="Virtual HR Manager",
            category="people",
            price=0,
            isAvailable=True,
            serviceType="virtual_assistance",
        )


def test_compliance_update_request_allows_zero_price():
    payload = OperationsServiceUpdateRequest(
        name="Website Development",
        category="compliance",
        price=0,
        isAvailable=True,
        serviceType="compliance",
    )
    assert payload.price == 0


def test_mapper_serializes_camel_case():
    payload = build_operations_service_response(_row()).model_dump(by_alias=True)
    assert payload["name"] == "Virtual SEO Specialist"
    assert payload["isAvailable"] is True
    assert payload["displayOrder"] == 11


def test_category_default_icons_cover_seed_categories():
    for category in (
        "people",
        "finance",
        "marketing",
        "technology",
        "sales",
        "support",
        "creative",
        "growth",
        "operations",
    ):
        assert category in CATEGORY_DEFAULT_ICONS


@pytest.mark.asyncio
async def test_list_public_excludes_unavailable_rows():
    session = MagicMock()
    service = OperationsServiceService(session)
    visible = _row(is_available=True)
    with patch.object(
        service._repo,
        "list_public",
        new=AsyncMock(return_value=[visible]),
    ):
        items = await service.list_public()
    assert len(items) == 1
    assert items[0]["isAvailable"] is True


@pytest.mark.asyncio
async def test_list_public_filters_by_compliance_service_type():
    session = MagicMock()
    service = OperationsServiceService(session)
    compliance_row = _row(
        name="GST Registration",
        category="compliance",
        price=3000.0,
        service_type="compliance",
        skills="GST_REGISTRATION",
    )
    list_public = AsyncMock(return_value=[compliance_row])

    with patch.object(service._repo, "list_public", new=list_public):
        items = await service.list_public(service_type="compliance")

    list_public.assert_awaited_once_with(service_type="compliance")
    assert len(items) == 1
    assert items[0]["name"] == "GST Registration"
    assert items[0]["serviceType"] == "compliance"


@pytest.mark.asyncio
async def test_create_admin_assigns_category_icon_and_order():
    session = MagicMock()
    session.commit = AsyncMock()
    service = OperationsServiceService(session)

    created_row = _row(name="Virtual HR Manager", category="people", icon="Users", display_order=16)

    with (
        patch.object(service._repo, "get_max_display_order", new=AsyncMock(return_value=15)),
        patch.object(service._repo, "create", new=AsyncMock(return_value=created_row)),
    ):
        result = await service.create_admin(
            OperationsServiceCreateRequest(
                name="Virtual HR Manager",
                category="people",
                description="HR support",
                price=18999,
                isAvailable=True,
            )
        )

    assert result["name"] == "Virtual HR Manager"
    assert result["icon"] == "Users"


@pytest.mark.asyncio
async def test_update_admin_not_found_raises():
    session = MagicMock()
    service = OperationsServiceService(session)
    with patch.object(service._repo, "get_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as exc:
            await service.update_admin(
                uuid.uuid4(),
                OperationsServiceUpdateRequest(
                    name="Missing",
                    category="people",
                    price=1000,
                    isAvailable=False,
                ),
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_patch_availability_admin_updates_flag():
    session = MagicMock()
    session.commit = AsyncMock()
    service = OperationsServiceService(session)
    row = _row(is_available=True)

    with (
        patch.object(service._repo, "get_by_id", new=AsyncMock(return_value=row)),
        patch.object(service._repo, "save", new=AsyncMock(return_value=row)),
    ):
        result = await service.patch_availability_admin(
            row.id,
            OperationsServiceAvailabilityRequest(isAvailable=False),
        )

    assert row.is_available is False
    assert result["isAvailable"] is False
