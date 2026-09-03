"""GSTIN format validation."""

from __future__ import annotations

import re

GSTIN_LENGTH = 15
GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")


def normalize_gstin(gstin: str) -> str:
    return gstin.strip().upper()


def validate_gstin_format(gstin: str) -> tuple[bool, str | None]:
    """Return (ok, error_message)."""
    if len(gstin) != GSTIN_LENGTH:
        return False, "GSTIN must be exactly 15 characters"
    if not GSTIN_PATTERN.match(gstin):
        return (
            False,
            "Invalid GSTIN format. Expected: 2-digit state code + PAN + entity + Z + check digit",
        )
    return True, None
