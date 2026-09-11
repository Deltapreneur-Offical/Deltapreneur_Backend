"""White-label customer access for provider-powered technology services.

Field mapping (no new database column):

- ResellPortal ``service_id`` is stored on ``technology_subscriptions.provider_subscription_id``.
  Renew, upgrade, and cancel already use that column as the provider service instance id.
- ResellPortal ``order_id`` / ``provider_order_id`` is stored on ``provider_order_id`` when
  the provider actually returns one. Fabricated ``RSP-ORD-{user[:8]}`` / ``RSP-SUB-{user[:8]}``
  values are never treated as real identifiers.
- ``credentials_json`` holds encrypted JSON (``enc:v1:`` + Fernet). Legacy plaintext JSON
  is still readable. ``access_token`` is never included in customer-facing APIs, URLs,
  emails, or logs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException, status

from app.core.config import settings
from app.service.security.auth_code_encryption_service import decrypt_secret, encrypt_secret
from app.service.technology.technology_purchase_status import is_paid_payment

logger = logging.getLogger(__name__)

CREDENTIALS_ENC_PREFIX = "enc:v1:"
LINK_IN_BIO_SLUG = "link-in-bio"
LINK_IN_BIO_MANAGE_PATH = "/link-in-bio/manage"
SENSITIVE_CREDENTIAL_KEYS = {
    "access_token",
    "token",
    "api_token",
    "api_key",
    "secret",
    "password",
    "client_secret",
    "refresh_token",
}
SECRET_QUERY_KEYS = {"access_token", "token", "api_token", "api_key"}
CUSTOMER_EMAIL_BLOCKED_KEYS = {
    "access_token",
    "token",
    "api_token",
    "api_key",
    "client_secret",
    "refresh_token",
    "secret",
    "secret_key",
    "bearer",
    "bearer_token",
    "service_id",
    "subscription_id",
    "provider_subscription_id",
    "provider_order_id",
    "order_id",
    "client_id",
    "account_id",
    "instance_id",
    "user_id",
    "is_mock",
    "test_mode",
    "configured",
    "fallback",
}
CUSTOMER_ACCESS_URL_KEYS = {
    "access_url",
    "url",
    "login_url",
    "manage_url",
    "cpanel_url",
    "dashboard_url",
    "portal_url",
    "webmail_url",
    "loginurl",
    "accessurl",
}
URL_KEY_PREFERENCE = (
    "login_url",
    "loginurl",
    "access_url",
    "accessurl",
    "dashboard_url",
    "cpanel_url",
    "portal_url",
    "webmail_url",
    "url",
    "manage_url",
)
PLACEHOLDER_URL_HOSTS = {
    "example.com",
    "www.example.com",
    "example.net",
    "www.example.net",
    "example.org",
    "www.example.org",
    "example.test",
    "workspace.cobrother.com",
    "localhost",
    "127.0.0.1",
}
EMAIL_SKIP_METADATA_KEYS = {
    "custom_domain_supported",
    "provisioned_at",
    "created_at",
    "updated_at",
    "configured",
    "fallback",
    "is_mock",
    "test_mode",
}
PLACEHOLDER_VALUE_KEYS = {
    "package_code",
    "package",
    "link",
    "server_id",
    "port_id",
    "server",
    "port",
}
PLACEHOLDER_FIELD_VALUES = {
    "test-starter",
    "default",
    "placeholder",
    "n/a",
    "na",
    "todo",
    "tbd",
    "none",
    "null",
    "https://example.com",
    "http://example.com",
}
ACCESS_EMAIL_STATUS_PENDING = "PENDING"
ACCESS_EMAIL_STATUS_SENT = "SENT"
ACCESS_EMAIL_STATUS_FAILED = "FAILED"
ACCESS_EMAIL_STATUSES = {
    ACCESS_EMAIL_STATUS_PENDING,
    ACCESS_EMAIL_STATUS_SENT,
    ACCESS_EMAIL_STATUS_FAILED,
}


def is_link_in_bio(service_slug: Any) -> bool:
    normalized = str(service_slug or "").strip().lower().replace("_", "-")
    return normalized == LINK_IN_BIO_SLUG


def _nonempty_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def is_fabricated_provider_id(value: Any, user_id: Any = None) -> bool:
    """True for the historical local fallbacks RSP-ORD/{SUB}-{user_id[:8]}."""
    text = _nonempty_str(value)
    uid = _nonempty_str(user_id)
    if not text or not uid:
        return False
    prefix = uid[:8]
    return text in {f"RSP-ORD-{prefix}", f"RSP-SUB-{prefix}"}


def real_provider_service_id(payload: dict[str, Any] | None, *, user_id: Any = None) -> Optional[str]:
    """Return the provider service instance id, never a fabricated local fallback.

    Confirmed ResellPortal Link in Bio contract uses ``service_id``. Existing
    renew/upgrade/cancel callers store that value on ``provider_subscription_id``.
    """
    data = payload or {}
    for key in ("service_id", "provider_subscription_id", "subscription_id"):
        candidate = _nonempty_str(data.get(key))
        if candidate and not is_fabricated_provider_id(candidate, user_id):
            return candidate
    return None


def real_provider_order_id(payload: dict[str, Any] | None, *, user_id: Any = None) -> Optional[str]:
    data = payload or {}
    for key in ("provider_order_id", "order_id"):
        candidate = _nonempty_str(data.get(key))
        if candidate and not is_fabricated_provider_id(candidate, user_id):
            return candidate
    return None


def extract_provider_credentials(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload or {}
    creds = data.get("credentials")
    if isinstance(creds, dict) and creds:
        return dict(creds)
    client_creds = data.get("client_credentials")
    if isinstance(client_creds, dict) and client_creds:
        return dict(client_creds)
    return {}


def credential_log_fields(creds: dict[str, Any] | None) -> dict[str, Any]:
    """Safe summary for logs — never includes token values or the credentials object."""
    data = creds if isinstance(creds, dict) else {}
    keys = sorted(str(k) for k in data.keys() if str(k).lower() not in SENSITIVE_CREDENTIAL_KEYS)
    return {
        "credential_keys": keys,
        "has_access_token": any(str(k).lower() == "access_token" for k in data.keys()),
        "has_username": bool(_nonempty_str(data.get("username"))),
    }


def dump_provider_credentials(creds: dict[str, Any] | None) -> str:
    payload = json.dumps(creds or {}, separators=(",", ":"), sort_keys=True)
    return CREDENTIALS_ENC_PREFIX + encrypt_secret(payload)


def load_provider_credentials(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw).strip()
    if not text or text in {"{}", "null"}:
        return {}
    if text.startswith(CREDENTIALS_ENC_PREFIX):
        try:
            decrypted = decrypt_secret(text[len(CREDENTIALS_ENC_PREFIX) :])
            parsed = json.loads(decrypted)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            logger.warning("technology.credentials.decrypt_failed")
            return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def store_subscription_credentials(sub: Any, creds: dict[str, Any] | None) -> None:
    sub.credentials_json = dump_provider_credentials(creds or {})


def customer_frontend_origin() -> str:
    base = (getattr(settings, "FRONTEND_BASE_URL", None) or "").strip().rstrip("/")
    if base:
        return base
    return "https://deltapreneur.com"


def link_in_bio_manage_path(service_id: Any) -> Optional[str]:
    sid = _nonempty_str(service_id)
    if not sid:
        return None
    return f"{LINK_IN_BIO_MANAGE_PATH}?{urlencode({'service_id': sid})}"


def link_in_bio_manage_url(service_id: Any) -> Optional[str]:
    path = link_in_bio_manage_path(service_id)
    if not path:
        return None
    return f"{customer_frontend_origin()}{path}"


def is_safe_customer_url(url: Any) -> bool:
    text = _nonempty_str(url)
    if not text:
        return False
    lower = text.lower()
    if "resellportal" in lower:
        return False
    if "access_token=" in lower or "api_token=" in lower:
        return False
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return False
    host = (parts.netloc or "").lower().split(":", 1)[0]
    if host in PLACEHOLDER_URL_HOSTS:
        return False
    if host.endswith(".example.com") or host.endswith(".example.test") or host.endswith(".resellportal.com"):
        return False
    if "workspace.cobrother.com" in host:
        return False
    for key, _value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in SECRET_QUERY_KEYS:
            return False
    return True


def is_captured_payment(payment_status: Any) -> bool:
    return str(payment_status or "").strip().upper() == "CAPTURED"


def confirmation_manage_url(*, service_slug: Any, provider_service_id: Any) -> Optional[str]:
    """Customer Manage CTAs are retired. Always returns None."""
    return None


def confirmation_email_kwargs(sub: Any) -> dict[str, Any]:
    """Customer confirmation mail has no Manage CTA and no provider credentials."""
    return {}


def _strip_secret_query(url: str) -> Optional[str]:
    parts = urlsplit(url)
    host = (parts.netloc or "").lower()
    if "resellportal" in host or "resellportal" in url.lower():
        return None
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in SECRET_QUERY_KEYS
    ]
    cleaned = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))
    if not is_safe_customer_url(cleaned):
        return None
    return cleaned


def public_credentials(
    creds: dict[str, Any] | None,
    *,
    service_slug: Any,
    provider_service_id: Any = None,
    status: Any = None,
    payment_status: Any = None,
) -> dict[str, Any]:
    """Customer-visible credential subset. Never includes access_token."""
    out: dict[str, Any] = {}
    data = creds if isinstance(creds, dict) else {}
    for key, value in data.items():
        if str(key).lower() in SENSITIVE_CREDENTIAL_KEYS:
            continue
        if isinstance(value, str):
            if "resellportal" in value.lower():
                continue
            if str(key).lower() in CUSTOMER_ACCESS_URL_KEYS:
                cleaned = _strip_secret_query(value)
                if cleaned:
                    out[key] = cleaned
                continue
        out[key] = value

    if is_link_in_bio(service_slug):
        out.pop("access_url", None)
        out.pop("url", None)
        out.pop("login_url", None)
        out.pop("manage_url", None)
        out.pop("managePath", None)
    return out


def public_purchase_access_fields(sub: Any) -> dict[str, Any]:
    """Customer purchase-list fields. Never includes a Manage CTA or provider host."""
    return {
        "serviceSlug": getattr(sub, "service_slug", None),
        "providerServiceId": None,
        "managePath": None,
        "manageLabel": None,
    }


def serialize_customer_subscription(sub: Any) -> dict[str, Any]:
    payload = {
        "id": str(sub.id),
        "service_slug": sub.service_slug,
        "service_name": sub.service_name,
        "plan_code": sub.plan_code,
        "billing_cycle": sub.billing_cycle,
        "price": sub.price,
        "currency": sub.currency,
        "status": sub.status,
        "payment_status": getattr(sub, "payment_status", None),
        "credentials": {},
        "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "auto_renew": sub.auto_renew,
        "created_at": sub.created_at.isoformat() if getattr(sub, "created_at", None) else None,
    }
    return _reject_secret_payload(payload)


def _payload_contains_secret(payload: Any) -> bool:
    dumped = json.dumps(payload, default=str).lower()
    if "access_token" in dumped:
        return True
    if "resellportal.com" in dumped:
        return True
    return False


def _reject_secret_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if _payload_contains_secret(payload):
        logger.error("technology.customer_payload.secret_blocked")
        raise RuntimeError("Refusing to return provider secrets to the customer.")
    return payload


@dataclass(frozen=True)
class LinkInBioAccessDecision:
    allowed: bool
    http_status: int
    detail: str
    subscription: Any = None


def evaluate_link_in_bio_access(*, sub: Any, requester_user_id: Any) -> LinkInBioAccessDecision:
    """Ownership and activation gate. ``service_id`` is not authentication."""
    if sub is None:
        return LinkInBioAccessDecision(False, status.HTTP_404_NOT_FOUND, "Service not found")
    if getattr(sub, "is_deleted", False):
        return LinkInBioAccessDecision(False, status.HTTP_404_NOT_FOUND, "Service not found")
    if not is_link_in_bio(getattr(sub, "service_slug", None)):
        return LinkInBioAccessDecision(False, status.HTTP_404_NOT_FOUND, "Service not found")
    if str(getattr(sub, "user_id", "")) != str(requester_user_id):
        return LinkInBioAccessDecision(False, status.HTTP_404_NOT_FOUND, "Service not found")
    if not is_paid_payment(getattr(sub, "payment_status", None)):
        return LinkInBioAccessDecision(
            False,
            status.HTTP_403_FORBIDDEN,
            "This Link in Bio service is not available to manage.",
        )
    if str(getattr(sub, "status", "") or "").strip().upper() != "ACTIVE":
        return LinkInBioAccessDecision(
            False,
            status.HTTP_403_FORBIDDEN,
            "This Link in Bio service is not available to manage.",
        )
    return LinkInBioAccessDecision(True, status.HTTP_200_OK, "ok", subscription=sub)


def load_link_in_bio_subscription_by_service_id(db: Any, service_id: str) -> Any:
    from app.entity.technology_services.technology_subscription_entity import (
        TechnologySubscriptionEntity,
    )

    sid = _nonempty_str(service_id)
    if not sid:
        return None
    rows = (
        db.query(TechnologySubscriptionEntity)
        .filter(
            TechnologySubscriptionEntity.provider_subscription_id == sid,
            TechnologySubscriptionEntity.is_deleted == False,  # noqa: E712
        )
        .all()
    )
    for row in rows:
        if is_link_in_bio(getattr(row, "service_slug", None)):
            return row
    return None


def stored_provider_access_token(sub: Any) -> Optional[str]:
    """Server-side only. Never return this from a customer API."""
    creds = load_provider_credentials(getattr(sub, "credentials_json", None))
    token = creds.get("access_token")
    return _nonempty_str(token)


def link_in_bio_access_payload(*, sub: Any, service_id: str) -> dict[str, Any]:
    """Legacy helper kept for tests. Never includes Manage CTAs or secrets."""
    # Intentionally discard provider token — customer APIs must never receive it.
    _provider_token = stored_provider_access_token(sub)
    del _provider_token
    payload = {
        "allowed": True,
        "service_id": _nonempty_str(service_id),
        "service_name": getattr(sub, "service_name", None),
        "status": getattr(sub, "status", None),
        "payment_status": getattr(sub, "payment_status", None),
        "managePath": None,
        "manageLabel": None,
        "editorAvailable": False,
    }
    return _reject_secret_payload(payload)


def resolve_link_in_bio_access(db: Any, *, user_id: str, service_id: str) -> dict[str, Any]:
    sid = _nonempty_str(service_id)
    if not sid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="service_id is required")
    sub = load_link_in_bio_subscription_by_service_id(db, sid)
    decision = evaluate_link_in_bio_access(sub=sub, requester_user_id=user_id)
    if not decision.allowed:
        raise HTTPException(status_code=decision.http_status, detail=decision.detail)
    return link_in_bio_access_payload(sub=decision.subscription, service_id=sid)


CREDENTIAL_FIELD_LABELS = {
    "email": "Email",
    "password": "Password",
    "username": "Username",
    "user_name": "Username",
    "access_url": "Login URL",
    "login_url": "Login URL",
    "url": "Login URL",
    "manage_url": "Login URL",
    "cpanel_url": "cPanel URL",
    "cpanel_username": "cPanel Username",
    "dashboard_url": "Dashboard URL",
    "portal_url": "Portal URL",
    "webmail_url": "Webmail URL",
    "phone_number": "Phone Number",
    "server": "Server",
    "port": "Port",
    "iccid": "ICCID",
    "lpa_string": "LPA / Activation String",
    "smdp_address": "SM-DP+ Address",
    "license_key": "License Key",
    "activation_code": "Activation Code",
    "activation_key": "Activation Key",
    "access_token": "Access Token",
    "api_key": "API Key",
    "api_token": "API Token",
    "qr": "QR / Activation Information",
    "qr_code": "QR Code",
}


def _as_status_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value.value) if hasattr(value, "value") else str(value)


def _email_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%d %b %Y")
    text = str(value).strip()
    return text or None


def customer_display_name(user: Any) -> Optional[str]:
    if user is None:
        return None
    parts = [
        _nonempty_str(getattr(user, "firstname", None)),
        _nonempty_str(getattr(user, "lastname", None)),
    ]
    name = " ".join(part for part in parts if part)
    if name:
        return name
    return _nonempty_str(getattr(user, "username", None)) or _nonempty_str(getattr(user, "email", None))


def credentials_blob_present(raw: Any) -> bool:
    """True when a credentials payload was stored. Does not decrypt or return values."""
    if raw is None:
        return False
    if isinstance(raw, dict):
        return any(v not in (None, "", [], {}) for v in raw.values())
    text = str(raw).strip()
    if not text or text.lower() in {"{}", "null", "[]", "none"}:
        return False
    return True


def humanize_credential_key(key: Any) -> str:
    text = str(key or "").strip()
    if not text:
        return "Field"
    mapped = CREDENTIAL_FIELD_LABELS.get(text.lower())
    if mapped:
        return mapped
    return text.replace("_", " ").replace("-", " ").title()


def is_sensitive_credential_key(key: Any) -> bool:
    lowered = str(key or "").strip().lower()
    if lowered in SENSITIVE_CREDENTIAL_KEYS:
        return True
    if lowered in {"license_key", "activation_code", "activation_key", "secret_key"}:
        return True
    return lowered.endswith("_token") or lowered.endswith("_secret") or lowered.endswith("_password")


def _stringify_credential_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def admin_access_detail_fields(creds: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Service-specific stored fields only. Does not invent missing keys."""
    fields: list[dict[str, Any]] = []
    data = creds if isinstance(creds, dict) else {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if value in ([], {}):
            continue
        fields.append(
            {
                "key": str(key),
                "label": humanize_credential_key(key),
                "value": _stringify_credential_value(value),
                "sensitive": is_sensitive_credential_key(key),
            }
        )
    return fields


def _strict_production_email_filter() -> bool:
    """Omit known TEST-only credential values from production customer emails."""
    return str(getattr(settings, "ENVIRONMENT", "") or "").strip().lower() == "production"


def _is_blocked_email_key(key_lower: str) -> bool:
    if key_lower in CUSTOMER_EMAIL_BLOCKED_KEYS or key_lower in EMAIL_SKIP_METADATA_KEYS:
        return True
    if key_lower.endswith("_token") or key_lower.endswith("_secret") or key_lower.endswith("_api_key"):
        return True
    return False


def _is_placeholder_credential(key_lower: str, rendered: str) -> bool:
    lower = rendered.strip().lower()
    if key_lower in PLACEHOLDER_VALUE_KEYS and (
        lower in PLACEHOLDER_FIELD_VALUES or "example.com" in lower or "example.test" in lower
    ):
        return True
    if key_lower in {"server_id", "port_id", "server", "port"} and lower in {"0", "test"}:
        return True
    return False


def _is_test_only_production_value(rendered: str) -> bool:
    if not _strict_production_email_filter():
        return False
    lower = rendered.strip().lower()
    if "@example.com" in lower or "@example.test" in lower:
        return True
    if "test-starter" in lower:
        return True
    return False


def _pick_login_url(url_candidates: dict[str, str]) -> Optional[str]:
    for key in URL_KEY_PREFERENCE:
        if key in url_candidates:
            return url_candidates[key]
    return next(iter(url_candidates.values()), None)


def customer_access_email_fields(creds: dict[str, Any] | None) -> tuple[list[dict[str, str]], Optional[str]]:
    """Stored credential fields that are safe to send in the access email.

    Resolves login URL and credentials from THIS subscription blob only.
    Does not invent hosts, ResellPortal admin URLs, or provider tokens.
    """
    fields: list[dict[str, str]] = []
    url_candidates: dict[str, str] = {}
    seen_url_values: set[str] = set()
    data = creds if isinstance(creds, dict) else {}
    for key, value in data.items():
        key_text = str(key or "").strip()
        key_lower = key_text.lower()
        if not key_text or _is_blocked_email_key(key_lower):
            continue
        if value is None or value in ([], {}):
            continue
        if isinstance(value, str) and not value.strip():
            continue
        rendered = _stringify_credential_value(value)
        if rendered.lower().startswith("bearer "):
            continue
        if "resellportal" in rendered.lower():
            continue
        if _is_placeholder_credential(key_lower, rendered):
            continue
        if _is_test_only_production_value(rendered):
            continue
        if key_lower in CUSTOMER_ACCESS_URL_KEYS:
            cleaned = _strip_secret_query(rendered)
            if not cleaned:
                continue
            rendered = cleaned
            url_candidates[key_lower] = cleaned
            if rendered.lower() in seen_url_values:
                continue
            seen_url_values.add(rendered.lower())
        fields.append(
            {
                "key": key_text,
                "label": "Login email" if key_lower == "email" else humanize_credential_key(key_text),
                "value": rendered,
            }
        )
    return fields, _pick_login_url(url_candidates)


def access_email_payload(
    sub: Any,
    *,
    customer_name: str | None = None,
    allow_already_sent: bool = False,
) -> Optional[dict[str, Any]]:
    """Build backend-only access email data, decrypting credentials just-in-time."""
    if bool(getattr(sub, "access_email_sent", False)) and not allow_already_sent:
        return None
    if bool(getattr(sub, "is_deleted", False)):
        return None
    if str(getattr(sub, "status", "") or "").strip().upper() != "ACTIVE":
        return None
    if not is_captured_payment(getattr(sub, "payment_status", None)):
        return None
    creds = load_provider_credentials(getattr(sub, "credentials_json", None))
    fields, access_url = customer_access_email_fields(creds)
    if not fields:
        return None
    return {
        "customer_name": customer_name or "Customer",
        "service_name": getattr(sub, "service_name", None) or "Technology Service",
        "plan_name": str(getattr(sub, "plan_code", "") or "").replace("_", " ").title() or "Plan",
        "billing_cycle": getattr(sub, "billing_cycle", None) or "",
        "service_status": "Active",
        "activated_at": _email_date(getattr(sub, "current_period_start", None)),
        "purchase_date": _email_date(getattr(sub, "created_at", None)),
        "access_fields": fields,
        "access_url": access_url,
    }


def access_email_resend_block_reason(sub: Any, *, user: Any = None) -> Optional[str]:
    """Safe eligibility error for a manual admin resend. Never includes secrets."""
    if sub is None or bool(getattr(sub, "is_deleted", False)):
        return "Subscription not found"
    if str(getattr(sub, "status", "") or "").strip().upper() != "ACTIVE":
        return "Access email can only be sent for an active subscription."
    if not is_captured_payment(getattr(sub, "payment_status", None)):
        return "Access email can only be sent after payment is captured."
    if not credentials_blob_present(getattr(sub, "credentials_json", None)):
        return "Access information is not available."
    if not _nonempty_str(getattr(user, "email", None)):
        return "Customer email is not available."
    return None


def mark_access_email_sent(sub: Any) -> None:
    sub.access_email_sent = True
    sub.access_email_status = ACCESS_EMAIL_STATUS_SENT


def mark_access_email_failed(sub: Any) -> None:
    """Record a failed delivery without clearing a previous successful send."""
    if not bool(getattr(sub, "access_email_sent", False)):
        sub.access_email_status = ACCESS_EMAIL_STATUS_FAILED


async def deliver_admin_access_email(
    sub: Any,
    *,
    user: Any = None,
    allow_already_sent: bool = False,
) -> dict[str, Any]:
    """Send the existing access-email template. Never returns credential values."""
    from app.service.auth.mail_service import MailService

    reason = access_email_resend_block_reason(sub, user=user)
    if reason:
        return {
            "success": False,
            "error": reason,
            "access_email_status": access_email_delivery_status(sub) if sub is not None else ACCESS_EMAIL_STATUS_PENDING,
        }
    to_email = _nonempty_str(getattr(user, "email", None))
    payload = access_email_payload(
        sub,
        customer_name=customer_display_name(user) or to_email,
        allow_already_sent=allow_already_sent,
    )
    if payload is None:
        return {
            "success": False,
            "error": "Access information is not available to email.",
            "access_email_status": access_email_delivery_status(sub),
        }
    try:
        await MailService.send_technology_service_access_email(
            to_email=to_email,
            **payload,
        )
    except Exception:
        logger.exception("technology.access_email.send_failed sub=%s", getattr(sub, "id", None))
        mark_access_email_failed(sub)
        return {
            "success": False,
            "error": "Unable to send access email.",
            "access_email_status": access_email_delivery_status(sub),
        }
    mark_access_email_sent(sub)
    return {
        "success": True,
        "message": "Access email sent.",
        "access_email_status": ACCESS_EMAIL_STATUS_SENT,
        "access_email_sent": True,
    }


def access_email_delivery_status(sub: Any) -> str:
    if bool(getattr(sub, "access_email_sent", False)):
        return ACCESS_EMAIL_STATUS_SENT
    raw = str(getattr(sub, "access_email_status", "") or "").strip().upper()
    if raw == ACCESS_EMAIL_STATUS_FAILED:
        return ACCESS_EMAIL_STATUS_FAILED
    return ACCESS_EMAIL_STATUS_PENDING


def serialize_admin_subscription_list_item(sub: Any, *, user: Any = None) -> dict[str, Any]:
    """Admin list row. Never includes decrypted credential values."""
    email = _nonempty_str(getattr(user, "email", None)) if user is not None else None
    return {
        "id": str(getattr(sub, "id", "")),
        "user_id": getattr(sub, "user_id", None),
        "customer_name": customer_display_name(user) or email,
        "customer_email": email,
        "service_slug": getattr(sub, "service_slug", None),
        "service_name": getattr(sub, "service_name", None),
        "plan_code": getattr(sub, "plan_code", None),
        "billing_cycle": getattr(sub, "billing_cycle", None),
        "price": getattr(sub, "price", None),
        "currency": getattr(sub, "currency", None),
        "status": getattr(sub, "status", None),
        "payment_status": _as_status_str(getattr(sub, "payment_status", None)),
        "access_email_sent": bool(getattr(sub, "access_email_sent", False)),
        "access_email_status": access_email_delivery_status(sub),
        "provider_subscription_id": getattr(sub, "provider_subscription_id", None),
        "provider_order_id": getattr(sub, "provider_order_id", None),
        "provisioning_status": getattr(sub, "last_provider_status", None) or getattr(sub, "status", None),
        "has_access_information": credentials_blob_present(getattr(sub, "credentials_json", None)),
        "needs_review": bool(getattr(sub, "needs_review", False)),
        "needs_input": str(getattr(sub, "last_provider_status", "") or "") == "NEEDS_INPUT",
        "last_provider_status": getattr(sub, "last_provider_status", None),
        "last_provider_error": getattr(sub, "last_provider_error", None),
        "provision_attempts": getattr(sub, "provision_attempts", 0),
        "next_retry_at": (
            sub.next_retry_at.isoformat() if getattr(sub, "next_retry_at", None) else None
        ),
        "created_at": (
            sub.created_at.isoformat() if getattr(sub, "created_at", None) else None
        ),
    }


def filter_admin_subscriptions_by_email(rows: list[dict[str, Any]], email: str | None) -> list[dict[str, Any]]:
    needle = str(email or "").strip().lower()
    if not needle:
        return rows
    return [row for row in rows if needle in str(row.get("customer_email") or "").lower()]


def serialize_admin_access_details(sub: Any, *, user: Any = None, admin_id: Any = None) -> dict[str, Any]:
    creds = load_provider_credentials(getattr(sub, "credentials_json", None))
    fields = admin_access_detail_fields(creds)
    logger.info(
        "technology.admin.access_details.viewed admin=%s sub=%s keys=%s",
        admin_id,
        getattr(sub, "id", None),
        [field["key"] for field in fields],
    )
    email = _nonempty_str(getattr(user, "email", None)) if user is not None else None
    return {
        "subscription_id": str(getattr(sub, "id", "")),
        "customer_name": customer_display_name(user) or email,
        "customer_email": email,
        "service_name": getattr(sub, "service_name", None),
        "service_slug": getattr(sub, "service_slug", None),
        "provider_subscription_id": getattr(sub, "provider_subscription_id", None),
        "provider_order_id": getattr(sub, "provider_order_id", None),
        "access_available": bool(fields),
        "message": None if fields else "Access information not available",
        "fields": fields,
    }
