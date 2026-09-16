"""Shared markers for premium-listing CRM placeholders (not real buyer enquiries)."""

from __future__ import annotations

from typing import Any

LISTING_PIPELINE_FULL_NAME = "No buyer enquiry yet"
LISTING_PIPELINE_MESSAGE = "Listed premium domain (Pending buyer enquiry)"


def is_listing_pipeline_placeholder(
    source: Any = None,
    *,
    full_name: str | None = None,
    message: str | None = None,
    is_virtual: bool = False,
) -> bool:
    """True when this row is a listed-premium placeholder, not a buyer ticket."""
    if source is not None:
        if isinstance(source, dict):
            if source.get("isPlaceholder") is True or source.get("isVirtual") is True:
                return True
            full_name = source.get("fullName") if full_name is None else full_name
            if full_name is None:
                full_name = source.get("full_name")
            message = source.get("message") if message is None else message
            is_virtual = bool(source.get("isVirtual") or is_virtual)
        else:
            if getattr(source, "is_virtual", False) or getattr(source, "isVirtual", False):
                return True
            if full_name is None:
                full_name = getattr(source, "full_name", None)
            if message is None:
                message = getattr(source, "message", None)

    if is_virtual:
        return True
    return (
        str(full_name or "").strip() == LISTING_PIPELINE_FULL_NAME
        and str(message or "").strip() == LISTING_PIPELINE_MESSAGE
    )
