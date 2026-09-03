"""Shared helpers for offset/limit list endpoints."""

from __future__ import annotations


def offset_limit(page: int, page_size: int) -> tuple[int, int]:
    """Return (offset, limit) for 1-based page numbers."""
    safe_page = max(1, page)
    safe_size = max(1, page_size)
    return max(0, (safe_page - 1) * safe_size), safe_size
