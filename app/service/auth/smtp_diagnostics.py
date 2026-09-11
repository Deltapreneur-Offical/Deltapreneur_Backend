"""Safe SMTP diagnostics for transactional mail.

This module intentionally never returns or logs SMTP passwords, API keys, or
other secrets. It is shared by the local script and admin diagnostic endpoint so
both paths exercise the same configuration that normal backend mail uses.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Any

from app.core import config as config_module
from app.core.config import settings
from app.utils.email_mask import mask_email

logger = logging.getLogger(__name__)


def safe_mail_config_diagnostic() -> dict[str, Any]:
    """Return non-secret mail configuration state."""
    return {
        "MAIL_SERVER configured": bool((settings.MAIL_SERVER or "").strip()),
        "MAIL_PORT": settings.MAIL_PORT,
        "MAIL_USERNAME configured": bool((settings.MAIL_USERNAME or "").strip()),
        "MAIL_PASSWORD configured": bool((settings.MAIL_PASSWORD or "").strip()),
        "MAIL_FROM": settings.MAIL_FROM,
        "MAIL_REPLY_TO": settings.MAIL_REPLY_TO,
        "MAIL_FROM_NAME": settings.MAIL_FROM_NAME,
        "MAIL_STARTTLS": settings.MAIL_STARTTLS,
        "MAIL_SSL_TLS": settings.MAIL_SSL_TLS,
        "settings.mail_configured()": settings.mail_configured(),
    }


def local_runtime_context() -> dict[str, Any]:
    """Return local runtime context without secrets."""
    return {
        "env_file": str(getattr(config_module, "_BACKEND_ENV_FILE", Path(".env"))),
        "env_file_exists": Path(getattr(config_module, "_BACKEND_ENV_FILE", Path(".env"))).is_file(),
        "environment": settings.ENVIRONMENT,
        "backend_base_url": settings.BACKEND_BASE_URL,
        "frontend_base_url": settings.FRONTEND_BASE_URL,
    }


def _tls_mode() -> str:
    if settings.MAIL_SSL_TLS:
        return "SSL/TLS"
    if settings.MAIL_STARTTLS:
        return "STARTTLS"
    return "plain"


_TRUSTSTORE_INJECTED = False


def ensure_truststore_for_mail_tls() -> None:
    """Prefer the OS certificate store for SMTP TLS verification."""
    global _TRUSTSTORE_INJECTED
    if not settings.MAIL_VALIDATE_CERTS or _TRUSTSTORE_INJECTED:
        return
    try:
        import truststore
    except Exception:
        return
    truststore.inject_into_ssl()
    _TRUSTSTORE_INJECTED = True


def _ssl_context() -> ssl.SSLContext:
    if settings.MAIL_VALIDATE_CERTS:
        ensure_truststore_for_mail_tls()
        return ssl.create_default_context()
    return ssl._create_unverified_context()  # noqa: SLF001


def _sanitize_exception_text(text: str) -> str:
    sanitized = str(text or "")
    for secret in (
        settings.MAIL_PASSWORD,
        settings.resolved_mail_domains_password(),
    ):
        if secret:
            sanitized = sanitized.replace(secret, "[redacted]")
    return sanitized


def safe_exception_payload(exc: BaseException) -> dict[str, Any]:
    """Return exact non-secret SMTP exception details."""
    payload: dict[str, Any] = {
        "exception_type": type(exc).__name__,
        "exception": _sanitize_exception_text(str(exc)),
    }
    if isinstance(exc, smtplib.SMTPResponseException):
        payload["smtp_code"] = exc.smtp_code
        smtp_error = exc.smtp_error
        if isinstance(smtp_error, bytes):
            smtp_error_text = smtp_error.decode("utf-8", errors="replace")
        else:
            smtp_error_text = str(smtp_error)
        payload["smtp_error"] = _sanitize_exception_text(smtp_error_text)
    return payload


def run_smtp_connectivity_test(to_email: str | None = None) -> dict[str, Any]:
    """Connect, TLS, authenticate, and send one diagnostic email."""
    recipient = (to_email or settings.resolved_mail_reply_to() or settings.MAIL_FROM).strip()
    result: dict[str, Any] = {
        "success": False,
        "smtp_server": settings.MAIL_SERVER,
        "smtp_port": settings.MAIL_PORT,
        "tls_mode": _tls_mode(),
        "sender": settings.MAIL_FROM,
        "reply_to": settings.resolved_mail_reply_to(),
        "recipient": mask_email(recipient),
        "username_configured": bool((settings.MAIL_USERNAME or "").strip()),
        "password_configured": bool((settings.MAIL_PASSWORD or "").strip()),
        "mail_configured": settings.mail_configured(),
        "message_id": None,
        "refused_recipients": {},
    }
    if not settings.mail_configured():
        result["error"] = "Mail configuration is incomplete."
        return result

    message_id = make_msgid(domain=(settings.MAIL_FROM.split("@", 1)[-1] or None))
    message = EmailMessage()
    message["Subject"] = "Deltapreneur SMTP diagnostic"
    message["From"] = settings.MAIL_FROM
    message["To"] = recipient
    message["Reply-To"] = settings.resolved_mail_reply_to()
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = message_id
    message.set_content(
        "This is a backend SMTP diagnostic email from Deltapreneur. "
        "It confirms SMTP authentication and provider acceptance only."
    )
    result["message_id"] = message_id

    try:
        context = _ssl_context()
        if settings.MAIL_SSL_TLS:
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.MAIL_SERVER,
                settings.MAIL_PORT,
                timeout=20,
                context=context,
            )
        else:
            smtp = smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT, timeout=20)

        with smtp:
            smtp.ehlo()
            if settings.MAIL_STARTTLS and not settings.MAIL_SSL_TLS:
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            refused = smtp.send_message(message)
        result["refused_recipients"] = {
            mask_email(address): _sanitize_exception_text(str(reason))
            for address, reason in (refused or {}).items()
        }
        result["success"] = not bool(refused)
        result["smtp_accepted"] = result["success"]
        return result
    except Exception as exc:
        result.update(safe_exception_payload(exc))
        logger.error(
            "smtp.diagnostic.failed server=%s port=%s tls=%s sender=%s recipient=%s error_type=%s error=%s",
            settings.MAIL_SERVER,
            settings.MAIL_PORT,
            _tls_mode(),
            settings.MAIL_FROM,
            mask_email(recipient),
            type(exc).__name__,
            result.get("exception"),
        )
        return result
