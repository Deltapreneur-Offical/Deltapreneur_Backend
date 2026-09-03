"""Shared pytest configuration for the backend test suite."""

from __future__ import annotations

import sys
from pathlib import Path
import importlib
import os
import pytest
from dotenv import load_dotenv

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

load_dotenv(_BACKEND_ROOT / ".env", override=True)

from app.core.database import Base, _to_sync_url  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _import_entity_modules() -> None:
    """Import ORM entity modules so Base.metadata sees every table to create."""
    entity_root = Path(__file__).resolve().parents[1] / "entity"
    if not entity_root.exists():
        return

    # Import subpackages and entity files
    for module_path in sorted(entity_root.rglob("*.py")):
        if module_path.name == "__init__.py":
            continue
        relative_path = module_path.relative_to(entity_root).with_suffix("")
        module_name = ".".join(["app", "entity", *relative_path.parts])
        try:
            importlib.import_module(module_name)
        except Exception as err:
            logger_err = str(err)
            if "cannot import name" not in logger_err:
                pass


def _ensure_test_schema() -> None:
    """Create the SQLAlchemy schema for the active test database when pytest runs.

    SAFETY: this must NEVER fall back to settings.DATABASE_URL — that is the
    real (RDS) database. If TEST_DATABASE_URL is not set, do nothing and let
    the DB-backed suites skip.
    """
    database_url = (os.getenv("TEST_DATABASE_URL") or "").strip()
    if not database_url:
        from app.core.config import settings

        database_url = (getattr(settings, "TEST_DATABASE_URL", "") or "").strip()

    if not database_url:
        return

    from app.tests.db_safety import check_test_db_url_is_local

    error = check_test_db_url_is_local(database_url)
    if error:
        raise RuntimeError(error)

    try:
        _import_entity_modules()
        engine = create_engine(_to_sync_url(database_url), future=True)
        Base.metadata.create_all(bind=engine)
        engine.dispose()
    except Exception:
        # Keep test startup resilient when the test DB is unavailable during local runs.
        pass


_ensure_test_schema()

from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _relax_bot_protection_for_tests(monkeypatch):
    """Turnstile and empty User-Agent checks should not block unit tests."""
    from app.core import bot_protection
    from app.core.config import settings

    monkeypatch.setattr(settings, "TURNSTILE_SECRET_KEY", "")
    monkeypatch.setattr(settings, "TURNSTILE_SITE_KEY", "")
    monkeypatch.setattr(bot_protection, "is_blocked_user_agent", lambda _ua: False)


@pytest.fixture
def client():
    return TestClient(app)
