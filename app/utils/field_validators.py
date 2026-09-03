"""Reusable Pydantic field normalization and validation."""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

E164_PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")
GSTIN_RE = re.compile(r"^[0-9A-Z]{15}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_HTTP_SCHEMES = frozenset({"http", "https"})


def blank_to_none(value: str | None) -> str | None:
    """Treat '', '   ', and None as absent optional text."""
    if value is None:
        return None
    if not str(value).strip():
        return None
    return str(value).strip()


def normalize_optional_non_whitespace(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field} cannot be empty or whitespace only")
    return stripped


def normalize_http_url(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    # Use urlparse to detect if a scheme already exists.
    # startswith("http://") would turn "ftp://example.com" into
    # "https://ftp://example.com" which is wrong.
    pre_parsed = urlparse(raw)
    if pre_parsed.scheme:
        # A scheme was already present — validate it first.
        if pre_parsed.scheme.lower() not in _HTTP_SCHEMES:
            raise ValueError("URL must use http or https")
        # Valid http/https scheme already — fall through to full normalisation.
    else:
        # No scheme found; add https:// for user convenience (e.g. "www.example.com").
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in _HTTP_SCHEMES:
        raise ValueError("URL must use http or https")
    if not parsed.netloc:
        raise ValueError("URL must include a valid host")
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "",
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def normalize_optional_email(value: str | None) -> str | None:
    value = blank_to_none(value)
    if value is None:
        return None
    raw = value
    lowered = raw.lower()
    if len(lowered) > 255 or not EMAIL_RE.match(lowered):
        raise ValueError("Invalid email format")
    return lowered


def normalize_e164_phone(value: str | None) -> str | None:
    value = blank_to_none(value)
    if value is None:
        return None
    compact = re.sub(r"[\s\-().]", "", value)
    if not E164_PHONE_RE.match(compact):
        raise ValueError(
            "phone_number must be in E.164 format (e.g. +919876543210)"
        )
    return compact


def normalize_profile_phone(value: str | None) -> str | None:
    """Optional phone for profile: blank → None, 10-digit IN → +91…, else E.164."""
    value = blank_to_none(value)
    if value is None:
        return None
    compact = re.sub(r"[\s\-().]", "", value)
    if re.fullmatch(r"\d{10}", compact):
        compact = f"+91{compact}"
    return normalize_e164_phone(compact)


def normalize_gstin(value: str) -> str:
    normalized = value.strip().upper()
    if not GSTIN_RE.match(normalized):
        raise ValueError(
            "GSTIN must be exactly 15 uppercase alphanumeric characters"
        )
    return normalized

