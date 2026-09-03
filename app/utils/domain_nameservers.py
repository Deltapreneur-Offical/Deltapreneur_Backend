"""Canonical parsing/persistence for ``DomainRegistrationOrder.custom_nameservers``.

The column has accumulated several historical formats:

- Canonical JSON dict: ``{"hosts": [...], "source": "openprovider", "syncedAt": "..."}``
- JSON list of hosts: ``["ns1.example.com", "ns2.example.com"]``
- JSON string / raw comma-separated string: ``"ns1.example.com,ns2.example.com"``
  (written by the legacy manual nameserver-update path)

This module is the single reader/writer so every consumer (DNS validation,
DNSSEC eligibility, order detail payloads) sees the same hosts. All writes go
through :func:`set_order_nameservers`, which always persists the canonical
JSON dict shape.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable

_HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

if TYPE_CHECKING:
    from app.entity.domain.domain_registration_order_entity import (
        DomainRegistrationOrder,
    )


def normalize_nameserver_host(host: object) -> str:
    """Lowercase, trim whitespace, and strip the trailing FQDN dot."""
    return str(host or "").strip().rstrip(".").lower()


def _clean_hosts(hosts: Iterable[object]) -> list[str]:
    cleaned: list[str] = []
    for host in hosts:
        normalized = normalize_nameserver_host(host)
        if normalized and normalized not in cleaned:
            cleaned.append(normalized)
    return cleaned


def parse_order_nameservers(
    order: "DomainRegistrationOrder",
) -> tuple[list[str], str | None]:
    """Parse ``order.custom_nameservers`` in any historical format.

    Returns ``(hosts, source)`` where hosts are normalized (lowercase, no
    trailing dot) and deduplicated. An empty list means "no explicit
    nameservers stored" — callers treat that as platform defaults.
    """
    raw = order.custom_nameservers
    if not raw:
        return [], None
    raw = str(raw).strip()
    if not raw:
        return [], None

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = None

    if isinstance(data, dict):
        hosts = data.get("hosts")
        if isinstance(hosts, list):
            source = str(data.get("source") or "").strip() or None
            return _clean_hosts(hosts), source
        return [], None
    if isinstance(data, list):
        return _clean_hosts(data), "custom"
    if isinstance(data, str):
        return _parse_host_string(data), "custom"

    # Not JSON: legacy raw comma-separated string (also handles a single host).
    return _parse_host_string(raw), "custom"


def _parse_host_string(raw: str) -> list[str]:
    """Split a comma-separated string, keeping only hostname-shaped tokens so
    malformed values never masquerade as custom nameservers."""
    hosts = _clean_hosts(raw.split(","))
    return [h for h in hosts if _HOSTNAME_RE.match(h)]


def set_order_nameservers(
    order: "DomainRegistrationOrder",
    hosts: Iterable[object],
    source: str,
) -> None:
    """Persist nameservers in the canonical JSON format.

    ``syncedAt`` records when this value was captured, which makes stale-data
    investigations (like the ResellerClub → OpenProvider migration issue)
    diagnosable without a schema migration.
    """
    order.custom_nameservers = json.dumps(
        {
            "hosts": _clean_hosts(hosts),
            "source": source,
            "syncedAt": datetime.now(timezone.utc).isoformat(),
        }
    )
