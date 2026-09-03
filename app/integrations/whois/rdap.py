"""RDAP-based registrant email discovery for domain ownership verification."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ROLE_PRIORITY = (
    "registrant",
    "administrative",
)


def _normalize_email(value: str) -> str | None:
    raw = (value or "").strip().lower()
    if not raw or "@" not in raw:
        return None
    if raw.startswith("mailto:"):
        raw = raw[7:].strip()
    if _EMAIL_RE.match(raw):
        return raw
    return None


def _emails_from_vcard(vcard_array: list[Any]) -> list[str]:
    if not vcard_array or len(vcard_array) < 2:
        return []
    # vcardArray: ["vcard", [ [ "email", {}, "text", "x@y.com" ], ... ]]
    props = vcard_array[1] if isinstance(vcard_array[1], list) else []
    found: list[str] = []
    for item in props:
        if not isinstance(item, list) or len(item) < 4:
            continue
        if str(item[0]).lower() != "email":
            continue
        email = _normalize_email(str(item[3]))
        if email:
            found.append(email)
    return found


def _collect_entity_emails(entity: dict[str, Any]) -> dict[str, list[str]]:
    by_role: dict[str, list[str]] = {}
    roles = entity.get("roles") or []
    vcard = entity.get("vcardArray")
    emails = _emails_from_vcard(vcard) if isinstance(vcard, list) else []
    for role in roles:
        key = str(role).lower()
        by_role.setdefault(key, []).extend(emails)
    nested = entity.get("entities") or []
    for child in nested:
        if isinstance(child, dict):
            for role, addrs in _collect_entity_emails(child).items():
                by_role.setdefault(role, []).extend(addrs)
    return by_role


def pick_registrant_email(by_role: dict[str, list[str]]) -> str | None:
    """Return owner mailbox from registrant/admin roles only (skip registrar abuse contacts)."""
    seen: set[str] = set()
    for role in _ROLE_PRIORITY:
        for email in by_role.get(role, []):
            if email not in seen:
                seen.add(email)
                return email
    return None


async def lookup_registrant_email(fqdn: str, *, timeout: float = 15.0) -> str | None:
    """Return best registrant/admin email from RDAP, or None if unavailable/redacted."""
    fqdn = fqdn.strip().lower()
    url = f"https://rdap.org/domain/{fqdn}"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={"Accept": "application/rdap+json"})
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("RDAP lookup failed for %s: %s", fqdn, exc)
        return None

    by_role: dict[str, list[str]] = {}
    for entity in data.get("entities") or []:
        if isinstance(entity, dict):
            for role, emails in _collect_entity_emails(entity).items():
                by_role.setdefault(role, []).extend(emails)

    return pick_registrant_email(by_role)
