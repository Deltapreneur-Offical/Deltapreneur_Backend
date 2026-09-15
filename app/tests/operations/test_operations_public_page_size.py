"""Optional page_size on the public operations catalog (homepage preview)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controller.operations.operations_service_controller import (
    _get_service,
    router as operations_router,
)
from app.core.database import get_async_db, get_db
from app.core.exceptions import register_exception_handlers
from app.repository.operations_service_repository import OperationsServiceRepository


class _OpsService:
    def __init__(self, items: list[dict]) -> None:
        self._items = items
        self.calls: list[dict] = []

    async def list_public(self, *, service_type=None, page_size=None):
        self.calls.append({"service_type": service_type, "page_size": page_size})
        rows = list(self._items)
        if service_type:
            rows = [row for row in rows if row.get("serviceType") == service_type]
        if page_size is not None:
            rows = rows[:page_size]
        return rows


def _client(items: list[dict]):
    service = _OpsService(items)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(operations_router)
    app.dependency_overrides[get_async_db] = lambda: MagicMock()
    app.dependency_overrides[get_db] = lambda: MagicMock()
    app.dependency_overrides[_get_service] = lambda: service
    return TestClient(app), service


def _row(index: int, service_type: str = "compliance") -> dict:
    return {
        "id": f"00000000-0000-0000-0000-0000000000{index:02d}",
        "name": f"Service {index:02d}",
        "serviceType": service_type,
        "displayOrder": index,
    }


def test_operations_without_page_size_returns_all_in_order() -> None:
    items = [_row(i) for i in range(1, 13)]
    client, service = _client(items)
    res = client.get("/api/v1/operations/services", params={"serviceType": "compliance"})
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert "data" in body and "items" in body
    assert len(body["data"]) == 12
    assert body["data"][0]["name"] == "Service 01"
    assert body["data"][-1]["name"] == "Service 12"
    assert service.calls == [{"service_type": "compliance", "page_size": None}]


def test_operations_page_size_8_returns_first_eight() -> None:
    items = [_row(i) for i in range(1, 13)]
    client, service = _client(items)
    res = client.get(
        "/api/v1/operations/services",
        params={"serviceType": "compliance", "page_size": 8},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert len(body["data"]) == 8
    assert [row["name"] for row in body["data"]] == [f"Service {i:02d}" for i in range(1, 9)]
    assert service.calls == [{"service_type": "compliance", "page_size": 8}]


@pytest.mark.asyncio
async def test_operations_list_public_sql_applies_limit() -> None:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    repo = OperationsServiceRepository(session)
    await repo.list_public(service_type="compliance", page_size=8)
    stmt = session.execute.await_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
    assert "LIMIT 8" in compiled
