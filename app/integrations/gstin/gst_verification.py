"""GSTIN verification via sheet.gstincheck.co.in (Java parity)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.integrations.gstin.gst_validator import GSTIN_PATTERN, normalize_gstin, validate_gstin_format

BASE_URL = "https://sheet.gstincheck.co.in/check/{api_key}/{gstin}"
logger = logging.getLogger(__name__)


@dataclass
class GstinResult:
    active: bool
    trade_name: Optional[str] = None
    error_message: Optional[str] = None


def is_gstin_sandbox_mode() -> bool:
    return settings.gstin_sandbox_enabled()


def _api_key() -> str:
    return (settings.GSTIN_API_KEY or "").strip()


def _sandbox() -> bool:
    return is_gstin_sandbox_mode()


async def verify_gstin(gstin: str, *, trade_name_hint: str | None = None) -> GstinResult:
    normalized = normalize_gstin(gstin)
    ok, err = validate_gstin_format(normalized)
    if not ok:
        return GstinResult(active=False, error_message=err)

    if _sandbox():
        return _sandbox_verify(normalized, trade_name_hint=trade_name_hint)

    return await _live_verify(normalized)


def _sandbox_verify(gstin: str, *, trade_name_hint: str | None = None) -> GstinResult:
    if not GSTIN_PATTERN.match(gstin):
        return GstinResult(active=False, error_message="Invalid GSTIN format")
    name = (trade_name_hint or "").strip() or f"SANDBOX BUSINESS ({gstin[2:12]})"
    return GstinResult(active=True, trade_name=name)


async def _live_verify(gstin: str) -> GstinResult:
    api_key = _api_key()
    if not api_key:
        return GstinResult(
            active=False,
            error_message=(
                "GSTIN verification is not configured. Set GSTIN_API_KEY in .env "
                "or enable GSTIN_API_SANDBOX=true for local development."
            ),
        )

    url = BASE_URL.format(api_key=api_key, gstin=gstin)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
        if response.status_code == 401:
            return GstinResult(
                active=False,
                error_message="GSTIN API key is invalid. Contact support.",
            )
        if response.status_code != 200:
            return GstinResult(active=False, error_message="Unexpected response from GSTIN service")

        body: dict[str, Any] = response.json()
        if not body.get("flag"):
            msg = body.get("message")
            error_code = str(body.get("errorCode") or "").strip()
            if error_code == "CREDIT_NOT_AVAILABLE":
                msg_text = str(msg or "").strip().lower()
                if "expire" in msg_text:
                    return GstinResult(
                        active=False,
                        error_message=(
                            "GSTIN API key is expired or does not match your account. "
                            "Copy the current API key from gstincheck.co.in → Settings, "
                            "update GSTIN_API_KEY in .env / Render, then restart the backend."
                        ),
                    )
                return GstinResult(
                    active=False,
                    error_message=(
                        "GSTIN verification credits exhausted. "
                        "Top up at https://gstincheck.co.in/pricing.html"
                    ),
                )
            return GstinResult(
                active=False,
                error_message=str(msg) if msg else "GSTIN not found or invalid",
            )

        data = body.get("data")
        if not isinstance(data, dict):
            return GstinResult(
                active=False,
                error_message="Unexpected response structure from GSTIN service",
            )

        trade_name = data.get("tradeNam") or data.get("lgnm")
        sts = str(data.get("sts", "")).strip().lower()
        if sts and sts not in ("active", "provisional"):
            reason = (
                "GSTIN is cancelled"
                if "cancel" in sts
                else "GSTIN is suspended"
                if "suspend" in sts
                else f"GSTIN is not active (status: {sts})"
            )
            return GstinResult(active=False, error_message=reason, trade_name=trade_name)

        if not trade_name:
            return GstinResult(active=False, error_message="GSTIN not found. Please double-check the number.")
        return GstinResult(active=True, trade_name=str(trade_name))
    except Exception as exc:
        return GstinResult(active=False, error_message=f"GSTIN verification failed: {exc}")
