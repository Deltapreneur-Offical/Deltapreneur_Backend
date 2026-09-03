"""HubRegistrar + CoBrother CORS origin resolution."""

from __future__ import annotations

import re

from app.core.config import settings


def test_production_cors_includes_hubregistrar_and_cobrother(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        settings,
        "CORS_ALLOW_ORIGINS",
        "https://cobrother.com,https://www.cobrother.com",
    )
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://cobrother.com")
    monkeypatch.setattr(settings, "BACKEND_BASE_URL", "https://backend.cobrother.com")
    monkeypatch.setattr(settings, "CORS_ALLOW_ORIGIN_REGEX", "")

    origins = settings.resolved_cors_origins()
    assert "https://hubregistrar.com" in origins
    assert "https://www.hubregistrar.com" in origins
    assert "https://cobrother.com" in origins
    assert "https://www.cobrother.com" in origins

    regex = settings.resolved_cors_origin_regex()
    assert regex is not None
    pat = re.compile(regex)
    assert pat.match("https://hubregistrar.com")
    assert pat.match("https://www.hubregistrar.com")
    assert pat.match("https://cobrother.com")
    assert pat.match("https://www.cobrother.com")
    assert not pat.match("https://evil.example.com")


def test_cors_includes_hubregistrar_when_environment_is_not_production(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(settings, "CORS_ALLOW_ORIGINS", "https://cobrother.com")
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://cobrother.com")
    monkeypatch.setattr(settings, "BACKEND_BASE_URL", "https://backend.cobrother.com")
    monkeypatch.setattr(settings, "CORS_ALLOW_ORIGIN_REGEX", "")

    origins = settings.resolved_cors_origins()
    assert "https://hubregistrar.com" in origins
    assert "https://www.hubregistrar.com" in origins
    assert "https://cobrother.com" in origins


def test_cors_regex_is_case_insensitive_for_production_environment(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "Production")
    monkeypatch.setattr(settings, "CORS_ALLOW_ORIGIN_REGEX", "")
    regex = settings.resolved_cors_origin_regex()
    assert regex is not None
    assert "hubregistrar" in regex
    assert "cobrother" in regex
