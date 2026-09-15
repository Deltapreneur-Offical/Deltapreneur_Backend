"""ResellPortal product mapper — centralized provider mapping for HubRegistrar services.

This module is the single source of truth for mapping HubRegistrar service slugs
to ResellPortal product_keys and building product-specific order parameters.

Validated via live ResellPortal TEST MODE on 2026-08-13.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# TLDs with more than one label (e.g. ``co.in``, ``com.au``) that must be
# stripped entirely when deriving a cpanel username from a domain.
_MULTI_LABEL_TLDS = {
    "co.in", "co.uk", "co.jp", "co.nz", "co.za", "com.au", "com.br", "com.cn",
    "com.hk", "com.mx", "com.sg", "com.tr", "net.au", "net.nz", "org.uk",
    "org.au", "org.nz", "gov.uk", "ac.uk", "co.kr", "com.tw", "com.vn",
    "com.my", "com.ph", "com.pk", "com.eg", "com.sa", "co.ke", "co.tz",
    "com.ng", "com.ar", "com.co", "com.pe", "com.uy", "com.ve", "com.ec",
    "com.gt", "com.ni", "com.do", "com.pr", "com.jm", "com.tt", "com.lk",
}

# Characters the provider's cpanel username may not contain.
_CPANEL_INVALID_CHARS = re.compile(r"[^a-z0-9]")

# Max length for a cpanel username (safe, provider-accepted length).
_CPANEL_MAX_LEN = 20


# Services that require customer-provided input before provider provisioning.
# Maps service_slug -> tuple of metadata keys required. A tuple of tuples means
# "any one of these groups is sufficient" (e.g. business-phone accepts an
# area_code OR a phone_number, not both).
REQUIRED_INPUT_KEYS: dict[str, tuple[tuple[str, ...], ...]] = {
    "ai-business-suite": (("aiTools",),),
    "business-phone": (("areaCode",), ("phoneNumber",)),
    "cloud-storage": (("storagePlan",),),
    "document-signer": (("companyName",),),
    "email-marketing": (("sendingPlan",), ("selectedPlan",), ("planCode",)),
    "invoice-ai": (("subdomain",),),
    "appointment-booking": (("subdomain",),),
    "smm-growth": (("serviceId", "link", "quantity"),),
    "esim": (("packageCode",),),
    "web-hosting": (("primaryDomain",),),
    "wordpress-plugin-pack": (("pluginName", "author", "description", "logoUrl"),),
}


# ---------------------------------------------------------------------------
# Static product_key mapping (DB-backed columns take precedence when present)
# ---------------------------------------------------------------------------

PRODUCT_KEY_MAP: dict[str, str] = {
    "ai-business-suite": "ai_business_tools",
    "website-builder": "website_builder",
    "web-hosting": "web_hosting",
    "cloud-storage": "cloud_storage",
    "email-marketing": "email_marketing",
    "esim": "esim",
    "smm-growth": "smm",
    "vpn": "vpn",
    "crm": "crm",
    "invoice-ai": "invoice_ai",
    "appointment-booking": "appointments",
    "document-signer": "docsign",
    "business-phone": "business_phone",
    "social-media-automation": "social_media_automation",
    "reputation-management": "reputation_management",
    "link-in-bio": "link_in_bio",
    "wordpress-plugin-pack": "wp_plugin_installer",
}

CONFIRMED_PRODUCT_KEYS: set[str] = set(PRODUCT_KEY_MAP.values())

_EMAIL_MARKETING_PLANS = {"starter", "growth", "pro", "business"}
_CLOUD_STORAGE_PLANS = {"50gb", "100gb", "200gb", "500gb", "1tb", "2tb"}


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item or "").strip()]
    return []


def _metadata_value(meta: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = meta.get(key)
        if value is not None and str(value).strip():
            return value
    return None


def _email_marketing_plan(
    plan_code: str = "",
    metadata: dict[str, Any] | None = None,
) -> str:
    meta = metadata or {}
    sending_plan = str(
        _metadata_value(meta, "sendingPlan", "sending_plan", "planCode", "selectedPlan", "plan_code")
        or plan_code
        or ""
    ).strip().lower()
    return sending_plan if sending_plan in _EMAIL_MARKETING_PLANS else ""


# ---------------------------------------------------------------------------
# Product-specific parameter builders
# ---------------------------------------------------------------------------

def _build_ai_business_tools_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = metadata or {}
    ai_tools = _coerce_str_list(meta.get("aiTools") or meta.get("ai_tools"))
    return {"ai_tools": ai_tools} if ai_tools else {}


def _build_website_builder_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {}


def _build_web_hosting_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = metadata or {}
    primary_domain = str(meta.get("primaryDomain") or "").strip().lower()
    params: dict[str, Any] = {}
    if primary_domain:
        params["primary_domain"] = primary_domain
    cpanel_username = str(meta.get("cpanelUsername") or "").strip()
    if cpanel_username:
        params["cpanel_username"] = cpanel_username
    elif primary_domain:
        derived = derive_cpanel_username(primary_domain)
        if derived:
            params["cpanel_username"] = derived
    plan = str(meta.get("plan") or plan_code or "").strip().lower()
    if primary_domain and plan:
        params["plan"] = plan
    return params


def _build_cloud_storage_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = metadata or {}
    storage_plan = str(meta.get("storagePlan") or meta.get("storage_plan") or "").strip().lower()
    if storage_plan not in _CLOUD_STORAGE_PLANS:
        return {}
    return {"storage_plan": storage_plan}


def _build_email_marketing_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sending_plan = _email_marketing_plan(plan_code, metadata)
    if sending_plan:
        return {"sending_plan": sending_plan}
    return {}


def _build_esim_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = metadata or {}
    package_code = str(meta.get("packageCode") or "").strip()
    return {"package_code": package_code} if package_code else {}


def _build_smm_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = metadata or {}
    service_id = str(meta.get("serviceId") or "").strip()
    link = str(meta.get("link") or "").strip()
    try:
        quantity = int(meta.get("quantity") or 0)
    except (TypeError, ValueError):
        quantity = 0
    params: dict[str, Any] = {}
    if service_id:
        params["service_id"] = service_id
    if link:
        params["link"] = link
    if quantity > 0:
        params["quantity"] = quantity
    return params


def _build_vpn_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = metadata or {}
    vpn_username = str(meta.get("vpnUsername") or "").strip()
    return {"vpn_username": vpn_username} if vpn_username else {}


def _build_crm_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = metadata or {}
    business_name = str(meta.get("businessName") or "").strip()
    if business_name:
        return {"business_name": business_name}
    return {}


def _build_invoice_ai_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = metadata or {}
    params: dict[str, Any] = {}
    subdomain = str(meta.get("subdomain") or "").strip()
    if subdomain:
        params["subdomain"] = subdomain
    for source_key, provider_key in (
        ("businessName", "business_name"),
        ("logoUrl", "logo_url"),
        ("primaryColor", "primary_color"),
    ):
        value = str(meta.get(source_key) or "").strip()
        if value:
            params[provider_key] = value
    return params


def _build_appointments_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = metadata or {}
    params: dict[str, Any] = {}
    subdomain = str(meta.get("subdomain") or "").strip()
    if subdomain:
        params["subdomain"] = subdomain
    for source_key, provider_key in (
        ("businessName", "business_name"),
        ("logoUrl", "logo_url"),
        ("primaryColor", "primary_color"),
        ("secondaryColor", "secondary_color"),
    ):
        value = str(meta.get(source_key) or "").strip()
        if value:
            params[provider_key] = value
    return params


def _build_docsign_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = metadata or {}
    company_name = str(meta.get("companyName") or meta.get("company_name") or "").strip()
    if company_name:
        return {"company_name": company_name}
    return {}


def _build_business_phone_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = metadata or {}
    phone_number = str(meta.get("phoneNumber") or "").strip()
    area_code = str(meta.get("areaCode") or "").strip()
    if phone_number:
        return {"phone_number": phone_number}
    if area_code:
        return {"area_code": area_code}
    # area_code="auto" is NOT valid for live purchases — the customer must
    # choose a specific area code. Returning {} lets the caller put the
    # purchase into a needs-input state instead of calling POST /orders.
    return {}


def _build_social_media_automation_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {}


def _build_reputation_management_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {}


def _build_link_in_bio_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {}


def _build_wp_plugin_installer_params(
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = metadata or {}
    mapping = {
        "pluginName": "plugin_name",
        "author": "author",
        "description": "description",
        "logoUrl": "logo_url",
    }
    params: dict[str, Any] = {}
    for source_key, provider_key in mapping.items():
        value = str(meta.get(source_key) or "").strip()
        if value:
            params[provider_key] = value
    return params


PARAM_BUILDERS: dict[str, Any] = {
    "ai_business_tools": _build_ai_business_tools_params,
    "website_builder": _build_website_builder_params,
    "web_hosting": _build_web_hosting_params,
    "cloud_storage": _build_cloud_storage_params,
    "email_marketing": _build_email_marketing_params,
    "esim": _build_esim_params,
    "smm": _build_smm_params,
    "vpn": _build_vpn_params,
    "crm": _build_crm_params,
    "invoice_ai": _build_invoice_ai_params,
    "appointments": _build_appointments_params,
    "docsign": _build_docsign_params,
    "business_phone": _build_business_phone_params,
    "social_media_automation": _build_social_media_automation_params,
    "reputation_management": _build_reputation_management_params,
    "link_in_bio": _build_link_in_bio_params,
    "wp_plugin_installer": _build_wp_plugin_installer_params,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_product_key(service_slug: str) -> str | None:
    """Return the ResellPortal product_key for a HubRegistrar service slug."""
    return PRODUCT_KEY_MAP.get(service_slug)


def is_confirmed_product_key(product_key: str | None) -> bool:
    """Return True only for product keys in the confirmed ResellPortal contract."""
    return str(product_key or "").strip() in CONFIRMED_PRODUCT_KEYS


def resolve_product_key(service_slug: str, configured_product_key: str | None = None) -> str | None:
    """Resolve the safe provider key for a catalogue service.

    The hard-coded contract mapping is authoritative for the 17 supported
    catalogue slugs. A DB override is accepted only for slugs that do not have
    a local mapping and only when the override itself is a confirmed provider
    key.
    """
    mapped = get_product_key(service_slug)
    if mapped:
        return mapped
    if is_confirmed_product_key(configured_product_key):
        return str(configured_product_key).strip()
    return None


def build_order_parameters(
    product_key: str,
    plan_code: str,
    billing_cycle: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build product-specific order parameters for a ResellPortal POST /orders call."""
    builder = PARAM_BUILDERS.get(product_key)
    if builder is None:
        logger.warning("No param builder registered for product_key=%s", product_key)
        return {}
    params = builder(plan_code, billing_cycle, metadata)
    return {k: v for k, v in params.items() if v is not None}


