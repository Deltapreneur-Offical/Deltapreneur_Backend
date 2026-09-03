"""Import every ORM entity module so SQLAlchemy can resolve all relationships.

``app/tests/conftest.py`` normally does this (via ``_import_entity_modules``)
but its DB-safety guard refuses to load when ``TEST_DATABASE_URL`` points at a
remote database. Unit tests that use mocks only can call
``ensure_entities_imported()`` to register the full mapper registry without
touching any database.
"""

from __future__ import annotations

import importlib
from pathlib import Path

_ENTITIES_IMPORTED = False


def ensure_entities_imported() -> None:
    global _ENTITIES_IMPORTED
    if _ENTITIES_IMPORTED:
        return
    entity_root = Path(__file__).resolve().parents[1] / "entity"
    if entity_root.exists():
        for module_path in sorted(entity_root.rglob("*.py")):
            if module_path.name == "__init__.py":
                continue
            relative = module_path.relative_to(entity_root).with_suffix("")
            module_name = ".".join(["app", "entity", *relative.parts])
            try:
                importlib.import_module(module_name)
            except Exception:
                pass
    _ENTITIES_IMPORTED = True
