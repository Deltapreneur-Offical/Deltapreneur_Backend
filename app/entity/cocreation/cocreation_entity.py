"""
Person 4 — CoCreation marketplace ORM (Java ``Entity/cocreation`` ``Software``).

Canonical model: :class:`Software`. ``CocreationEntity`` is an alias for the
role guide filename ``cocreation_entity.py``.
"""

from __future__ import annotations

from app.entity.cocreation.software_entity import Software

CocreationEntity = Software

__all__ = ["CocreationEntity", "Software"]
