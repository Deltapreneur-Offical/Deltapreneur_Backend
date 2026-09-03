"""User-safe ResellerClub / HTTP API error messages (no HTML dumps)."""

from __future__ import annotations

import re

from app.core.config import settings

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _looks_like_html(text: str) -> bool:
    lower = text.lower()
    return (
        "<!doctype html" in lower
        or "<html" in lower
        or "cloudflare" in lower
        or "attention required" in lower
        or "<head" in lower
    )


def _strip_html(text: str) -> str:
    cleaned = _HTML_TAG_RE.sub(" ", text or "")
    return " ".join(cleaned.split())


def user_message_for_http(status_code: int, body_text: str) -> str:
    raw = (body_text or "").strip()
    lower = raw.lower()
    panel = settings.resellerclub_control_panel_url()
    env = "sandbox" if settings.resellerclub_use_sandbox() else "production"
    api_base = settings.resolved_resellerclub_api_base()

    if status_code == 403 or _looks_like_html(raw) or "access denied" in lower:
        return (
            "ResellerClub blocked the server request (HTTP 403). "
            f"Open {panel} → Settings → API and whitelist your backend server's public IP. "
            f"Use RESELLERCLUB_ENV={env} with {api_base} and matching panel keys."
        )

    if status_code == 401 or "invalid credentials" in lower or "inactive or suspended" in lower:
        return (
            "ResellerClub rejected the API credentials. "
            f"Verify RESELLERCLUB_RESELLER_ID and RESELLERCLUB_API_KEY for {env} mode."
        )

    preview = _strip_html(raw)[:180]
    if preview:
        return f"ResellerClub request failed (HTTP {status_code}): {preview}"
    return f"ResellerClub request failed (HTTP {status_code}). Check panel API settings."


def format_registrar_http_error(operation: str, status_code: int, body_text: str) -> str:
    summary = user_message_for_http(status_code, body_text)
    return f"ResellerClub {operation} failed (HTTP {status_code}). {summary}"
