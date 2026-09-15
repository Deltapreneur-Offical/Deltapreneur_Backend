"""Optional page_size on the public OpenProvider showcase feed."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controller.domain.domain_controller import router as domain_router
from app.core.database import get_async_db, get_db
from app.core.exceptions import register_exception_handlers
from app.repository.showcase_domain_repository import ShowcaseDomainRepository


class _ShowcaseService:
    def __init__(self, items: list[dict]) -> None:
        self._items = items
        self.calls: list[dict] = []

    def read_only_mode(self) -> bool:
        return False

    async def table_available(self) -> bool:
        return True

    async def list_public(self, page_size=None):
        self.calls.append({"page_size": page_size})
        rows = list(self._items)
        if page_size is not None:
            rows = rows[:page_size]
        return rows, True


def _client(items: list[dict], monkeypatch):
    service = _ShowcaseService(items)

    class _Factory:
        def __init__(self, db) -> None:
            self._inner = service

        def read_only_mode(self):
            return self._inner.read_only_mode()

        async def table_available(self):
            return await self._inner.table_available()

        async def list_public(self, page_size=None):
            return await self._inner.list_public(page_size=page_size)

    monkeypatch.setattr(
        "app.controller.domain.domain_controller.ShowcaseDomainService",
        _Factory,
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(domain_router)
    app.dependency_overrides[get_async_db] = lambda: MagicMock()
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app), service


def _row(index: int) -> dict:
    return {
        "source": "openprovider_showcase",
        "showcaseId": f"id-{index:02d}",
        "domainName": f"alpha{index:02d}.com",
    }


def test_showcase_without_page_size_returns_all(monkeypatch) -> None:
    items = [_row(i) for i in range(1, 13)]
    client, service = _client(items, monkeypatch)
    res = client.get("/api/v1/domain/showcase")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["enabled"] is True
    assert "items" in body and "data" in body and "total" in body
    assert len(body["data"]) == 12
    assert body["total"] == 12
    assert body["data"][0]["domainName"] == "alpha01.com"
    assert service.calls == [{"page_size": None}]


def test_showcase_page_size_8_returns_first_eight(monkeypatch) -> None:
    items = [_row(i) for i in range(1, 13)]
    client, service = _client(items, monkeypatch)
    res = client.get("/api/v1/domain/showcase", params={"page_size": 8})
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert len(body["data"]) == 8
    assert [row["domainName"] for row in body["data"]] == [
        f"alpha{i:02d}.com" for i in range(1, 9)
    ]
    assert service.calls == [{"page_size": 8}]


@pytest.mark.asyncio
async def test_showcase_list_selected_sql_applies_limit() -> None:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    repo = ShowcaseDomainRepository(session)
    await repo.list_selected(limit=8)
    stmt = session.execute.await_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
    assert "LIMIT 8" in compiled
