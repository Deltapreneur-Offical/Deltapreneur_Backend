"""GSTIN verification — integration layer tests."""

from __future__ import annotations

import os

import httpx
import pytest

from app.integrations.gstin.gst_verification import (
    GstinResult,
    _live_verify,
    _sandbox_verify,
    verify_gstin,
)

VALID_GSTIN = "27AAAAP0267H2ZN"
OTHER_COMPANY = "GP PARSIK SAHAKARI BANK LIMITED"


# ── gst_verification (format + sandbox + mocked live API) ─────────────────────


def test_sandbox_verify_uses_brand_hint() -> None:
    result = _sandbox_verify(VALID_GSTIN, trade_name_hint="Demo Traders")
    assert result.active is True
    assert result.trade_name == "Demo Traders"


def test_sandbox_verify_default_name_without_hint() -> None:
    result = _sandbox_verify(VALID_GSTIN)
    assert result.active is True
    assert result.trade_name == "SANDBOX BUSINESS (AAAAP0267H)"


def test_sandbox_verify_rejects_bad_format() -> None:
    result = _sandbox_verify("NOT-A-GSTIN")
    assert result.active is False
    assert "format" in (result.error_message or "").lower()


@pytest.mark.asyncio
async def test_verify_gstin_rejects_short_input() -> None:
    result = await verify_gstin("123")
    assert result.active is False
    assert result.error_message


@pytest.mark.asyncio
async def test_live_verify_success_parses_trade_name(monkeypatch) -> None:
    body = {
        "flag": True,
        "data": {"tradeNam": "ACME TRADERS", "sts": "Active"},
    }

    class FakeResponse:
        status_code = 200

        def json(self) -> dict:
            return body

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url: str):
            return FakeResponse()

    monkeypatch.setattr(
        "app.integrations.gstin.gst_verification._api_key",
        lambda: "test-key",
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())

    result = await _live_verify(VALID_GSTIN)
    assert result.active is True
    assert result.trade_name == "ACME TRADERS"


@pytest.mark.asyncio
async def test_live_verify_cancelled_status(monkeypatch) -> None:
    body = {
        "flag": True,
        "data": {"tradeNam": OTHER_COMPANY, "sts": "Cancelled"},
    }

    class FakeResponse:
        status_code = 200

        def json(self) -> dict:
            return body

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url: str):
            return FakeResponse()

    monkeypatch.setattr(
        "app.integrations.gstin.gst_verification._api_key",
        lambda: "test-key",
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())

    result = await _live_verify(VALID_GSTIN)
    assert result.active is False
    assert "cancelled" in (result.error_message or "").lower()


@pytest.mark.asyncio
async def test_live_verify_credit_expire_message(monkeypatch) -> None:
    body = {
        "flag": False,
        "message": "Credit Expire.",
        "errorCode": "CREDIT_NOT_AVAILABLE",
    }

    class FakeResponse:
        status_code = 200

        def json(self) -> dict:
            return body

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url: str):
            return FakeResponse()

    monkeypatch.setattr(
        "app.integrations.gstin.gst_verification._api_key",
        lambda: "test-key",
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())

    result = await _live_verify(VALID_GSTIN)
    assert result.active is False
    assert "expired" in (result.error_message or "").lower()


@pytest.mark.asyncio
async def test_live_verify_invalid_api_key_401(monkeypatch) -> None:
    class FakeResponse:
        status_code = 401

        def json(self) -> dict:
            return {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url: str):
            return FakeResponse()

    monkeypatch.setattr(
        "app.integrations.gstin.gst_verification._api_key",
        lambda: "bad-key",
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())

    result = await _live_verify(VALID_GSTIN)
    assert result.active is False
    assert "invalid" in (result.error_message or "").lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_live_gstin_api_optional_real_call() -> None:
    """Hit gstincheck only when GSTIN_RUN_LIVE_TEST=1 and GSTIN_API_KEY is set."""
    if os.environ.get("GSTIN_RUN_LIVE_TEST") != "1":
        pytest.skip("Set GSTIN_RUN_LIVE_TEST=1 to run live GSTIN API test")

    from app.core.config import settings

    if not settings.GSTIN_API_KEY.strip() or settings.gstin_sandbox_enabled():
        pytest.skip("Live GSTIN API key required; GSTIN_API_SANDBOX must be false")

    result = await _live_verify(VALID_GSTIN)
    # Real GSTIN from public samples — expect active or a clear provider error, not crash
    assert result.error_message is not None or result.trade_name is not None
