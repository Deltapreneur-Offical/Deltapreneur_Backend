"""DNS second-level label sanitizers for Domain Register search.

Spaces, punctuation, and non-ASCII characters are dropped so a typed phrase
becomes a valid SLD (e.g. "a coffee shop near collage" → acoffeeshopnearcollage).
Does not convert spaces to hyphens. AI Brand Names should keep the raw idea.
"""

from __future__ import annotations

_SLD_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")
_EXT_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-")
_SLD_MAX = 63


def sanitize_sld(raw: str | None) -> str:
    """Return a DNS-safe second-level label, or empty if nothing usable remains."""
    text = str(raw or "").strip().lower()
    if "." in text:
        text = text.split(".", 1)[0]
    cleaned = "".join(ch for ch in text if ch in _SLD_CHARS)
    return cleaned.strip("-")[:_SLD_MAX]


def sanitize_extension(raw: str | None) -> str:
    """Return the extension after the first dot, stripped to safe TLD characters."""
    text = str(raw or "").strip().lower()
    if "." not in text:
        return ""
    ext = text.split(".", 1)[1]
    cleaned = "".join(ch for ch in ext if ch in _EXT_CHARS)
    return cleaned.strip(".-")


def compose_search_fqdn(raw: str | None, default_ext: str = "com") -> str:
    """Build name.tld for Domain Register. Bare phrases default to ``default_ext``."""
    name = sanitize_sld(raw)
    if not name:
        return ""
    ext = sanitize_extension(raw) or sanitize_sld(default_ext) or "com"
    return f"{name}.{ext}"
