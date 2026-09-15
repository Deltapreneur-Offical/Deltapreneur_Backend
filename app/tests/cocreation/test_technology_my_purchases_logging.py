"""Technology my-purchases logging must not 500 when software is null."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.controller.cocreation import cocreation_alias_controller as alias
from app.core.dependencies import get_current_user
from app.core.database import get_async_db
from app.model.common.api_response import ApiResponse


@pytest.mark.asyncio
async def test_my_purchases_logs_safely_when_software_payload_is_null():
    user = SimpleNamespace(id=uuid.uuid4())
    service = MagicMock()
    service.list_my_purchases = AsyncMock(
        return_value=[
            {
                "id": str(uuid.uuid4()),
                "software": None,
                "paymentStatus": "COMPLETED",
                "completionStatus": "CONFIRMED",
            },
            {
                "id": str(uuid.uuid4()),
                "software": {"name": "CRM"},
                "paymentStatus": "COMPLETED",
                "completionStatus": "ACTIVE",
                "isTechnologyService": True,
            },
        ]
    )

    app = FastAPI()
    app.include_router(alias.router, prefix="/api/v1/technology")

    async def override_user():
        return user

    async def override_db():
        yield MagicMock()

    async def override_service():
        return service

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_async_db] = override_db
    app.dependency_overrides[alias.get_cocreation_service] = override_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/technology/my-purchases")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert len(body["data"]) == 2
    ApiResponse.model_validate(body)
