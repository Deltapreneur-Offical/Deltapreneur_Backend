"""Email display helpers."""

from __future__ import annotations


def mask_email(email: str) -> str:
    """Mask local part for API responses, e.g. owner@example.com -> o***@example.com."""
    normalized = (email or "").strip().lower()
    if "@" not in normalized:
        return "***"
    local, _, domain = normalized.partition("@")
    if not local:
        return f"***@{domain}"
    visible = local[0]
    return f"{visible}***@{domain}"