def is_provider_mapped(service_slug: str) -> bool:
    """Return True if the service has a known ResellPortal product_key."""
    return service_slug in PRODUCT_KEY_MAP


def derive_cpanel_username(primary_domain: str) -> str:
    """Derive a valid, unique-per-domain cpanel username from a primary domain.

    example.com          -> example
    my-business.co.in    -> mybusiness
    sub.example.com.au   -> example

    The username is derived deterministically from the domain so it never
    needs a random suffix and never contains characters the provider rejects.
    Returns "" when no usable username can be derived.
    """
    domain = str(primary_domain or "").strip().lower()
    domain = re.sub(r"^[a-z]+://", "", domain)  # strip scheme
    domain = domain.split("/", 1)[0]  # strip path
    domain = domain.rstrip(".")
    if not domain or "." not in domain:
        return ""
    labels = domain.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in _MULTI_LABEL_TLDS:
        base_labels = labels[:-2]
    else:
        base_labels = labels[:-1]
    if not base_labels:
        return ""
    # Use the registered (apex) domain — the last label before the TLD — so
    # sub.example.com.au -> example rather than sub.
    base = base_labels[-1]
    username = _CPANEL_INVALID_CHARS.sub("", base)
    username = username[:_CPANEL_MAX_LEN]
    return username


