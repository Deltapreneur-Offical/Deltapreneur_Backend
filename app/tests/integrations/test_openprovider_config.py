"""OpenProvider environment URL resolution."""

import pytest

from app.core.config import Settings


def _base_settings(**overrides):
    data = {
        "DATABASE_URL": "postgresql://u:p@localhost/db",
        "JWT_SECRET_KEY": "x" * 64,
        "JWT_ALGORITHM": "HS512",
        "JWT_ACCESS_TOKEN_EXPIRE_MS": 1,
        "JWT_REFRESH_TOKEN_EXPIRE_MS": 1,
        "JWT_REFRESH_TOKEN_PEPPER": "a" * 32,
        "JWT_REFRESH_TOKEN_PEPPER_KID": "v1",
        "MAIL_USERNAME": "m",
        "MAIL_PASSWORD": "m",
        "MAIL_FROM": "m",
        "MAIL_PORT": 587,
        "MAIL_SERVER": "smtp",
        "MAIL_STARTTLS": True,
        "MAIL_SSL_TLS": False,
        "MAIL_FROM_NAME": "n",
    }
    data.update(overrides)
    return Settings(**data)


def test_resolved_openprovider_sandbox_url(monkeypatch):
    monkeypatch.setenv("OPENPROVIDER_USE_SANDBOX", "true")
    s = _base_settings(
        OPENPROVIDER_USE_SANDBOX=True,
    )
    assert s.resolved_openprovider_api_base_url() == "http://api.sandbox.openprovider.nl:8480"
    assert s.openprovider_use_sandbox() is True


def test_resolved_openprovider_production_url(monkeypatch):
    monkeypatch.setenv("OPENPROVIDER_USE_SANDBOX", "false")
    monkeypatch.delenv("OPENPROVIDER_API_BASE_URL", raising=False)
    s = _base_settings(
        OPENPROVIDER_USE_SANDBOX=False,
        OPENPROVIDER_API_BASE_URL="https://api.openprovider.eu",
    )
    assert s.resolved_openprovider_api_base_url() == "https://api.openprovider.eu"
    assert s.openprovider_use_sandbox() is False


def test_openprovider_validation_blocks_test_razorpay_key(monkeypatch):
    from app.core.config import Settings
    monkeypatch.setattr(Settings, "resolved_razorpay_key_id", lambda self: "rzp_test_123")
    monkeypatch.setattr(Settings, "resolved_razorpay_key_secret", lambda self: "sec")
    monkeypatch.setattr(Settings, "openprovider_configured", lambda self: True)
    monkeypatch.setattr(Settings, "openprovider_use_sandbox", lambda self: False)

    from app.core.config import settings
    # temporarily patch other settings fields
    monkeypatch.setattr(settings, "OPENPROVIDER_USE_SANDBOX", False)
    monkeypatch.setattr(settings, "OPENPROVIDER_USERNAME", "user")
    monkeypatch.setattr(settings, "OPENPROVIDER_PASSWORD", "pwd")
    monkeypatch.setattr(settings, "OPENPROVIDER_DEFAULT_NAMESERVERS", "ns1.example.com,ns2.example.com")
    
    from app.integrations.openprovider.client import validate_runtime
    report = validate_runtime(for_live_checkout=True)
    assert report["ready"] is False
    assert any("Razorpay test keys" in issue for issue in report["blockingIssues"])


