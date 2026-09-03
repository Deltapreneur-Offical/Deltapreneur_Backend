"""Operations hire/booking request tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppException
from app.entity.user.app_user import AppUser
from app.model.operations.operations_service_request_dto import (
    OperationsServiceRequestCreateBody,
    OperationsServiceRequestStatusBody,
)
from app.service.operations.operations_service_request_service import (
    OperationsServiceRequestService,
    _derive_request_meta,
)


def _service_row(**overrides):
    base = {
        "id": uuid.uuid4(),
        "name": "Virtual HR Manager",
        "price": 18999.0,
        "service_type": "virtual_assistance",
        "is_available": True,
        "is_deleted": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _request_row(**overrides):
    base = {
        "id": uuid.uuid4(),
        "operations_service_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "request_type": "hire",
        "service_type": "virtual_assistance",
        "billing_period": "monthly",
        "service_name": "Virtual HR Manager",
        "quoted_price": 18999.0,
        "full_name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "+919876543210",
        "company_name": "Acme",
        "city_state": None,
        "message": "Need HR support",
        "preferred_timeline": "Next week",
        "status": "PENDING",
        "razorpay_order_id": None,
        "razorpay_payment_id": None,
        "razorpay_signature": None,
        "payment_status": "PENDING",
        "payment_amount_inr": None,
        "contact_status": "CONTACT_PENDING",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "user": SimpleNamespace(
            id=uuid.uuid4(),
            firstname="Jane",
            lastname="Doe",
            email="jane@example.com",
            phone_number="+919876543210",
        ),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_derive_request_meta_va():
    assert _derive_request_meta("virtual_assistance") == ("hire", "monthly")


def test_derive_request_meta_compliance():
    assert _derive_request_meta("compliance") == ("booking", "one_time")


@pytest.mark.asyncio
async def test_submit_hire_request_succeeds():
    session = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    service = OperationsServiceRequestService(session)
    user = SimpleNamespace(id=uuid.uuid4())
    catalog = _service_row()

    with (
        patch.object(service._services, "get_by_id", new=AsyncMock(return_value=catalog)),
        patch.object(service._repo, "find_pending_for_user_service", new=AsyncMock(return_value=None)),
        patch.object(service._repo, "create", new=AsyncMock(side_effect=lambda row: row)),
    ):
        result = await service.submit(
            OperationsServiceRequestCreateBody(
                operationsServiceId=str(catalog.id),
                fullName="Jane Doe",
                email="jane@example.com",
                phone="9876543210",
                message="Need help",
            ),
            user=user,
        )

    assert result["requestType"] == "hire"
    assert result["billingPeriod"] == "monthly"
    assert result["serviceName"] == "Virtual HR Manager"


@pytest.mark.asyncio
async def test_submit_booking_request_succeeds():
    session = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    service = OperationsServiceRequestService(session)
    user = SimpleNamespace(id=uuid.uuid4())
    catalog = _service_row(
        name="GST Registration",
        price=3000.0,
        service_type="compliance",
    )

    with (
        patch.object(service._services, "get_by_id", new=AsyncMock(return_value=catalog)),
        patch.object(service._repo, "find_pending_for_user_service", new=AsyncMock(return_value=None)),
        patch.object(service._repo, "create", new=AsyncMock(side_effect=lambda row: row)),
    ):
        result = await service.submit(
            OperationsServiceRequestCreateBody(
                operationsServiceId=str(catalog.id),
                fullName="Jane Doe",
                email="jane@example.com",
                phone="9876543210",
                cityState="Maharashtra",
            ),
            user=user,
        )

    assert result["requestType"] == "booking"
    assert result["billingPeriod"] == "one_time"


@pytest.mark.asyncio
async def test_list_mine_returns_user_requests():
    session = MagicMock()
    service = OperationsServiceRequestService(session)
    user = SimpleNamespace(id=uuid.uuid4())
    rows = [_request_row(user_id=user.id), _request_row(user_id=user.id)]

    list_mock = AsyncMock(return_value=rows)
    with patch.object(service._repo, "list_for_user", list_mock):
        result = await service.list_for_user(user=user)

    assert len(result) == 2
    assert result[0]["serviceName"] == "Virtual HR Manager"
    list_mock.assert_awaited_once_with(user.id)


@pytest.mark.asyncio
async def test_submit_duplicate_pending_rejected():
    session = MagicMock()
    service = OperationsServiceRequestService(session)
    user = SimpleNamespace(id=uuid.uuid4())
    catalog = _service_row()

    with (
        patch.object(service._services, "get_by_id", new=AsyncMock(return_value=catalog)),
        patch.object(
            service._repo,
            "find_pending_for_user_service",
            new=AsyncMock(return_value=_request_row()),
        ),
    ):
        with pytest.raises(AppException) as exc:
            await service.submit(
                OperationsServiceRequestCreateBody(
                    operationsServiceId=str(catalog.id),
                    fullName="Jane Doe",
                    email="jane@example.com",
                    phone="9876543210",
                ),
                user=user,
            )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_submit_unavailable_service_rejected():
    session = MagicMock()
    service = OperationsServiceRequestService(session)
    user = SimpleNamespace(id=uuid.uuid4())

    with patch.object(service._services, "get_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as exc:
            await service.submit(
                OperationsServiceRequestCreateBody(
                    operationsServiceId=str(uuid.uuid4()),
                    fullName="Jane Doe",
                    email="jane@example.com",
                    phone="9876543210",
                ),
                user=user,
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_patch_status_admin_updates_row():
    session = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    service = OperationsServiceRequestService(session)
    row = _request_row()

    with (
        patch.object(service._repo, "get_by_id", new=AsyncMock(return_value=row)),
        patch.object(service._repo, "save", new=AsyncMock(return_value=row)),
    ):
        result = await service.patch_status_admin(
            row.id,
            OperationsServiceRequestStatusBody(status="CONTACTED"),
        )

    assert row.status == "CONTACTED"
    assert result["status"] == "CONTACTED"


@pytest.mark.asyncio
async def test_patch_status_admin_reverts_to_pending():
    session = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    service = OperationsServiceRequestService(session)
    row = _request_row(status="CONTACTED")

    with (
        patch.object(service._repo, "get_by_id", new=AsyncMock(return_value=row)),
        patch.object(service._repo, "save", new=AsyncMock(return_value=row)),
    ):
        result = await service.patch_status_admin(
            row.id,
            OperationsServiceRequestStatusBody(status="PENDING"),
        )

    assert row.status == "PENDING"
    assert result["status"] == "PENDING"


@pytest.mark.asyncio
async def test_list_for_user_returns_user_requests():
    session = MagicMock()
    service = OperationsServiceRequestService(session)
    user = SimpleNamespace(id=uuid.uuid4())
    rows = [_request_row(user_id=user.id), _request_row(user_id=user.id)]

    with patch.object(service._repo, "list_for_user", new=AsyncMock(return_value=rows)):
        result = await service.list_for_user(user=user)

    assert len(result) == 2
    assert result[0]["requestType"] == "hire"


@pytest.mark.asyncio
async def test_delete_admin_removes_request():
    session = MagicMock()
    session.commit = AsyncMock()
    service = OperationsServiceRequestService(session)
    row = _request_row()
    delete_mock = AsyncMock()

    with (
        patch.object(service._repo, "get_by_id", new=AsyncMock(return_value=row)),
        patch.object(service._repo, "delete", new=delete_mock),
    ):
        await service.delete_admin(row.id)

    delete_mock.assert_awaited_once_with(row)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_admin_not_found():
    session = MagicMock()
    service = OperationsServiceRequestService(session)

    with patch.object(service._repo, "get_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as exc:
            await service.delete_admin(uuid.uuid4())

    assert exc.value.status_code == 404
