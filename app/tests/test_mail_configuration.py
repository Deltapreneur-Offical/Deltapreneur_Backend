"""Placeholder SMTP settings must count as unconfigured, not as working mail."""

from app.core.config import Settings, settings


def test_reserved_example_hosts_are_placeholders() -> None:
    assert Settings._is_placeholder_mail_host("smtp.example.com") is True
    assert Settings._is_placeholder_mail_host("  SMTP.Example.Com.  ") is True
    assert Settings._is_placeholder_mail_host("example.com") is True


def test_real_hosts_are_not_placeholders() -> None:
    assert Settings._is_placeholder_mail_host("smtp.gmail.com") is False
    assert Settings._is_placeholder_mail_host("smtp.zoho.in") is False
    assert Settings._is_placeholder_mail_host("smtp.notexample.com") is False


def test_mail_configured_rejects_placeholder_server() -> None:
    placeholder = settings.model_copy(
        update={
            "MAIL_SERVER": "smtp.example.com",
            "MAIL_USERNAME": "no-reply@example.com",
            "MAIL_PASSWORD": "secret",
            "MAIL_FROM": "no-reply@example.com",
        }
    )

    assert placeholder.mail_configured() is False


def test_mail_configured_accepts_real_server() -> None:
    configured = settings.model_copy(
        update={
            "MAIL_SERVER": "smtp.zoho.in",
            "MAIL_USERNAME": "support@deltapreneur.com",
            "MAIL_PASSWORD": "secret",
            "MAIL_FROM": "support@deltapreneur.com",
        }
    )

    assert configured.mail_configured() is True