def validate_order_input(
    service_slug: str,
    metadata: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """Return (ok, missing_keys) for services that require customer input.

    For ``business-phone`` an areaCode OR a phoneNumber must be present. For
    ``web-hosting`` a primaryDomain must be present. Services without
    declared requirements always pass.
    """
    meta = metadata or {}
    if service_slug == "ai-business-suite":
        return (True, []) if _coerce_str_list(meta.get("aiTools") or meta.get("ai_tools")) else (False, ["aiTools"])
    if service_slug == "cloud-storage":
        storage_plan = str(meta.get("storagePlan") or meta.get("storage_plan") or "").strip().lower()
        return (True, []) if storage_plan in _CLOUD_STORAGE_PLANS else (False, ["storagePlan"])
    if service_slug == "email-marketing":
        return (True, []) if _email_marketing_plan(metadata=meta) else (False, ["sendingPlan"])
    groups = REQUIRED_INPUT_KEYS.get(service_slug)
    if not groups:
        return True, []
    for group in groups:
        if all(str(_metadata_value(meta, k) or "").strip() for k in group):
            return True, []
    # Nothing satisfied: report the smallest group's keys as missing guidance.
    missing = sorted(min(groups, key=len))
    return False, missing


def get_mapped_services() -> list[str]:
    """Return all service slugs with a known provider mapping."""
    return list(PRODUCT_KEY_MAP.keys())
