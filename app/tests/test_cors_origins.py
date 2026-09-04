"""Deltapreneur CORS origin resolution. CoBrother/HubRegistrar must not be injected."""

from __future__ import annotations

import re

from app.core.config import settings


def test_production_cors_includes_deltapreneur_not_cobrother(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        settings,
        "CORS_ALLOW_ORIGINS",
        "https://deltapreneur.com,https://www.deltapreneur.com",
    )
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://deltapreneur.com")
    monkeypatch.setattr(settings, "BACKEND_BASE_URL", "https://api.deltapreneur.com")
    monkeypatch.setattr(settings, "CORS_ALLOW_ORIGIN_REGEX", "")

    origins = settings.resolved_cors_origins()
    assert "https://deltapreneur.com" in origins
    assert "https://www.deltapreneur.com" in origins
    assert "https://cobrother.com" not in origins
    assert "https://hubregistrar.com" not in origins

    regex = settings.resolved_cors_origin_regex()
    assert regex is not None
    pat = re.compile(regex)
    assert pat.match("https://deltapreneur.com")
    assert pat.match("https://www.deltapreneur.com")
    assert not pat.match("https://cobrother.com")
    assert not pat.match("https://hubregistrar.com")
    assert not pat.match("https://evil.example.com")


def test_cors_includes_deltapreneur_when_environment_is_not_production(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(settings, "CORS_ALLOW_ORIGINS", "https://preview.example")
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://deltapreneur.com")
    monkeypatch.setattr(settings, "BACKEND_BASE_URL", "https://api.deltapreneur.com")
    monkeypatch.setattr(settings, "CORS_ALLOW_ORIGIN_REGEX", "")

    origins = settings.resolved_cors_origins()
    assert "https://deltapreneur.com" in origins
    assert "https://www.deltapreneur.com" in origins
    assert "https://preview.example" in origins
    assert "https://cobrother.com" not in origins


def test_cors_regex_is_case_insensitive_for_production_environment(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "Production")
    monkeypatch.setattr(settings, "CORS_ALLOW_ORIGIN_REGEX", "")
    regex = settings.resolved_cors_origin_regex()
    assert regex is not None
    assert "deltapreneur" in regex
    assert "cobrother" not in regex
    assert "hubregistrar" not in regex
