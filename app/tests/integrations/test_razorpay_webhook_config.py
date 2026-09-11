"""Razorpay webhook secret resolution — no live network, no secret values."""

from app.core.config import Settings
from app.integrations.openprovider.client import validate_runtime


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


def test_resolved_webhook_secret_uses_razorpay_webhook_secret_only():
    s = _base_settings(
        RAZORPAY_WEBHOOK_SECRET="whsec_local",
        RAZORPAY_LIVE_WEBHOOK_SECRET="whsec_other",
    )
    assert s.resolved_razorpay_webhook_secret() == "whsec_local"


def test_resolved_webhook_secret_ignores_live_webhook_secret_alias():
    s = _base_settings(
        RAZORPAY_WEBHOOK_SECRET="",
        RAZORPAY_LIVE_WEBHOOK_SECRET="whsec_live_only",
    )
    assert s.resolved_razorpay_webhook_secret() == ""


def test_validate_runtime_warns_when_webhook_secret_missing(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "OPENPROVIDER_USE_SANDBOX", False)
    monkeypatch.setattr(settings, "OPENPROVIDER_USERNAME", "user")
    monkeypatch.setattr(settings, "OPENPROVIDER_PASSWORD", "pwd")
    monkeypatch.setattr(
        settings,
        "OPENPROVIDER_DEFAULT_NAMESERVERS",
        "ns1.example.com,ns2.example.com",
    )
    monkeypatch.setattr(Settings, "resolved_razorpay_key_id", lambda self: "rzp_live_x")
    monkeypatch.setattr(Settings, "resolved_razorpay_key_secret", lambda self: "sec")
    monkeypatch.setattr(Settings, "resolved_razorpay_webhook_secret", lambda self: "")
    monkeypatch.setattr(Settings, "openprovider_configured", lambda self: True)
    monkeypatch.setattr(Settings, "openprovider_use_sandbox", lambda self: False)

    report = validate_runtime(for_live_checkout=True)
    assert any("RAZORPAY_WEBHOOK_SECRET not set" in w for w in report["warnings"])


def test_validate_runtime_silent_when_webhook_secret_set(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "OPENPROVIDER_USE_SANDBOX", False)
    monkeypatch.setattr(settings, "OPENPROVIDER_USERNAME", "user")
    monkeypatch.setattr(settings, "OPENPROVIDER_PASSWORD", "pwd")
    monkeypatch.setattr(
        settings,
        "OPENPROVIDER_DEFAULT_NAMESERVERS",
        "ns1.example.com,ns2.example.com",
    )
    monkeypatch.setattr(Settings, "resolved_razorpay_key_id", lambda self: "rzp_live_x")
    monkeypatch.setattr(Settings, "resolved_razorpay_key_secret", lambda self: "sec")
    monkeypatch.setattr(Settings, "resolved_razorpay_webhook_secret", lambda self: "whsec_ok")
    monkeypatch.setattr(Settings, "openprovider_configured", lambda self: True)
    monkeypatch.setattr(Settings, "openprovider_use_sandbox", lambda self: False)

    report = validate_runtime(for_live_checkout=True)
    assert not any("RAZORPAY_WEBHOOK_SECRET not set" in w for w in report["warnings"])
    # Startup warning uses this same resolver; RAZORPAY_LIVE_WEBHOOK_SECRET is ignored.
