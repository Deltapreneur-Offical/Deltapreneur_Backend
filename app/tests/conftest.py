"""Shared pytest configuration for the backend test suite."""

from __future__ import annotations

import asyncio
import sys
import warnings
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


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Limiter windows are process-wide, so one test can 429 the next one."""
    from app.core.rate_limiter import limiter

    reset = getattr(limiter._storage, "reset", None)
    if callable(reset):
        reset()
    yield


def _current_event_loop_or_none():
    """The thread's current event loop, or None — never raises, never warns."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            return asyncio.get_event_loop_policy().get_event_loop()
        except RuntimeError:
            return None


@pytest.fixture(autouse=True)
def _keep_event_loop_available():
    """Keep a current event loop available to every later (async) test.

    ``asyncio.run()`` — used by some sync tests and by sync service code paths —
    ends with ``set_event_loop(None)``. pytest-asyncio's ``wrap_in_sync`` then
    calls ``get_event_loop()`` for every following async test and fails with
    ``RuntimeError: There is no current event loop in thread 'MainThread'``
    (Python 3.11 / pytest-asyncio 0.26). If a test leaves the thread without a
    current loop, put back the loop that was current before it (normally
    pytest-asyncio's session loop). A no-op in every other case.
    """
    loop_before = _current_event_loop_or_none()
    yield
    if (
        _current_event_loop_or_none() is None
        and loop_before is not None
        and not loop_before.is_closed()
    ):
        asyncio.set_event_loop(loop_before)


@pytest.fixture
def client():
    return TestClient(app)
