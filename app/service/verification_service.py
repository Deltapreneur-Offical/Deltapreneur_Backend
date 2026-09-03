"""
Person 4 — verification entrypoints (single import surface).

* :class:`DomainVerificationService` — marketplace listing ownership (DNS / email flow).
* :class:`VentureVerificationService` — GSTIN verification for venture listings.

Implementations live under ``app/service/domain/`` and ``app/service/venture/``.
"""

from __future__ import annotations

from app.service.domain.verification_service import DomainVerificationService
from app.service.venture.verification_service import VentureVerificationService

__all__ = ["DomainVerificationService", "VentureVerificationService"]
