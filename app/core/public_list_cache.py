"""Short TTL cache for public homepage catalog lists.

Display-only. Never use for checkout, payments, quotes, or authz.
"""

from __future__ import annotations

import copy
import time
from typing import Any

_DEFAULT_TTL = 45.0
_store: dict[str, tuple[float, Any]] = {}


def public_list_cache_get(key: str) -> Any | None:
    entry = _store.get(key)
    if not entry:
        return None
    expiry, payload = entry
    if time.time() >= expiry:
        _store.pop(key, None)
        return None
    return copy.deepcopy(payload)


def public_list_cache_put(key: str, payload: Any, ttl: float = _DEFAULT_TTL) -> None:
    if ttl <= 0:
        return
    if len(_store) > 64:
        _store.clear()
    _store[key] = (time.time() + ttl, copy.deepcopy(payload))


def public_list_cache_clear(prefix: str | None = None) -> None:
    if prefix is None:
        _store.clear()
        return
    for key in [k for k in _store if k.startswith(prefix)]:
        _store.pop(key, None)
