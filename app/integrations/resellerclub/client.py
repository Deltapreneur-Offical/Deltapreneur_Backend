"""ResellerClub / LogicBoxes HTTP API (domain availability, pricing, register)."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.integrations.resellerclub.errors import format_registrar_http_error

logger = logging.getLogger(__name__)

_HANDLE_PREFIX = "rc:"
_TAKEN_STATUSES = frozenset({"regthroughothers", "regthroughus", "reserved", "invalid"})
_AVAILABLE_STATUSES = frozenset({"available"})


def _api_base() -> str:
    return settings.resolved_resellerclub_api_base()


def _auth_userid() -> str:
    return settings.resellerclub_reseller_id()


def _api_key() -> str:
    return settings.resellerclub_api_key()


def effective_invoice_option() -> str:
    from app.integrations.resellerclub.runtime_validation import effective_invoice_option as _eff

    return _eff()


def _nameservers_from_env() -> list[str]:
    """Nameservers from .env for active RESELLERCLUB_ENV (no API)."""
    return settings.resolved_resellerclub_default_nameservers()


def _default_nameservers() -> list[str]:
    """Sync fallback list for validation/logging."""
    return _nameservers_from_env()


def extract_nameservers_from_api_body(body: Any) -> list[str]:
    """Parse domains/customer-default-ns.json (array or object shapes)."""
    if isinstance(body, list):
        return [str(item).strip() for item in body if str(item).strip()]
    if not isinstance(body, dict):
        return []
    if str(body.get("status", "")).upper() == "ERROR":
        return []
    for key in ("ns", "nameservers", "nameserver", "defaultns", "default-ns", "defaultNameservers"):
        value = body.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [part.strip() for part in value.split(",") if part.strip()]
    hosts: list[str] = []
    for value in body.values():
        if isinstance(value, str) and "." in value and " " not in value:
            hosts.append(value.strip().lower())
    return hosts


def _validate_nameserver_hosts(hosts: list[str]) -> None:
    if len(hosts) < 2:
        raise RuntimeError("At least two nameservers are required for domain registration.")
    if not is_sandbox():
        for host in hosts:
            if "onlyfordemo" in host.lower():
                raise RuntimeError(
                    "Live ResellerClub registration cannot use demo nameservers (onlyfordemo.net). "
                    "Configure default nameservers in the ResellerClub panel (Branding → Name Servers).",
                )


def is_sandbox() -> bool:
    return settings.resellerclub_use_sandbox()


def control_panel_url() -> str:
    return settings.resellerclub_control_panel_url()


def is_configured() -> bool:
    return settings.resellerclub_configured()


def _auth_params() -> dict[str, str]:
    return {"auth-userid": _auth_userid(), "api-key": _api_key()}


_HTTP_HEADERS = {
    "User-Agent": "CoBrother-ResellerClub/1.0 (+https://cobrother.com)",
    "Accept": "application/json, text/plain, */*",
}


def _form_body(fields: list[tuple[str, str]]) -> tuple[bytes, dict[str, str]]:
    body = urlencode(fields, doseq=True).encode("utf-8")
    return body, {"Content-Type": "application/x-www-form-urlencoded"}


def _parse_json_body(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ResellerClub returned invalid JSON.") from exc


def _normalize_id_response(body: Any, *, id_key: str) -> dict[str, Any]:
    """Some endpoints return a bare numeric id instead of an object."""
    if isinstance(body, dict):
        return body
    if body is not None and str(body).strip().isdigit():
        return {id_key: str(body).strip()}
    return {}


def _ensure_not_error(body: Any, *, operation: str) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise RuntimeError(f"ResellerClub {operation} returned unexpected response.")
    status = str(body.get("status", "")).upper()
    if status == "ERROR":
        message = body.get("message") or body.get("error") or "request failed"
        raise RuntimeError(f"ResellerClub {operation}: {message}")
    return body


def _is_dns_or_connect_failure(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        isinstance(exc, httpx.ConnectError)
        or "getaddrinfo failed" in text
        or "cannot connect" in text
    )


def _connect_error_message(api_base: str, exc: BaseException) -> str:
    host = api_base.replace("https://", "").replace("http://", "").split("/")[0]
    return (
        f"Cannot reach ResellerClub API host '{host}' (DNS/network). "
        "For sandbox use https://test.httpapi.com/api, check internet/VPN, and IP whitelist."
    )


def _api_base_candidates() -> list[str]:
    """Configured API host only — never mix live + test (sandbox prices differ from panel)."""
    seen: set[str] = set()
    out: list[str] = []
    primary = (_api_base() or "").strip().rstrip("/")
    if primary:
        seen.add(primary)
        out.append(primary)
    return out


def _domaincheck_base_candidates() -> list[str]:
    """Availability hosts for the active env only (sandbox → test, live → domaincheck/live)."""
    seen: set[str] = set()
    out: list[str] = []
    for base in (
        settings.resolved_resellerclub_domaincheck_base(),
        *([] if settings.resellerclub_use_sandbox() else _api_base_candidates()),
    ):
        cleaned = (base or "").strip().rstrip("/")
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    if not out:
        out.extend(_api_base_candidates())
    return out


async def _get_domaincheck(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET on domaincheck host (availability only)."""
    last_exc: RuntimeError | None = None
    for base in _domaincheck_base_candidates():
        try:
            return await _get_once(base, path, params)
        except RuntimeError as exc:
            last_exc = exc
            if _is_dns_or_connect_failure(exc) or _should_retry_alternate_api(exc):
                logger.warning("ResellerClub domaincheck GET %s failed at %s: %s", path, base, exc)
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("ResellerClub domaincheck base URL is not configured.")


