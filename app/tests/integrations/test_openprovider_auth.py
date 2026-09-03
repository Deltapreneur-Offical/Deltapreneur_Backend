"""Mocked OpenProvider auth hardening tests — no database, no real network."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from app.integrations.openprovider import client as op_client


@pytest.fixture(autouse=True)
def _reset_auth_state():
    op_client.reset_openprovider_auth_state_for_tests()
    yield
    op_client.reset_openprovider_auth_state_for_tests()


def _login_ok_body(*, token: str = "tok-1", expires_in: int | None = 3600) -> dict[str, Any]:
    data: dict[str, Any] = {"token": token}
    if expires_in is not None:
        data["expires_in"] = expires_in
    return {"code": 0, "data": data}


class _FakeResponse:
    def __init__(self, status_code: int, body: dict[str, Any] | str | None = None) -> None:
        self.status_code = status_code
        if body is None:
            self._body: dict[str, Any] | None = {}
            self.text = ""
        elif isinstance(body, str):
            self._body = None
            self.text = body
        else:
            self._body = body
            self.text = json.dumps(body)

    def json(self) -> dict[str, Any]:
        if self._body is None:
            raise json.JSONDecodeError("x", "x", 0)
        return self._body


@pytest.mark.asyncio
async def test_concurrent_auth_single_flight(monkeypatch):
    login_calls = {"n": 0}

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def post(self, url: str, **kwargs):
            assert "auth/login" in url
            login_calls["n"] += 1
            await asyncio.sleep(0.05)
            return _FakeResponse(200, _login_ok_body(token="shared"))

        async def request(self, *a, **k):
            raise AssertionError("unexpected")

    monkeypatch.setattr(op_client, "_base_url", lambda: "https://registrar.test")
    monkeypatch.setattr(op_client, "_username", lambda: "u")
    monkeypatch.setattr(op_client, "_password", lambda: "p")
    monkeypatch.setattr(op_client.httpx, "AsyncClient", FakeClient)

    tokens = await asyncio.gather(*[op_client._get_token() for _ in range(8)])
    assert login_calls["n"] == 1
    assert set(tokens) == {"shared"}


@pytest.mark.asyncio
async def test_token_reused_until_expiry(monkeypatch):
    login_calls = {"n": 0}

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def post(self, url: str, **kwargs):
            login_calls["n"] += 1
            return _FakeResponse(200, _login_ok_body(token=f"t{login_calls['n']}", expires_in=3600))

    monkeypatch.setattr(op_client, "_base_url", lambda: "https://registrar.test")
    monkeypatch.setattr(op_client, "_username", lambda: "u")
    monkeypatch.setattr(op_client, "_password", lambda: "p")
    monkeypatch.setattr(op_client.httpx, "AsyncClient", FakeClient)

    t1 = await op_client._get_token()
    t2 = await op_client._get_token()
    assert t1 == t2 == "t1"
    assert login_calls["n"] == 1

    op_client._token_expiry = 0.0
    t3 = await op_client._get_token()
    assert t3 == "t2"
    assert login_calls["n"] == 2


@pytest.mark.asyncio
async def test_expires_in_drives_token_expiry(monkeypatch):
    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def post(self, url: str, **kwargs):
            return _FakeResponse(200, _login_ok_body(expires_in=120))

    monkeypatch.setattr(op_client, "_base_url", lambda: "https://registrar.test")
    monkeypatch.setattr(op_client, "_username", lambda: "u")
    monkeypatch.setattr(op_client, "_password", lambda: "p")
    monkeypatch.setattr(op_client.httpx, "AsyncClient", FakeClient)

    before = __import__("time").time()
    await op_client._get_token()
    # 120s TTL minus 60s margin => ~60s remaining
    remaining = op_client._token_expiry - before
    assert 50 <= remaining <= 70


def test_response_is_auth_error_status_first():
    assert op_client._response_is_auth_error(_FakeResponse(401, {"code": 0})) is True
    assert op_client._response_is_auth_error(_FakeResponse(200, {"code": 0})) is False
    # 10005 must not be treated as recoverable invalid-token
    assert (
        op_client._response_is_auth_error(
            _FakeResponse(500, {"code": 10005, "desc": "Access denied."})
        )
        is False
    )
    # Structured auth code
    assert (
        op_client._response_is_auth_error(
            _FakeResponse(500, {"code": 196, "desc": "Token expired"})
        )
        is True
    )
    # Free-text alone without structured code must not classify
    assert (
        op_client._response_is_auth_error(
            _FakeResponse(500, "invalid token please login again")
        )
        is False
    )


@pytest.mark.asyncio
async def test_401_recovery_retries_once(monkeypatch):
    api_calls: list[str] = []
    login_calls = {"n": 0}

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def request(self, method, url, **kwargs):
            api_calls.append(kwargs.get("headers", {}).get("Authorization", ""))
            if len(api_calls) == 1:
                return _FakeResponse(401, {"code": 196, "desc": "invalid token"})
            return _FakeResponse(200, {"code": 0, "data": {"ok": True}})

        async def get(self, url, **kwargs):
            return await self.request("GET", url, **kwargs)

        async def post(self, url: str, **kwargs):
            # Distinguish login vs data: login JSON has username.
            if isinstance(kwargs.get("json"), dict) and "username" in (kwargs.get("json") or {}):
                login_calls["n"] += 1
                return _FakeResponse(200, _login_ok_body(token=f"tok-{login_calls['n']}"))
            return await self.request("POST", url, **kwargs)

    monkeypatch.setattr(op_client, "_base_url", lambda: "https://registrar.test")
    monkeypatch.setattr(op_client, "_username", lambda: "u")
    monkeypatch.setattr(op_client, "_password", lambda: "p")
    monkeypatch.setattr(op_client.httpx, "AsyncClient", FakeClient)

    async with op_client._op_http_client(timeout=30.0) as client:
        resp = await client.get("https://registrar.test/v1beta/domains/prices")

    assert resp.status_code == 200
    assert len(api_calls) == 2
    assert api_calls[0] == "Bearer tok-1"
    assert api_calls[1] == "Bearer tok-2"
    assert login_calls["n"] == 2


@pytest.mark.asyncio
async def test_auth_retry_exactly_once_then_circuit(monkeypatch):
    api_calls = {"n": 0}
    login_calls = {"n": 0}

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def post(self, url: str, **kwargs):
            if isinstance(kwargs.get("json"), dict) and "username" in (kwargs.get("json") or {}):
                login_calls["n"] += 1
                return _FakeResponse(200, _login_ok_body(token=f"tok-{login_calls['n']}"))
            api_calls["n"] += 1
            return _FakeResponse(401, {"code": 196, "desc": "invalid token"})

        async def get(self, url, **kwargs):
            api_calls["n"] += 1
            return _FakeResponse(401, {"code": 196, "desc": "invalid token"})

    monkeypatch.setattr(op_client, "_base_url", lambda: "https://registrar.test")
    monkeypatch.setattr(op_client, "_username", lambda: "u")
    monkeypatch.setattr(op_client, "_password", lambda: "p")
    monkeypatch.setattr(op_client.httpx, "AsyncClient", FakeClient)

    async with op_client._op_http_client(timeout=30.0) as client:
        resp = await client.get("https://registrar.test/v1beta/x")

    assert resp.status_code == 401
    assert api_calls["n"] == 2  # original + one retry, never a third
    assert op_client._auth_in_cooldown() is True

    with pytest.raises(RuntimeError, match="circuit breaker"):
        await op_client._get_token()


@pytest.mark.asyncio
async def test_post_invalidation_single_flight(monkeypatch):
    login_calls = {"n": 0}

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def post(self, url: str, **kwargs):
            if isinstance(kwargs.get("json"), dict) and "username" in (kwargs.get("json") or {}):
                login_calls["n"] += 1
                await asyncio.sleep(0.05)
                if login_calls["n"] == 1:
                    return _FakeResponse(200, _login_ok_body(token="stale"))
                return _FakeResponse(200, _login_ok_body(token="fresh"))
            auth = kwargs.get("headers", {}).get("Authorization", "")
            if auth == "Bearer stale":
                return _FakeResponse(401, {"code": 196, "desc": "invalid token"})
            return _FakeResponse(200, {"code": 0, "data": {}})

        async def get(self, url, **kwargs):
            auth = kwargs.get("headers", {}).get("Authorization", "")
            if auth == "Bearer stale":
                return _FakeResponse(401, {"code": 196, "desc": "invalid token"})
            return _FakeResponse(200, {"code": 0, "data": {}})

    monkeypatch.setattr(op_client, "_base_url", lambda: "https://registrar.test")
    monkeypatch.setattr(op_client, "_username", lambda: "u")
    monkeypatch.setattr(op_client, "_password", lambda: "p")
    monkeypatch.setattr(op_client.httpx, "AsyncClient", FakeClient)

    # Prime cache with stale token
    assert await op_client._get_token() == "stale"

    async def one_call():
        async with op_client._op_http_client(timeout=30.0) as client:
            return await client.get("https://registrar.test/v1beta/x")

    results = await asyncio.gather(*[one_call() for _ in range(5)])
    assert all(r.status_code == 200 for r in results)
    # Initial login + exactly one refresh after invalidation (single-flight)
    assert login_calls["n"] == 2


@pytest.mark.asyncio
async def test_login_failure_opens_cooldown(monkeypatch):
    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def post(self, url: str, **kwargs):
            return _FakeResponse(401, {"code": 1, "desc": "bad credentials"})

    monkeypatch.setattr(op_client, "_base_url", lambda: "https://registrar.test")
    monkeypatch.setattr(op_client, "_username", lambda: "u")
    monkeypatch.setattr(op_client, "_password", lambda: "p")
    monkeypatch.setattr(op_client.httpx, "AsyncClient", FakeClient)

    with pytest.raises(RuntimeError, match="auth/login"):
        await op_client._get_token()

    assert op_client._auth_in_cooldown() is True

    # Second attempt must fail fast with no further HTTP (FakeClient would still work;
    # circuit raises before client construction).
    posts = {"n": 0}

    class CountingClient(FakeClient):
        async def post(self, url: str, **kwargs):
            posts["n"] += 1
            return await super().post(url, **kwargs)

    monkeypatch.setattr(op_client.httpx, "AsyncClient", CountingClient)
    with pytest.raises(RuntimeError, match="circuit breaker"):
        await op_client._get_token()
    assert posts["n"] == 0


@pytest.mark.asyncio
async def test_login_rate_limit_trips_circuit(monkeypatch):
    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def post(self, url: str, **kwargs):
            return _FakeResponse(200, _login_ok_body(token="x", expires_in=1))

    monkeypatch.setattr(op_client, "_base_url", lambda: "https://registrar.test")
    monkeypatch.setattr(op_client, "_username", lambda: "u")
    monkeypatch.setattr(op_client, "_password", lambda: "p")
    monkeypatch.setattr(op_client.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(op_client, "_LOGIN_RATE_LIMIT", 3)
    monkeypatch.setattr(op_client, "_LOGIN_RATE_WINDOW_SECONDS", 60.0)

    for _ in range(3):
        op_client._token = None
        op_client._token_expiry = 0.0
        await op_client._get_token()

    op_client._token = None
    op_client._token_expiry = 0.0
    with pytest.raises(RuntimeError, match="rate limit|circuit breaker"):
        await op_client._get_token()


@pytest.mark.asyncio
async def test_search_does_not_retry_auth_errors(monkeypatch):
    attempts = {"n": 0}

    monkeypatch.setattr(
        op_client, "_auth_headers", AsyncMock(return_value={"Authorization": "Bearer test"})
    )
    monkeypatch.setattr(op_client, "_base_url", lambda: "https://registrar.test")
    monkeypatch.setattr(op_client, "_DOMAIN_SEARCH_RETRIES", 4)
    monkeypatch.setattr(op_client, "_DOMAIN_SEARCH_CONCURRENCY", 1)
    monkeypatch.setattr(op_client, "_DOMAIN_SEARCH_BATCH_SIZE", 10)

    class FakeResponse:
        status_code = 401
        text = '{"code":196,"desc":"invalid token"}'

        def json(self):
            return {"code": 196, "desc": "invalid token"}

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def post(self, _url: str, *, headers=None, json=None):
            attempts["n"] += 1
            return FakeResponse()

        async def request(self, method, url, **kwargs):
            attempts["n"] += 1
            return FakeResponse()

        async def get(self, *a, **k):
            raise AssertionError("unexpected get")

    monkeypatch.setattr(op_client.httpx, "AsyncClient", FakeClient)

    with pytest.raises(RuntimeError, match="domains/check|auth"):
        await op_client._check_tld_batches("label", ["com", "net", "org"])

    # One batch → wrapper may do original+1 refresh = up to 2; must NOT be 4× transient retries.
    assert attempts["n"] <= 2
