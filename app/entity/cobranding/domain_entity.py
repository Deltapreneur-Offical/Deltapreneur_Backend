"""
Person 4 — marketplace domain ORM (Java ``Entity/cobranding`` ``Domain``).

Canonical model: :class:`DomainListing`. ``DomainEntity`` is an alias for
documentation parity with the role guide.
"""

from __future__ import annotations

from app.entity.cobranding.domain_listing_entity import DomainListing

DomainEntity = DomainListing

__all__ = ["DomainEntity", "DomainListing"]
