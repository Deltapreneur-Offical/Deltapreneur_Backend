from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controller.cocreation import cocreation_controller
from app.core.dependencies import get_current_user
from app.core.exceptions import register_exception_handlers
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.service.cocreation.cocreation_payment_service import CocreationPaymentService
from app.utils.cocreation_enums import (
    SoftwarePaymentStatus,
    SoftwarePurchaseCompletionStatus,
)


def _buyer() -> AppUser:
    return AppUser(
        id=uuid.uuid4(),
        email="buyer@test.local",
        role=UserRole.USER,
        active=True,
        email_verified=True,
        profile_complete=True,
    )


@pytest.fixture
def confirm_client():
    user = _buyer()
    purchase_id = uuid.uuid4()
    software_id = uuid.uuid4()

    purchase = SimpleNamespace(
        id=purchase_id,
        software_id=software_id,
        buyer_id=user.id,
        buyer_email=user.email,
        payment_status=SoftwarePaymentStatus.COMPLETED,
        completion_status=SoftwarePurchaseCompletionStatus.PENDING,
        software=SimpleNamespace(
            id=software_id,
            name="Test App",
            github_link="https://github.com/org/repo",
        ),
    )

    class _PaymentServiceStub:
        async def confirm_purchase(self, purchase_id_arg, *, buyer):
            assert purchase_id_arg == purchase_id
            assert buyer is user
            purchase.completion_status = SoftwarePurchaseCompletionStatus.CONFIRMED
            return {
                "success": True,
                "message": "Purchase confirmed successfully.",
                "githubLink": purchase.software.github_link,
                "completionStatus": SoftwarePurchaseCompletionStatus.CONFIRMED.value,
                "purchaseId": str(purchase.id),
            }

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(cocreation_controller.router, prefix="/api/v1/cocreation")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[cocreation_controller.get_payment_service] = (
        lambda: _PaymentServiceStub()
    )
    try:
        with TestClient(app) as client:
            yield client, purchase_id
    finally:
        app.dependency_overrides.clear()


def test_confirm_purchase_endpoint_returns_github_link(confirm_client) -> None:
    client, purchase_id = confirm_client
    res = client.post(f"/api/v1/cocreation/purchase/{purchase_id}/confirm")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["githubLink"] == "https://github.com/org/repo"
    assert body["completionStatus"] == "CONFIRMED"


@pytest.mark.asyncio
async def test_confirm_purchase_service_updates_status(monkeypatch) -> None:
    buyer = _buyer()
    purchase_id = uuid.uuid4()
    software_id = uuid.uuid4()

    purchase = SimpleNamespace(
        id=purchase_id,
        software_id=software_id,
        buyer_id=buyer.id,
        buyer_email=buyer.email,
        payment_status=SoftwarePaymentStatus.COMPLETED,
        completion_status=SoftwarePurchaseCompletionStatus.PENDING,
        software=SimpleNamespace(
            id=software_id,
            name="Test App",
            github_link="https://github.com/org/repo",
        ),
    )

    class _PurchaseRepo:
        async def get_by_id(self, pid):
            return purchase if pid == purchase_id else None

        async def save(self, row):
            return row

    service = CocreationPaymentService(MagicMock())
    service._purchase_repo = _PurchaseRepo()
    service._software_repo = MagicMock()
    service._session = MagicMock()
    service._session.commit = AsyncMock()
    service._send_confirmed_email = AsyncMock()

    result = await service.confirm_purchase(purchase_id, buyer=buyer)

    assert result["githubLink"] == "https://github.com/org/repo"
    assert purchase.completion_status == SoftwarePurchaseCompletionStatus.CONFIRMED
    service._send_confirmed_email.assert_awaited_once()