def _should_retry_alternate_api(exc: RuntimeError) -> bool:
    msg = str(exc).lower()
    if "invalid credentials" in msg:
        return True
    return "http 403" in msg or "blocked the server" in msg or "cloudflare" in msg


async def _get_once_raw(api_base: str, path: str, params: dict[str, Any] | None = None) -> Any:
    query = {**_auth_params(), **(params or {})}
    url = f"{api_base.rstrip('/')}/api/{path.lstrip('/')}?{urlencode(query, doseq=True)}"
    try:
        async with httpx.AsyncClient(timeout=45.0, headers=_HTTP_HEADERS) as client:
            resp = await client.get(url)
    except httpx.ConnectError as exc:
        raise RuntimeError(_connect_error_message(api_base, exc)) from exc
    if resp.status_code >= 400:
        raise RuntimeError(format_registrar_http_error(path, resp.status_code, resp.text or ""))
    return _parse_json_body(resp.text)


async def _get_once(api_base: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    body = await _get_once_raw(api_base, path, params)
    if isinstance(body, dict):
        return _ensure_not_error(body, operation=path)
    raise RuntimeError(f"ResellerClub {path} returned unexpected response.")


async def _get_any(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET that accepts dict or list JSON (e.g. customer-default-ns)."""
    last_exc: RuntimeError | None = None
    for base in _api_base_candidates():
        try:
            body = await _get_once_raw(base, path, params)
            if isinstance(body, dict) and str(body.get("status", "")).upper() == "ERROR":
                message = body.get("message") or body.get("error") or "request failed"
                raise RuntimeError(f"ResellerClub {path}: {message}")
            return body
        except RuntimeError as exc:
            last_exc = exc
            if _is_dns_or_connect_failure(exc) or _should_retry_alternate_api(exc):
                logger.warning("ResellerClub GET %s failed at %s: %s", path, base, exc)
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("ResellerClub API base URL is not configured.")


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    last_exc: RuntimeError | None = None
    for base in _api_base_candidates():
        try:
            return await _get_once(base, path, params)
        except RuntimeError as exc:
            last_exc = exc
            if _is_dns_or_connect_failure(exc) or _should_retry_alternate_api(exc):
                logger.warning("ResellerClub GET %s failed at %s: %s", path, base, exc)
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("ResellerClub API base URL is not configured.")


async def _post(path: str, data: dict[str, Any], *, extra_fields: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    fields: list[tuple[str, str]] = [(k, str(v)) for k, v in {**_auth_params(), **data}.items()]
    if extra_fields:
        fields.extend(extra_fields)
    content, form_headers = _form_body(fields)
    post_headers = {**_HTTP_HEADERS, **form_headers}
    last_exc: RuntimeError | None = None
    resp: httpx.Response | None = None
    for base in _api_base_candidates():
        url = f"{base.rstrip('/')}/api/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=90.0, headers=post_headers) as client:
                resp = await client.post(url, content=content)
        except httpx.ConnectError as exc:
            last_exc = RuntimeError(_connect_error_message(base, exc))
            continue
        if resp.status_code >= 400:
            err = RuntimeError(format_registrar_http_error(path, resp.status_code, resp.text or ""))
            if _should_retry_alternate_api(err):
                last_exc = err
                continue
            raise err
        break
    else:
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("ResellerClub API base URL is not configured.")
    if resp is None:
        raise RuntimeError("ResellerClub POST did not receive a response.")
    parsed = _parse_json_body(resp.text)
    if path.rstrip("/").endswith("customers/signup.json"):
        parsed = _normalize_id_response(parsed, id_key="customerid") or parsed
    if path.rstrip("/").endswith("contacts/add.json"):
        parsed = _normalize_id_response(parsed, id_key="contactid") or parsed
    return _ensure_not_error(parsed, operation=path)


def map_availability_status(rc_status: str) -> str:
    s = (rc_status or "").lower()
    if s in _AVAILABLE_STATUSES:
        return "available"
    if s in _TAKEN_STATUSES:
        return "taken"
    if s == "unknown":
        return "error"
    return s or "error"


def is_free(check_result: dict[str, Any]) -> bool:
    return map_availability_status(str(check_result.get("status", ""))) == "available"


def _find_availability_entry(body: dict[str, Any], fqdn: str) -> dict[str, Any] | None:
    direct = body.get(fqdn)
    if isinstance(direct, dict):
        return direct
    target = fqdn.lower()
    for key, value in body.items():
        if str(key).lower() == target and isinstance(value, dict):
            return value
    return None


async def check_availability_bulk(label: str, tlds: list[str]) -> list[dict[str, Any]]:
    """Bulk availability — GET domains/available.json with domain-name + multiple tlds=."""
    clean_label = label.strip().lower().split(".")[0]
    query_parts: list[tuple[str, str]] = [
        ("domain-name", clean_label),
        ("suggest-alternative", "false"),
    ]
    for tld in tlds:
        query_parts.append(("tlds", tld.lstrip(".")))

    last_exc: RuntimeError | None = None
    for base in _domaincheck_base_candidates():
        auth = urlencode(_auth_params())
        query = urlencode(query_parts, doseq=True)
        url = f"{base.rstrip('/')}/api/domains/available.json?{auth}&{query}"
        try:
            async with httpx.AsyncClient(timeout=45.0, headers=_HTTP_HEADERS) as client:
                resp = await client.get(url)
        except httpx.ConnectError as exc:
            last_exc = RuntimeError(_connect_error_message(base, exc))
            continue
        if resp.status_code >= 400:
            last_exc = RuntimeError(
                format_registrar_http_error(
                    "domains/available.json",
                    resp.status_code,
                    resp.text or "",
                ),
            )
            continue
        body = _ensure_not_error(
            _parse_json_body(resp.text),
            operation="domains/available.json",
        )
        results: list[dict[str, Any]] = []
        for tld in tlds:
            ext = tld.lstrip(".")
            fqdn = f"{clean_label}.{ext}"
            entry = _find_availability_entry(body, fqdn) or {}
            mapped = map_availability_status(str(entry.get("status", "")))
            results.append(
                {
                    "domain": fqdn,
                    "status": mapped,
                    "classkey": entry.get("classkey"),
                    "attributes": entry,
                },
            )
        return results
    if last_exc:
        raise last_exc
    raise RuntimeError("ResellerClub bulk availability failed.")


async def _fetch_availability(label: str, ext: str, fqdn: str) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = [
        {"domain-name": label, "tlds": ext},
        {"domain-name": fqdn},
    ]
    last_error: RuntimeError | None = None
    for params in attempts:
        try:
            body = await _get_domaincheck("domains/available.json", params)
            entry = _find_availability_entry(body, fqdn)
            if entry is not None:
                return entry
        except RuntimeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"ResellerClub availability response missing entry for {fqdn}")


async def check_domain(name: str, extension_no_dot: str) -> dict[str, Any]:
    label = name.strip().lower()
    ext = extension_no_dot.strip().lower().lstrip(".")
    if "." in label:
        dot = label.find(".")
        ext = label[dot + 1 :] or ext
        label = label[:dot]
    fqdn = f"{label}.{ext}"
    entry = await _fetch_availability(label, ext, fqdn)
    rc_status = str(entry.get("status", "")).lower()
    return {
        "domain": fqdn,
        "status": map_availability_status(rc_status),
        "registrarStatus": rc_status,
        "classkey": str(entry.get("classkey") or _default_classkey(ext)),
        "attributes": entry,
    }


def _default_classkey(extension_no_dot: str) -> str:
    ext = extension_no_dot.lower().lstrip(".")
    mapping = {
        "com": "domcno",
        "net": "domcno",
        "org": "domcno",
        "in": "dotin",
        "co.in": "codotin",
        "io": "dotio",
        "info": "dominfo",
        "biz": "dombiz",
    }
    return mapping.get(ext, "domcno")


def _extract_year_one_price(add_pricing: Any) -> float:
    if not isinstance(add_pricing, list):
        return 0.0
    for row in add_pricing:
        if not isinstance(row, dict):
            continue
        if str(row.get("years")) == "1" and row.get("price") is not None:
            try:
                return float(row["price"])
            except (TypeError, ValueError):
                continue
    return 0.0


def _extract_addnewdomain_price(node: Any, *, years: str = "1") -> float:
    """Parse addnewdomain year price from domorder, customer-price, or reseller-price shapes."""
    if not isinstance(node, dict):
        return 0.0
    for key in ("addnewdomain", "addNewDomain"):
        add = node.get(key)
        if isinstance(add, dict) and years in add:
            try:
                return float(add[years])
            except (TypeError, ValueError):
                pass
    pricing = node.get("pricing")
    if isinstance(pricing, dict):
        found = _extract_addnewdomain_price(pricing, years=years)
        if found > 0:
            return found
    nested = node.get("0")
    if isinstance(nested, dict):
        found = _extract_addnewdomain_price(nested, years=years)
        if found > 0:
            return found
    return 0.0


async def get_domorder_price(fqdn: str, *, action: str = "add") -> dict[str, Any]:
    """GET products/domorder/details.json — primary pricing per spec."""
    return await _get(
        "products/domorder/details.json",
        {"domain-name": fqdn.lower(), "action": action},
    )


async def get_create_price(
    name: str,
    extension_no_dot: str,
    *,
    period: int = 1,
    classkey: str | None = None,
) -> dict[str, Any]:
    ext = extension_no_dot.lstrip(".")
    fqdn = f"{name}.{ext}".lower()
    key = classkey or _default_classkey(ext)
    currency = settings.RESELLERCLUB_PRICE_CURRENCY.strip() or "INR"
    year_key = str(max(1, period))

    # Customer selling price — matches ResellerClub panel search/checkout for standard TLDs.
    for path, source_tag in (
        ("products/customer-price.json", "resellerclub_customer_price"),
        ("products/reseller-price.json", "resellerclub_reseller_price"),
    ):
        try:
            body = await _get(path, {"product-key": key})
            node = body.get(key) if isinstance(body.get(key), dict) else body
            price = _extract_addnewdomain_price(node, years=year_key)
            if price <= 0 and period != 1:
                price = _extract_addnewdomain_price(node, years="1")
            if price > 0:
                return {
                    "price": price,
                    "currency": currency,
                    "classkey": key,
                    "source": source_tag,
                    "fqdn": fqdn,
                }
        except Exception as exc:
            logger.warning("ResellerClub %s failed for %s: %s", path, fqdn, exc)

    try:
        details = await get_domorder_price(fqdn)
        unit = _extract_year_one_price(details.get("addnewdomain"))
        if unit <= 0:
            unit = _extract_addnewdomain_price(details, years=year_key)
        if unit > 0:
            return {
                "price": unit,
                "currency": currency,
                "classkey": key,
                "source": "resellerclub_domorder",
                "fqdn": fqdn,
            }
    except Exception as exc:
        logger.warning("ResellerClub domorder price failed for %s: %s", fqdn, exc)

    raise RuntimeError(
        f"ResellerClub returned no registration price for {fqdn}. "
        "Check API credentials, IP whitelist, and TLD support."
    )


def extract_reseller_price_details(check_result: dict[str, Any]) -> tuple[float, str | None]:
    if check_result.get("price") is not None:
        try:
            return float(check_result["price"]), settings.RESELLERCLUB_PRICE_CURRENCY.strip() or "INR"
        except (TypeError, ValueError):
            pass
    return 0.0, settings.RESELLERCLUB_PRICE_CURRENCY.strip() or "INR"


def extract_create_price_details(
    quote: dict[str, Any],
    *,
    source_hint: str | None = None,
) -> tuple[float, str | None, str]:
    price = 0.0
    if quote.get("price") is not None:
        try:
            price = float(quote["price"])
        except (TypeError, ValueError):
            pass
    currency = str(quote.get("currency") or settings.RESELLERCLUB_PRICE_CURRENCY or "INR").upper()
    tag = source_hint or str(quote.get("source") or "resellerclub_domorder")
    return price, currency, tag


_TLD_MIN_REGISTRATION_YEARS: dict[str, int] = {
    "ai": 2,
}


def tld_min_registration_years(extension_no_dot: str) -> int:
    ext = (extension_no_dot or "").lower().lstrip(".")
    return max(1, int(_TLD_MIN_REGISTRATION_YEARS.get(ext, 1)))


def resolve_registration_period(requested: int, extension_no_dot: str) -> int:
    return max(1, int(requested or 1), tld_min_registration_years(extension_no_dot))


def yearly_create_price_from_check(raw_price: float, extension_no_dot: str) -> float:
    """Normalize multi-year minimum check totals to a 1-year unit (see OpenProvider)."""
    price = float(raw_price or 0)
    if price <= 0:
        return 0.0
    years = tld_min_registration_years(extension_no_dot)
    if years <= 1:
        return round(price, 2)
    return round(price / years, 2)


def friendly_error_from_body(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return "ResellerClub registration failed. Try again or contact support."
    lower = text.lower()
    if "access denied" in lower or "http 403" in lower:
        return f"ResellerClub API access denied. Whitelist server IP in {control_panel_url()} → Settings → API."
    if "insufficient" in lower or "balance" in lower or "funds" in lower:
        return f"ResellerClub balance is too low. Add funds in {control_panel_url()}, then retry."
    if "invalid credentials" in lower:
        return "ResellerClub rejected API credentials. Check RESELLERCLUB_RESELLER_ID and RESELLERCLUB_API_KEY."
    if "getaddrinfo" in lower or "dns/network" in lower:
        return "Cannot reach ResellerClub API (DNS/network). Check RESELLERCLUB_API_BASE and connectivity."
    return text if len(text) < 320 else text[:320]


def parse_registrant_handle(handle: str) -> tuple[str, str] | None:
    """Return (customer_id, contact_id) from internal ``rc:customer:contact`` handle."""
    return _parse_handle(handle)


def _parse_handle(handle: str) -> tuple[str, str] | None:
    if not handle or not handle.startswith(_HANDLE_PREFIX):
        return None
    parts = handle[len(_HANDLE_PREFIX) :].split(":", 1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1]
    return None


def _format_handle(customer_id: str, contact_id: str) -> str:
    return f"{_HANDLE_PREFIX}{customer_id}:{contact_id}"


def _phone_parts(contact: dict[str, Any]) -> tuple[str, str]:
    phone = contact.get("phone") or {}
    country = str((contact.get("address") or {}).get("country") or "IN").upper()
    digits = "".join(c for c in str(phone.get("subscriber_number") or "") if c.isdigit())
    if len(digits) > 10:
        digits = digits[-10:]
    cc = "91" if country == "IN" else "1"
    return cc, digits or "9999999999"


def _contact_fields(contact: dict[str, Any]) -> dict[str, str]:
    name = contact.get("name") or {}
    addr = contact.get("address") or {}
    phone_cc, phone = _phone_parts(contact)
    first = str(name.get("first_name") or "Registrant")
    last = str(name.get("last_name") or "User")
    full = str(name.get("full_name") or f"{first} {last}").strip()
    return {
        "name": full[:255],
        "company": full[:255],
        "email": str(contact.get("email") or "")[:255],
        "address-line-1": str(addr.get("street") or "1 Main Street")[:255],
        "city": str(addr.get("city") or "City")[:128],
        "state": str(addr.get("state") or "Delhi")[:128],
        "country": str(addr.get("country") or "IN").upper()[:2],
        "zipcode": str(addr.get("zipcode") or "110001")[:16],
        "phone-cc": phone_cc,
        "phone": phone,
    }


async def _lookup_customer_id_by_username(email: str) -> str | None:
    try:
        body = await _get("customers/details.json", {"username": email.strip().lower()})
    except Exception:
        return None
    cid = body.get("customerid") or body.get("customer-id")
    return str(cid) if cid is not None else None


async def _signup_customer(contact: dict[str, Any]) -> str:
    fields = _contact_fields(contact)
    email = fields["email"]
    if not email or "@" not in email:
        raise RuntimeError("Valid registrant email is required for ResellerClub customer signup.")
    password = secrets.token_hex(6)[:12]
    try:
        body = await _post(
            "customers/signup.json",
            {
                "username": email,
                "passwd": password,
                "name": fields["name"],
                "company": fields["company"] or fields["name"],
                "address-line-1": fields["address-line-1"],
                "city": fields["city"],
                "state": fields["state"],
                "country": fields["country"],
                "zipcode": fields["zipcode"],
                "phone-cc": fields["phone-cc"],
                "phone": fields["phone"],
                "lang-pref": "en",
            },
        )
    except RuntimeError as exc:
        if "already a customer" in str(exc).lower():
            existing = await _lookup_customer_id_by_username(email)
            if existing:
                return existing
        raise
    customer_id = body.get("customerid") or body.get("customer-id") or body.get("id")
    if customer_id is None:
        raise RuntimeError("ResellerClub customer signup did not return customerid.")
    return str(customer_id)


async def _add_contact(customer_id: str, contact: dict[str, Any]) -> str:
    fields = _contact_fields(contact)
    body = await _post(
        "contacts/add.json",
        {
            "customer-id": customer_id,
            "type": "Contact",
            "name": fields["name"],
            "company": fields["company"],
            "email": fields["email"],
            "address-line-1": fields["address-line-1"],
            "city": fields["city"],
            "state": fields["state"],
            "country": fields["country"],
            "zipcode": fields["zipcode"],
            "phone-cc": fields["phone-cc"],
            "phone": fields["phone"],
        },
    )
    contact_id = body.get("contactid") or body.get("contact-id") or body.get("id")
    if contact_id is None:
        raise RuntimeError("ResellerClub contacts/add did not return contactid.")
    return str(contact_id)


async def create_customer(contact: dict[str, Any]) -> str:
    default_cust = settings.RESELLERCLUB_DEFAULT_CUSTOMER_ID.strip()
    default_contact = settings.RESELLERCLUB_DEFAULT_CONTACT_ID.strip()
    if default_cust and default_contact:
        return _format_handle(default_cust, default_contact)
    existing = _parse_handle(str(contact.get("_handle") or ""))
    if existing:
        return _format_handle(existing[0], existing[1])
    customer_id = await _signup_customer(contact)
    contact_id = await _add_contact(customer_id, contact)
    return _format_handle(customer_id, contact_id)


async def get_reseller_details() -> dict[str, Any]:
    return await _get("resellers/details.json", {})


async def get_customer_default_nameservers(customer_id: str) -> list[str]:
    """
    GET domains/customer-default-ns.json — panel default NS for this customer (KB 788).
    """
    body = await _get_any(
        "domains/customer-default-ns.json",
        {"customer-id": str(customer_id).strip()},
    )
    hosts = extract_nameservers_from_api_body(body)
    if len(hosts) < 2:
        raise RuntimeError(
            f"ResellerClub returned fewer than 2 default nameservers for customer {customer_id}.",
        )
    return hosts[:5]


async def resolve_nameservers_for_customer(customer_id: str) -> tuple[list[str], str]:
    """
    Resolve nameservers for domains/register.json.

    Priority: customer API (panel defaults) → .env override → sandbox demo fallback.
    """
    if settings.RESELLERCLUB_FETCH_NAMESERVERS_FROM_API and customer_id.strip():
        try:
            api_hosts = await get_customer_default_nameservers(customer_id)
            _validate_nameserver_hosts(api_hosts)
            return api_hosts, "resellerclub_customer_default_ns"
        except Exception as exc:
            logger.warning(
                "ResellerClub customer-default-ns failed for customer %s: %s",
                customer_id,
                exc,
            )

    env_hosts = _nameservers_from_env()
    if len(env_hosts) >= 2:
        _validate_nameserver_hosts(env_hosts)
        return env_hosts[:5], "resellerclub_env"

    if is_sandbox():
        demo = ["ns1.onlyfordemo.net", "ns2.onlyfordemo.net"]
        return demo, "resellerclub_sandbox_fallback"

    raise RuntimeError(
        "No nameservers available. Configure defaults in the ResellerClub panel "
        "(customer-default-ns API) or set RESELLERCLUB_DEFAULT_NAMESERVERS in .env.",
    )


def parse_registration_response(body: dict[str, Any]) -> dict[str, Any]:
    """Normalize domains/register.json fields for persistence."""
    entity_id = body.get("entityid") or body.get("orderid") or body.get("order-id")
    action_id = body.get("eaqid") or body.get("actionid") or body.get("action-id")
    return {
        "id": str(entity_id) if entity_id is not None else None,
        "entityid": entity_id,
        "actionid": action_id,
        "actionstatus": body.get("actionstatus") or body.get("status"),
        "actionstatusdesc": body.get("actionstatusdesc") or body.get("description"),
        "invoiceid": body.get("invoiceid") or body.get("invoice-id"),
        "status": str(body.get("actionstatus") or body.get("status") or "submitted"),
        "attributes": body,
    }


def order_details_current_status(details: dict[str, Any]) -> str:
    direct = details.get("currentstatus") or details.get("currentStatus")
    if direct:
        return str(direct)
    nested = details.get("orderdetails") or details.get("OrderDetails")
    if isinstance(nested, dict):
        return str(nested.get("currentstatus") or nested.get("currentStatus") or "")
    return ""


def is_registration_confirmed(details: dict[str, Any]) -> bool:
    """
    True when ResellerClub reports the domain order is live.

    Sandbox often returns orderstatus e.g. transferlock instead of currentstatus=Active.
    """
    current = order_details_current_status(details).lower()
    if current == "active":
        return True
    if details.get("orderid") and details.get("domainname"):
        orderstatus = details.get("orderstatus")
        if isinstance(orderstatus, list) and orderstatus:
            return True
        if str(details.get("actionstatus") or details.get("status") or "").lower() == "success":
            return True
    return False


def is_order_active(details: dict[str, Any]) -> bool:
    return is_registration_confirmed(details)


async def get_domain_order_details(order_id: str) -> dict[str, Any]:
    return await _get(
        "domains/details.json",
        {"order-id": str(order_id), "options": "OrderDetails"},
    )


async def get_domain_status_details(order_id: str) -> dict[str, Any]:
    """Domain status including RAA (registrant email verification)."""
    return await _get(
        "domains/details.json",
        {"order-id": str(order_id), "options": "DomainStatus"},
    )


async def get_domain_all_details(order_id: str) -> dict[str, Any]:
    return await _get(
        "domains/details.json",
        {"order-id": str(order_id), "options": "All"},
    )


def _nested_dict_values(body: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in body and body[key] is not None:
            return body[key]
    for nested_key in ("orderdetails", "OrderDetails", "domainstatus", "statusdetails"):
        nested = body.get(nested_key)
        if isinstance(nested, dict):
            for key in keys:
                if key in nested and nested[key] is not None:
                    return nested[key]
    return None


def parse_raa_verification_status(details: dict[str, Any]) -> str:
    """Normalize ResellerClub raaVerificationStatus to VERIFIED, PENDING, SUSPENDED, or UNKNOWN."""
    raw = _nested_dict_values(
        details,
        "raaVerificationStatus",
        "raaverificationstatus",
        "RAAVerificationStatus",
    )
    if raw is None:
        return "UNKNOWN"
    normalized = str(raw).strip().upper()
    if normalized == "VERIFIED":
        return "VERIFIED"
    if normalized == "PENDING":
        return "PENDING"
    if normalized == "SUSPENDED":
        return "SUSPENDED"
    return "UNKNOWN"


def parse_expiry_from_details(details: dict[str, Any]) -> datetime | None:
    """Parse registrar expiry/end time from domains/details response."""
    raw = _nested_dict_values(
        details,
        "endtime",
        "endTime",
        "expirydate",
        "expirationdate",
        "currentexpirationdate",
    )
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        text = str(raw).strip()
        if text.isdigit():
            return datetime.fromtimestamp(int(text), tz=timezone.utc)
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError, OSError):
        return None


async def resend_raa_verification(order_id: str) -> bool:
    body = await _post(
        "domains/raa/resend-verification.json",
        {"order-id": str(order_id)},
    )
    if isinstance(body, bool):
        return body
    if str(body.get("status", "")).upper() == "ERROR":
        raise RuntimeError(body.get("message") or "ResellerClub resend verification failed.")
    if body.get("success") is False:
        return False
    return True


async def lookup_order_id_by_domain(fqdn: str) -> str | None:
    try:
        body = await _get("domains/orderid.json", {"domain-name": fqdn.lower()})
    except Exception:
        return None
    oid = body.get("orderid") or body.get("entityid") or body.get("order-id")
    return str(oid) if oid is not None else None


async def register_domain(
    name: str,
    extension_no_dot: str,
    handle: str,
    period_years: int,
    *,
    contact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed = _parse_handle(handle)
    if not parsed and contact:
        handle = await create_customer(contact)
        parsed = _parse_handle(handle)
    if not parsed:
        raise RuntimeError("ResellerClub registrant handle is invalid.")

    customer_id, contact_id = parsed
    fqdn = f"{name}.{extension_no_dot.lstrip('.')}".lower()
    nameservers, ns_source = await resolve_nameservers_for_customer(customer_id)
    logger.info(
        "ResellerClub register %s nameservers=%s source=%s",
        fqdn,
        nameservers,
        ns_source,
    )

    payload: dict[str, Any] = {
        "domain-name": fqdn,
        "years": str(max(1, period_years)),
        "customer-id": customer_id,
        "reg-contact-id": contact_id,
        "admin-contact-id": contact_id,
        "tech-contact-id": contact_id,
        "billing-contact-id": contact_id,
        "invoice-option": effective_invoice_option(),
        "auto-renew": "false",
        "purchase-privacy": "false",
    }
    ns_fields = [("ns", ns) for ns in nameservers[:5]]
    body = await _post("domains/register.json", payload, extra_fields=ns_fields)
    parsed = parse_registration_response(body)
    parsed["nameservers"] = nameservers
    parsed["nameserverSource"] = ns_source
    action_status = parsed.get("actionstatus") or parsed.get("status")
    if str(action_status).upper() == "ERROR" or str(body.get("status", "")).upper() == "ERROR":
        raise RuntimeError(f"ResellerClub domains/register.json: {body.get('message', action_status)}")
    return parsed
