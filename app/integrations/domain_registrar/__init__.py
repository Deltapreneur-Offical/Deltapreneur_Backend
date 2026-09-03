"""Active domain registrar client (OpenProvider)."""

from __future__ import annotations

from types import ModuleType

from app.core.config import settings
from app.integrations.domain_registrar.protocol import DomainRegistrarClient


def active_registrar_module() -> ModuleType:
    from app.integrations.openprovider import client as mod

    return mod


def active_registrar() -> DomainRegistrarClient:
    """Typed facade over the active registrar module."""
    mod = active_registrar_module()
    return mod  # type: ignore[return-value]
