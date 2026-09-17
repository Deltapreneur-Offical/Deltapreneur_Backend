"""Auth must not keep a QueuePool checkout for the whole request."""

from unittest.mock import MagicMock

from fastapi import Request

from app.core.database import get_db
from app.core.dependencies import get_db as get_db_from_dependencies
from app.core.dependencies import get_optional_current_user


def test_get_db_still_exported_from_dependencies() -> None:
    assert get_db_from_dependencies is get_db


def test_optional_auth_skips_db_when_anonymous(monkeypatch) -> None:
    opened = []

    def fake_session_local():
        opened.append(True)
        raise AssertionError("anonymous requests must not open an auth DB session")

    monkeypatch.setattr("app.core.dependencies.SessionLocal", fake_session_local)

    request = MagicMock(spec=Request)
    request.cookies = {}
    request.method = "GET"

    assert get_optional_current_user(request, credentials=None) is None
    assert opened == []
