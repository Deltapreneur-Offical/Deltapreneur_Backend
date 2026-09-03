"""Domain registration storefront — checkout, verify, provision."""

from __future__ import annotations

import json
import logging
import asyncio
import inspect
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import ModuleType
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.entity.user.app_user import AppUser
from app.integrations import domain_registrar
from app.integrations.openprovider.client import (
    http_status_for_openprovider_error,
)
from app.integrations.razorpay import client as rzp
from app.model.domain.domain_check_response import (
    DomainCheckListingSnippet,
    DomainCheckResponse,
)
from app.repository.domain_listing_repository import DomainListingRepository
from app.repository.domain_registration_order_repository import (
    DomainRegistrationOrderRepository,
)
from app.service.domain.domain_registration_followup import (
    DomainRegistrationFollowup,
    _parse_order_nameservers,
    is_legacy_resellerclub_order,
    sanitize_customer_registrar_message,
)
from app.service.domain.provider_domain_correlation import (
    ProviderLinkDecision,
    decide_provider_link,
    email_from_customer_payload,
)
from app.utils.domain_gst import domain_price_breakdown, gst_settings_for_client, order_gst_payload
from app.utils.domain_label import compose_search_fqdn, sanitize_sld
from app.utils.domain_nameservers import parse_order_nameservers, set_order_nameservers
from app.utils.registration_enums import RegistrationOrderStatus
from app.utils.registration_lifecycle import registration_lifecycle_status

logger = logging.getLogger(__name__)

# ── Retry-payment mint guard ──────────────────────────────────────────────────
# A transfer retry ALWAYS mints a fresh Razorpay order (a stale order id from an
# abandoned checkout makes the Razorpay checkout refuse to open). This in-process
# guard absorbs a rapid duplicate click: within the TTL the just-minted order id
# is returned instead of minting a second order for the same attempt.
_RETRY_MINT_GUARD: dict[uuid.UUID, tuple[float, str]] = {}
_RETRY_MINT_TTL_SECONDS = 60.0

# OpenProvider SpamExperts incoming MX (see OP support docs). Priorities 100/200/300.
SPAMEXPERTS_MX_RECORDS: list[dict[str, Any]] = [
    {"host": "mx.spamexperts.com", "priority": 100},
    {"host": "fallbackmx.spamexperts.eu", "priority": 200},
    {"host": "lastmx.spamexperts.net", "priority": 300},
]

_PRICE_TOLERANCE_INR = 1.0

# ── Storefront TLD search pagination + short-lived cache ─────────────────────
# Page 1 returns the curated priority extensions (.com, .in, .ai, .org, … — the
# list maintained in openprovider.client._PRIORITY_TLDS) in ONE fast concurrent
# wave. Each subsequent "Load more" page (page >= 2) scans a single bounded
# window of the remaining catalog instead of serially draining the whole 600+
# TLD catalog on the first request. Responses are cached briefly so rapid
# re-searches and repeated "Load more" clicks never re-hit the registrar, which
# also protects us from OpenProvider rate-limiting.
_TLD_REMAINING_WINDOW = 100
_TLD_SEARCH_CACHE_TTL = 300.0
_tld_search_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _is_provider_reachability_error(exc: BaseException) -> bool:
    """True when the provider call failed because the registrar was unreachable
    (transient — safe to retry automatically) rather than because it rejected
    the transfer (never retry blindly: OpenProvider has no POST idempotency)."""
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "timeout",
            "timed out",
            "connection",
            "connect",
            "refused",
            "unreachable",
            "could not resolve",
            "could not connect",
            "name or service not known",
            "ssl",
            "tls",
            "certificate",
            "network",
            "eof",
            "winerror",
        )
    )


def _is_definitive_transfer_failure(raw: str) -> bool:
    """True when OpenProvider definitively rejected the transfer submission.

    These are terminal business failures (invalid EPP/auth code, locked domain,
    duplicate, insufficient balance, forbidden, etc.) — never retry blindly and
    never leave the customer paying for a transfer that cannot proceed. Unknown
    or transient messages (timeouts, connection errors, ambiguous 5xx) fall
    through to the retry/reconciliation state instead.
    """
    lower = (raw or "").lower()
    return any(
        token in lower
        for token in (
            "auth code",
            "authorization code",
            "epp",
            "invalid",
            "wrong",
            "incorrect",
            "locked",
            "duplicate",
            "balance",
            "funds",
            "insufficient",
            "denied",
            "forbidden",
            "reject",
            "not allowed",
            "cannot be transferred",
            "cannot be transfered",
            "transfer failed",
            "unable to transfer",
            "refused to",
        )
    )


def _friendly_transfer_error(raw: str, domain: str) -> str:
    """Customer-facing failure message for a rejected transfer submission.

    Never claims the EPP code was verified, never exposes the raw auth code, and
    always tells the customer the payment is being refunded so they know they
    can retry safely once the refund completes.
    """
    lower = (raw or "").lower()
    if any(
        token in lower
        for token in ("auth", "epp", "authorization", "code")
    ):
        return (
            f"Domain transfer failed for {domain}: the registrar rejected the "
            "authorization (EPP) code. Your payment was received and is being "
            "refunded. Verify the code with your current registrar and start a "
            "new transfer once the refund is complete."
        )
    if any(token in lower for token in ("balance", "funds", "insufficient")):
        return (
            f"Domain transfer failed for {domain}: our registrar could not "
            "process the transfer right now. Your payment was received and is "
            "being refunded. Please try again later."
        )
    if "duplicate" in lower:
        return (
            f"Domain transfer failed for {domain}: the domain is already "
            "registered with our registrar and cannot be transferred in. Your "
            "payment was received and is being refunded."
        )
    return (
        f"Domain transfer failed for {domain}: {raw[:300]}. Your payment was "
        "received and is being refunded. Please try again or contact support."
    )


def _tld_search_cache_get(key: str) -> dict[str, Any] | None:
    entry = _tld_search_cache.get(key)
    if not entry:
        return None
    expiry, payload = entry
    if time.time() >= expiry:
        _tld_search_cache.pop(key, None)
        return None
    return payload


def _tld_search_cache_put(key: str, payload: dict[str, Any]) -> None:
    # Bound the cache so it can't grow without limit on a busy storefront.
    if len(_tld_search_cache) > 512:
        _tld_search_cache.clear()
    _tld_search_cache[key] = (time.time() + _TLD_SEARCH_CACHE_TTL, payload)


def _sanitize_sld(raw: str) -> str:
    """DNS second-level label: letters, digits, hyphen; spaces/punctuation dropped."""
    return sanitize_sld(raw)


def clear_tld_search_cache() -> None:
    """Drop all cached storefront TLD-search responses.

    Called when admin pricing/commission settings change so freshly-computed
    prices are served immediately instead of waiting out the cache TTL.
    """
    _tld_search_cache.clear()


def active_registrar() -> ModuleType:
    """Active registrar client module (OpenProvider)."""
    return domain_registrar.active_registrar_module()


async def _warm_tld_min_period(reg: Any, extension_no_dot: str) -> None:
    """
    Optionally prefetch OpenProvider TLD ``min_period`` into the registrar cache.

    Only awaits when ``ensure_tld_min_period`` returns an awaitable. Sync mocks
    (and missing helpers) are skipped so checkout/check keep using
    ``resolve_registration_period``.
    """
    ensure_min = getattr(reg, "ensure_tld_min_period", None)
    if not callable(ensure_min):
        return
    maybe = ensure_min(extension_no_dot)
    if inspect.isawaitable(maybe):
        await maybe


def registrar_source() -> str:
    return settings.domain_registrar()


def _registration_pricing_fields(unit_inr: float, years: int = 1) -> dict[str, Any]:
    """
    Map a **1-year** selling unit price to storefront fields (incl. GST).

    Storefront search/check cards always use ``years=1``. Multi-year registration
    totals are quoted only in cart/checkout after the user selects a period —
    never by multiplying here for display.
    """
    breakdown = domain_price_breakdown(unit_inr, years=max(1, int(years or 1)))
    return {
        "unitPrice": unit_inr,
        "subtotalInr": breakdown["subtotalInr"],
        "gstInr": breakdown["gstInr"],
        "totalInr": breakdown["totalInr"],
        "price": breakdown["totalInr"],
        "gstRate": breakdown["gstRate"],
        "gstEnabled": breakdown["gstEnabled"],
    }


def _order_gst_fields(order: DomainRegistrationOrder) -> dict[str, Any]:
    return order_gst_payload(order)


def _parse_order_nameservers_local(order: DomainRegistrationOrder) -> tuple[list[str], str | None]:
    return parse_order_nameservers(order)


def _default_nameservers_for_order(order: DomainRegistrationOrder) -> list[str]:
    reg = active_registrar()
    if hasattr(reg, "default_nameservers"):
        return reg.default_nameservers()
    if hasattr(reg, "_default_nameservers"):
        return reg._default_nameservers()
    return []


def _order_is_using_default_nameservers(order: DomainRegistrationOrder) -> bool:
    hosts, _ = parse_order_nameservers(order)
    reg = active_registrar()
    if hasattr(reg, "is_platform_nameserver_set"):
        return bool(reg.is_platform_nameserver_set(hosts))
    if not hosts:
        return True
    defaults = _default_nameservers_for_order(order)
    if not defaults:
        return True
    normalized_hosts = sorted(h.lower() for h in hosts)
    normalized_defaults = sorted(ns.lower() for ns in defaults)
    return normalized_hosts == normalized_defaults


def _registrar_sync_is_stale(
    order: DomainRegistrationOrder,
    *,
    minutes: int = 10,
) -> bool:
    last = order.last_registrar_sync_at
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last > timedelta(minutes=minutes)


def is_demo_mode() -> bool:
    """Simulated registrar + placeholder pricing — not the same as Razorpay test keys."""
    return settings.domain_storefront_demo_fallback()


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _listing_snippet(listing: DomainListing) -> DomainCheckListingSnippet:
    return DomainCheckListingSnippet(
        id=listing.id,
        domainName=listing.domain_name,
        domainExtension=listing.domain_extension,
        askingPrice=float(listing.asking_price or 0),
        domainStatus=_enum_value(listing.domain_status),
        saleType=_enum_value(listing.sale_type),
    )


def _registrar_api_base_url() -> str:
    return settings.resolved_openprovider_api_base_url()


def _registrar_check_fields() -> dict[str, Any]:
    """Expose active registrar API environment on domain check responses."""
    import inspect

    reg = active_registrar()
    # is_sandbox() is a synchronous provider method; resolve defensively so a
    # mock that returns a coroutine/awaitable never reaches pydantic bool
    # validation on the DomainCheckResponse contract.
    sandbox_raw = reg.is_sandbox()
    if inspect.isawaitable(sandbox_raw):
        # Sync helper cannot await; fall back to settings for test mocks.
        close = getattr(sandbox_raw, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
        sandbox = bool(settings.openprovider_use_sandbox())
    else:
        sandbox = bool(sandbox_raw)
    return {
        "registrarSandbox": sandbox,
        "registrarEnv": "sandbox" if sandbox else "live",
        "registrarApiBaseUrl": _registrar_api_base_url(),
    }


def _registrar_runtime_report(*, for_live_checkout: bool = False) -> dict[str, Any]:
    reg = active_registrar()
    return reg.validate_runtime(for_live_checkout=for_live_checkout)


def _require_registrar_runtime(
    *,
    for_checkout: bool = False,
    allow_demo_skip: bool = True,
) -> None:
    """Block checkout/provision when the active registrar env is misconfigured.

    Paid provision must pass ``allow_demo_skip=False`` so demo fallback cannot
    bypass OpenProvider readiness checks.
    """
    if allow_demo_skip and is_demo_mode():
        return
    reg = active_registrar()
    registrar_name = settings.domain_registrar()
    if registrar_name == "resellerclub":
        from app.integrations.resellerclub import runtime_validation as rc_runtime

        report = rc_runtime.validate_resellerclub_runtime(
            for_live_checkout=for_checkout and not settings.resellerclub_use_sandbox(),
        )
    else:
        report = reg.validate_runtime(for_live_checkout=for_checkout and not reg.is_sandbox())
    if report["ready"]:
        return
    detail = "; ".join(report["blockingIssues"])
    raise AppException(
        f"{registrar_name.upper()} is not correctly configured for "
        f"{'live checkout' if for_checkout and not report['sandbox'] else 'current env'}: {detail}",
        status_code=503,
    )


def production_readiness() -> dict[str, Any]:
    """
    Checklist for live registrar + Razorpay. ``ready`` is True when no blocking issues.
    """
    reg_name = settings.domain_registrar()
    reg = active_registrar()
    issues: list[str] = []
    warnings: list[str] = []

    reg_report = _registrar_runtime_report(for_live_checkout=not reg.is_sandbox())
    issues.extend(reg_report["blockingIssues"])
    warnings.extend(reg_report["warnings"])

    if is_demo_mode():
        issues.append(
            "DOMAIN_STOREFRONT_DEMO_FALLBACK is active (simulated pricing/register). "
            "Set DOMAIN_STOREFRONT_DEMO_FALLBACK=false and configure registrar credentials.",
        )
    if not settings.resolved_razorpay_key_id() or not settings.resolved_razorpay_key_secret():
        issues.append("Razorpay KEY_ID / KEY_SECRET missing.")
    if not settings.resolved_razorpay_webhook_secret():
        warnings.append(
            "RAZORPAY_WEBHOOK_SECRET empty — payment may not complete if user closes browser before verify.",
        )
    if rzp.is_test_mode():
        warnings.append("Razorpay keys are test mode — use live keys for production payments.")

    frontend = settings.FRONTEND_BASE_URL.strip()
    if "localhost" in frontend or "127.0.0.1" in frontend:
        if not reg.is_sandbox():
            warnings.append(
                f"FRONTEND_BASE_URL is {frontend} — order emails/links should use https://hubregistrar.com in production.",
            )

    return {
        "ready": len(issues) == 0,
        "registrar": reg_name,
        "registrarConfigured": reg.is_configured(),
        "registrarSandbox": reg.is_sandbox(),
        "registrarEnv": "sandbox" if reg.is_sandbox() else "live",
        "demoMode": is_demo_mode(),
        "razorpayTestMode": rzp.is_test_mode(),
        "webhooksEnabled": bool(settings.resolved_razorpay_webhook_secret()),
        "blockingIssues": issues,
        "warnings": warnings,
    }


class DomainRegistrationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._orders = DomainRegistrationOrderRepository(session)
        self._listings = DomainListingRepository(session)
        self._followup = DomainRegistrationFollowup(session)

    def storefront_config(self) -> dict[str, Any]:
        demo = is_demo_mode()
        reg = active_registrar()
        name = registrar_source()
        readiness = production_readiness()
        registrar_env = "sandbox" if reg.is_sandbox() else "live"
        message = "Search availability, register securely, and manage your domains with HubRegistrar."
        return {
            "demoMode": demo,
            "razorpayTestMode": rzp.is_test_mode(),
            "registrar": name,
            "registrarConfigured": reg.is_configured(),
            "registrarEnv": registrar_env,
            "registrarSandbox": reg.is_sandbox(),
            "registrarApiBaseUrl": _registrar_api_base_url(),
            "openProviderConfigured": settings.openprovider_configured(),
            "openProviderSandbox": settings.openprovider_use_sandbox(),
            "openProviderApiBaseUrl": settings.resolved_openprovider_api_base_url(),
            "renewalFallbackUnitInr": settings.DOMAIN_STOREFRONT_RENEWAL_FALLBACK_UNIT_INR,
            "authRequired": True,
            "webhooksEnabled": bool(settings.resolved_razorpay_webhook_secret()),
            "productionReadiness": readiness,
            "message": message,
            "gst": gst_settings_for_client(),
        }

    async def get_service_prices(self) -> dict[str, Any]:
        """Fetch live per-TLD prices from OpenProvider with commission markup. Falls back to defaults."""
        from app.integrations import domain_registrar
        from app.service.domain import domain_commission_config as commission
        reg = domain_registrar.active_registrar()

        tlds = ["com", "in", "net", "org", "co", "io", "ai"]
        fallback_inr = settings.DOMAIN_STOREFRONT_RENEWAL_FALLBACK_UNIT_INR or 100.0

        fallback_tld_prices = {
            ".com": 799.0, ".in": 499.0, ".net": 899.0, ".org": 999.0,
            ".co": 1199.0, ".io": 2499.0, ".ai": 4500.0,
        }

        tld_registration_prices: dict[str, float] = {}
        tld_renewal_prices: dict[str, float] = {}
        cheapest_transfer = None

        if reg.is_configured() and hasattr(reg, "get_create_price") and hasattr(reg, "extract_create_price_details"):
            from app.integrations.openprovider.client import (
                get_domain_price,
                extract_create_price_details,
                extract_reseller_price_details,
            )
            import asyncio

            async def _to_inr(price: float, currency: str | None) -> float:
                """Convert a provider price to INR if it's in a foreign currency."""
                cur = (currency or "INR").upper()
                if cur == "INR" or price <= 0:
                    return price
                from app.service.currency.exchange_rate_service import convert_foreign_to_inr
                try:
                    result = convert_foreign_to_inr(price, cur)
                    converted = float(result["amountInr"])
                    logger.info(
                        "[PRICES] FX conversion: %.2f %s → ₹%.2f",
                        price, cur, converted,
                    )
                    return converted
                except Exception as exc:
                    logger.warning(
                        "[PRICES] FX %s→INR failed for price %.2f: %s; using raw",
                        cur, price, exc,
                    )
                    return price

            async def _fetch_one(ext: str) -> tuple[str, float, float, float]:
                try:
                    create_quote = await get_domain_price("mydomain", ext, operation="create", period=1)
                    unit_reg, reg_currency, _ = extract_create_price_details(create_quote)
                    logger.info(
                        "[PRICES] .%s create: raw=%.2f currency=%s",
                        ext, unit_reg, reg_currency,
                    )
                    reg_inr = max(1.0, round(await _to_inr(unit_reg, reg_currency), 2))

                    try:
                        ren_quote = await get_domain_price("mydomain", ext, operation="renew", period=1)
                        ren_unit, ren_currency = extract_reseller_price_details(ren_quote)
                        ren_inr = max(1.0, round(await _to_inr(ren_unit, ren_currency), 2)) if ren_unit else reg_inr
                    except Exception:
                        ren_inr = reg_inr

                    try:
                        xfer_quote = await get_domain_price("mydomain", ext, operation="transfer", period=1)
                        xfer_unit, xfer_currency = extract_reseller_price_details(xfer_quote)
                        xfer_inr = max(1.0, round(await _to_inr(xfer_unit, xfer_currency), 2)) if xfer_unit else ren_inr
                    except Exception:
                        xfer_inr = ren_inr

                    return ext, reg_inr, ren_inr, xfer_inr
                except Exception as exc:
                    logger.warning("[PRICES] Could not fetch price for .%s: %s", ext, exc)
                    fb = fallback_tld_prices.get(f".{ext}", 799.0)
                    return ext, fb, fallback_inr, fallback_inr

            results = await asyncio.gather(*[_fetch_one(ext) for ext in tlds])
            tld_transfer_prices: dict[str, float] = {}
            for ext, reg_price, ren_price, xfer_price in results:
                tld_registration_prices[f".{ext}"] = reg_price
                tld_renewal_prices[f".{ext}"] = ren_price
                tld_transfer_prices[f".{ext}"] = xfer_price
            if tld_transfer_prices:
                cheapest_transfer = min(tld_transfer_prices.values())
        else:
            tld_registration_prices = dict(fallback_tld_prices)
            tld_renewal_prices = {k: fallback_inr for k in fallback_tld_prices}
            tld_transfer_prices = dict(tld_renewal_prices)
            cheapest_transfer = min(fallback_tld_prices.values())

        # Ensure transfer map exists when OP path was taken
        if "tld_transfer_prices" not in locals():
            tld_transfer_prices = dict(tld_renewal_prices)

        # ── Apply commission markup ──────────────────────────────────────────
        comm_cfg = commission.load()

        def _apply(base: float, service: str, tld: str | None = None) -> dict:
            rate = commission.get_rate(service, tld)
            final = commission.apply_markup(base, rate)
            return {"base": round(base, 2), "commissionRate": rate, "final": final}

        # Registration prices by TLD (with per-TLD commission)
        reg_by_tld_detailed = {}
        reg_by_tld_final = {}
        for tld, base in tld_registration_prices.items():
            d = _apply(base, "registration", tld)
            reg_by_tld_detailed[tld] = d
            reg_by_tld_final[tld] = d["final"]

        # Renewal prices by TLD
        ren_by_tld_detailed = {}
        ren_by_tld_final = {}
        for tld, base in tld_renewal_prices.items():
            d = _apply(base, "renewal", tld)
            ren_by_tld_detailed[tld] = d
            ren_by_tld_final[tld] = d["final"]

        # Transfer prices by TLD (operation=transfer, not registration/renew)
        xfer_by_tld_detailed = {}
        xfer_by_tld_final = {}
        for tld, base in tld_transfer_prices.items():
            d = _apply(base, "transfer", tld)
            xfer_by_tld_detailed[tld] = d
            xfer_by_tld_final[tld] = d["final"]

        cheapest_reg_base = min(tld_registration_prices.values()) if tld_registration_prices else 499.0
        cheapest_ren_base = min(tld_renewal_prices.values()) if tld_renewal_prices else fallback_inr
        if tld_transfer_prices:
            cheapest_trans_base = (
                cheapest_transfer
                if cheapest_transfer is not None
                else min(tld_transfer_prices.values())
            )
        else:
            cheapest_trans_base = cheapest_ren_base

        cheapest_reg_final = min(reg_by_tld_final.values()) if reg_by_tld_final else cheapest_reg_base
        cheapest_ren_final = min(ren_by_tld_final.values()) if ren_by_tld_final else cheapest_ren_base
        cheapest_trans_final = min(xfer_by_tld_final.values()) if xfer_by_tld_final else cheapest_trans_base

        email_base = 100.0
        email_d = _apply(email_base, "email")
        easydmarc_base = 499.0
        easydmarc_d = _apply(easydmarc_base, "easydmarc")
        spam_base = 299.0
        spam_d = _apply(spam_base, "spamexperts")

        ssl_block = await self._build_live_ssl_price_block(_apply)

        gst_rate = settings.DOMAIN_GST_RATE if settings.DOMAIN_GST_ENABLED else 0.0
        source = "openprovider" if reg.is_configured() else "fallback"

        return {
            "source": source,
            "gstRate": gst_rate,
            "commissionConfig": comm_cfg,
            "email": {
                "base": email_d["base"],
                "commissionRate": email_d["commissionRate"],
                "unitInr": email_d["final"],
                "label": f"₹{int(email_d['final'])} / month",
                "note": "per mailbox",
            },
            "easydmarc": {
                "base": easydmarc_d["base"],
                "commissionRate": easydmarc_d["commissionRate"],
                "unitInr": easydmarc_d["final"],
                "label": f"₹{int(easydmarc_d['final'])} / yr",
            },
            "spamexperts": {
                "base": spam_d["base"],
                "commissionRate": spam_d["commissionRate"],
                "unitInr": spam_d["final"],
                "label": f"₹{int(spam_d['final'])} / yr",
            },
            "restore": {
                "base": None,
                "commissionRate": commission.get_rate("restore"),
                "unitInr": None,
                "label": "Live restore price",
                "note": "Quoted per domain from OpenProvider",
            },
            "renewal": {
                "base": cheapest_ren_base,
                "commissionRate": commission.get_rate("renewal"),
                "unitInr": cheapest_ren_final,
                "byTld": ren_by_tld_final,
                "byTldDetailed": ren_by_tld_detailed,
                "label": f"From ₹{int(cheapest_ren_final)} / yr",
            },
            "transfer": {
                "base": cheapest_trans_base,
                "commissionRate": commission.get_rate("transfer"),
                "unitInr": cheapest_trans_final,
                "byTld": xfer_by_tld_final,
                "byTldDetailed": xfer_by_tld_detailed,
                "label": f"From ₹{int(cheapest_trans_final)} / yr",
            },
            "registration": {
                "base": cheapest_reg_base,
                "commissionRate": commission.get_rate("registration"),
                "unitInr": cheapest_reg_final,
                "byTld": reg_by_tld_final,
                "byTldDetailed": reg_by_tld_detailed,
                "label": f"From ₹{int(cheapest_reg_final)} / yr",
            },
            "ssl": ssl_block,
            "dnssec": {
                "unitInr": 0.0,
                "label": "Free Setup",
            },
        }

    async def check_openprovider_domain(
        self,
        full_domain: str,
        *,
        include_aftermarket: bool = False,
    ) -> DomainCheckResponse:
        """Check active registrar only; used by homepage \"New Domains\" search.

        ``include_aftermarket=False`` (default) keeps search fast — Afternic/Sedo
        premiums are loaded via ``search_premium_marketplace``. Checkout uses
        ``check_registration_domain`` which enables aftermarket.
        """
        full_domain = compose_search_fqdn(full_domain)
        if not full_domain:
            raise AppException(
                "Invalid domain format. Use name.tld e.g. example.com",
                status_code=400,
            )
        name, _, ext_no_dot = full_domain.partition(".")
        if not name or not ext_no_dot:
            raise AppException(
                "Invalid domain format. Use name.tld e.g. example.com",
                status_code=400,
            )
        # This endpoint reports availability sourced from the active registrar;
        # the literal "registrar" is the stable contract value for the homepage
        # "New Domains" search (see DomainCheckResponse.source). The storefront
        # full check (check_registration_domain) re-labels the source after
        # delegating to this method.
        source = "registrar"

        reg = active_registrar()
        registrar_meta = _registrar_check_fields()
        if not reg.is_configured():
            if is_demo_mode():
                demo_unit = 499.0
                return DomainCheckResponse(
                    status="available",
                    domain=full_domain,
                    priceCurrency="INR",
                    minPeriodYears=1,
                    source=source,
                    demoMode=True,
                    message=f"Demo mode: {source} credentials not configured",
                    **_registration_pricing_fields(demo_unit, 1),
                    **registrar_meta,
                )
            raise AppException(
                "Domain availability check is not configured. "
                "Set registrar API credentials in the environment.",
                status_code=503,
            )

        try:
            try:
                check = await reg.check_domain(
                    name,
                    ext_no_dot,
                    include_aftermarket=include_aftermarket,
                )
            except TypeError:
                # Older registrar stubs may not accept include_aftermarket.
                check = await reg.check_domain(name, ext_no_dot)
        except Exception as exc:
            logger.exception(
                "%s check failed domain=%s",
                source,
                full_domain,
            )
            if is_demo_mode():
                logger.warning("Falling back to demo mode due to registrar check failure: %s", exc)
                demo_unit = 499.0
                return DomainCheckResponse(
                    status="available",
                    domain=full_domain,
                    priceCurrency="INR",
                    minPeriodYears=1,
                    source=source,
                    demoMode=True,
                    message=f"Demo mode fallback: {source} check failed ({exc})",
                    **_registration_pricing_fields(demo_unit, 1),
                    **registrar_meta,
                )
            detail = str(exc).strip() or f"{source} request failed."
            raise AppException(
                "Could not verify domain availability with the registrar. "
                f"{detail}",
                status_code=http_status_for_openprovider_error(detail),
            ) from exc

        if not reg.is_free(check):
            return DomainCheckResponse(
                status="taken",
                domain=full_domain,
                price=None,
                listing=None,
                source=source,
                **registrar_meta,
            )

        await _warm_tld_min_period(reg, ext_no_dot)
        min_period = reg.resolve_registration_period(1, ext_no_dot)

        # Search uses CheckDomain(with_price) only — do not call GetPrice here.
        # GetPrice(period=N) is reserved for checkout / period re-quotes.
        unit_price = 0.0
        price_currency: str | None = None
        price_source = f"{source}_check"
        unit_price, price_currency, price_source = reg.extract_create_price_details(
            check,
            source_hint=f"{source}_check",
        )

        if unit_price <= 0:
            if is_demo_mode():
                unit_price = 499.0
                price_currency = "INR"
            else:
                raise AppException(
                    "Could not determine live registration price from the registrar. "
                    "The domain may not be available for registration.",
                    status_code=502,
                )

        # domains/check with_price embeds the TLD minimum period total for TLDs
        # like .ai (2yr). Normalize to a 1-year storefront unit.
        if not (is_demo_mode() and unit_price == 499.0):
            normalizer = getattr(reg, "yearly_create_price_from_check", None)
            if callable(normalizer):
                normalized = normalizer(unit_price, ext_no_dot)
                if not hasattr(normalized, "__await__"):
                    unit_price = float(normalized)

        is_premium = bool(check.get("is_premium"))
        from app.service.domain import domain_commission_config as commission

        priced = commission.calculate_customer_price(
            unit_price,
            is_premium=is_premium,
            service=commission.CommissionService.REGISTRATION,
            currency=price_currency or "INR",
            tld=ext_no_dot,
        )
        unit_inr = float(priced["customerUnitInr"])

        logger.info(
            "analytics.premium_search domain=%s is_premium=%s provider_inr=%s customer_inr=%s",
            full_domain,
            is_premium,
            priced["providerUnitInr"],
            unit_inr,
        )

        whois_allowed: bool | None = None
        if hasattr(reg, "is_private_whois_allowed"):
            try:
                whois_allowed = bool(await reg.is_private_whois_allowed(ext_no_dot))
            except Exception:
                whois_allowed = None

        renewal_inr: float | None = None
        # ── Step 1: try to extract renewal price from OpenProvider check result ──
        if hasattr(reg, "extract_renewal_price_details"):
            try:
                extracted = reg.extract_renewal_price_details(check)
                if hasattr(extracted, "__await__"):
                    extracted = await extracted
                logger.info(
                    "[RENEWAL_PRICE] domain=%s step=extract_from_check raw_extracted=%s",
                    full_domain, extracted,
                )
                if isinstance(extracted, tuple) and len(extracted) == 2:
                    renew_unit_price, renew_currency = extracted
                    logger.info(
                        "[RENEWAL_PRICE] domain=%s step=extract_from_check renew_unit_price=%s renew_currency=%s",
                        full_domain, renew_unit_price, renew_currency,
                    )
                    if renew_unit_price is not None and renew_unit_price > 0:
                        code = (price_currency or renew_currency or "INR").upper()
                        if code != "INR":
                            from app.service.currency.exchange_rate_service import convert_foreign_to_inr
                            converted = convert_foreign_to_inr(renew_unit_price, code)
                            renewal_inr = round(float(converted["amountInr"]), 2)
                        else:
                            renewal_inr = round(float(renew_unit_price), 2)
                        logger.info(
                            "[RENEWAL_PRICE] domain=%s step=extract_from_check resolved renewal_inr=%s",
                            full_domain, renewal_inr,
                        )
            except Exception as exc:
                logger.warning("Could not extract explicit renewal price for %s: %s", full_domain, exc)

        # ── Step 2: fallback — call OpenProvider GetPrice(operation=renew) ──
        # IMPORTANT: use the actual domain name (not "example") so OpenProvider
        # returns the correct premium renewal price for name-specific premium domains.
        if renewal_inr is None:
            logger.info(
                "[RENEWAL_PRICE] domain=%s step=check_result_had_no_renew is_premium=%s "
                "falling_back_to=GetPrice(operation=renew)",
                full_domain, is_premium,
            )
            try:
                from app.integrations.openprovider.client import get_domain_price, extract_getprice_renewal_details
                # Use the real domain name so premium name-specific pricing is returned.
                ren_quote = await get_domain_price(name, ext_no_dot, operation="renew", period=1)
                logger.info(
                    "[RENEWAL_PRICE] domain=%s step=GetPrice_renew raw_quote=%s",
                    full_domain, ren_quote,
                )
                ren_unit, ren_curr = extract_getprice_renewal_details(ren_quote)
                logger.info(
                    "[RENEWAL_PRICE] domain=%s step=GetPrice_renew ren_unit=%s ren_curr=%s",
                    full_domain, ren_unit, ren_curr,
                )
                if ren_unit and ren_unit > 0:
                    code = (ren_curr or "INR").upper()
                    if code != "INR":
                        from app.service.currency.exchange_rate_service import convert_foreign_to_inr
                        converted = convert_foreign_to_inr(ren_unit, code)
                        renewal_inr = round(float(converted["amountInr"]), 2)
                    else:
                        renewal_inr = round(float(ren_unit), 2)
                    logger.info(
                        "[RENEWAL_PRICE] domain=%s step=GetPrice_renew resolved renewal_inr=%s",
                        full_domain, renewal_inr,
                    )
                else:
                    logger.warning(
                        "[RENEWAL_PRICE] domain=%s step=GetPrice_renew returned no usable price ren_unit=%s",
                        full_domain, ren_unit,
                    )
            except Exception as exc:
                logger.warning(
                    "[RENEWAL_PRICE] domain=%s step=GetPrice_renew FAILED: %s",
                    full_domain, exc,
                )

        logger.info(
            "[RENEWAL_PRICE] domain=%s step=final_backend_value renewal_inr=%s "
            "(None means frontend will show 'Renewal price unavailable')",
            full_domain, renewal_inr,
        )

        return DomainCheckResponse(
            status="available",
            domain=full_domain,
            priceCurrency="INR",
            priceSource=price_source,
            minPeriodYears=min_period,
            source=source,
            demoMode=is_demo_mode() and float(unit_price) == 499.0 and not is_premium,
            isPremium=is_premium,
            whoisPrivacyAllowed=whois_allowed,
            renewalPrice=renewal_inr,
            renewalPriceInr=renewal_inr,
            # Storefront always exposes the 1-year customer price.
            **_registration_pricing_fields(unit_inr, 1),
            **registrar_meta,
        )

    async def search_openprovider_tlds(
        self,
        label: str,
        page: int = 1,
        page_size: int = 50,
        chunk: int | None = None,
        chunk_size: int = 12,
    ) -> dict[str, Any]:
        """
        Return every OpenProvider extension available for a label, with
        registration + renewal pricing, sorted ascending by registration price.

        No TLD whitelist is applied and the full OpenProvider response is used;
        pagination only slices the already-fetched list for frontend UX.

        Optional ``chunk`` (0-based) on page 1 returns one progressive wave of the
        curated priority TLDs so the Homepage can paint cards and drive a real
        progress bar as each wave finishes. Omitting ``chunk`` keeps the legacy
        single-shot first page (Storefront / Load more).
        """
        from app.integrations.openprovider.client import (
            search_domains_label_first_page,
            search_domains_label_first_page_chunk,
            search_domains_label_remaining,
        )

        label = _sanitize_sld(label)
        if not label:
            raise AppException("Query param 'name' is required.", status_code=400)

        if not settings.openprovider_configured() and not is_demo_mode():
            raise AppException(
                "Domain availability search is not configured. "
                "Set OpenProvider API credentials in the environment.",
                status_code=503,
            )

        page = max(1, page)
        page_size = max(1, min(page_size, 2000))
        chunk_size = max(1, min(int(chunk_size or 12), 60))

        cache_key = (
            f"{label}:{page}"
            if chunk is None
            else f"{label}:{page}:c{int(chunk)}:s{chunk_size}"
        )
        cached = _tld_search_cache_get(cache_key)
        if cached is not None:
            return {**cached, "pageSize": page_size}

        if page == 1 and chunk is not None:
            try:
                raw_results, chunk_index, chunk_total, more_chunks = (
                    await search_domains_label_first_page_chunk(
                        label,
                        chunk_index=max(0, int(chunk)),
                        chunk_size=chunk_size,
                    )
                )
            except Exception as exc:
                logger.exception(
                    "[TLD_SEARCH] OpenProvider first-page chunk failed for %s chunk=%s",
                    label,
                    chunk,
                )
                detail = str(exc).strip() or "Registrar request failed."
                # Never expose registrar vendor names (e.g. OpenProvider) to end users.
                if "openprovider" in detail.lower() or "open provider" in detail.lower():
                    user_msg = (
                        "Could not fetch available extensions from the registrar. "
                        "Please try again shortly."
                    )
                else:
                    user_msg = (
                        "Could not fetch available extensions from the registrar. "
                        f"{detail}"
                    )
                raise AppException(
                    user_msg,
                    status_code=http_status_for_openprovider_error(detail),
                ) from exc

            items = [it for it in self._build_tld_items(raw_results, label) if it.get("available")]
            # Fetch missing renewal prices for premium / high-registration-price domains in this chunk
            chunk_premium_items = [
                it for it in items
                if (it.get("isPremium") or (it.get("registrationPrice") and it.get("registrationPrice") > 2000))
                and it.get("renewalPrice") is None
            ]
            if chunk_premium_items:
                from app.integrations.openprovider.client import (
                    get_domain_price,
                    extract_getprice_renewal_details,
                )
                import asyncio
                async def _fetch_renewal_chunk(item):
                    try:
                        ren_quote = await get_domain_price(item["name"], item["tld"].lstrip("."), operation="renew", period=1)
                        ren_unit, ren_curr = extract_getprice_renewal_details(ren_quote)
                        if ren_unit and ren_unit > 0:
                            if ren_curr and ren_curr.upper() != "INR":
                                from app.service.currency.exchange_rate_service import convert_foreign_to_inr
                                conv = convert_foreign_to_inr(ren_unit, ren_curr.upper())
                                renewal_inr = round(float(conv["amountInr"]), 2)
                            else:
                                renewal_inr = round(float(ren_unit), 2)
                            item["renewalPrice"] = renewal_inr
                            if ren_quote.get("is_premium") or ren_quote.get("isPremium"):
                                item["isPremium"] = True
                                item["registryTier"] = "premium"
                            logger.info("[RENEWAL_FETCH][CHUNK] domain=%s renewal=%s", item["domain"], renewal_inr)
                    except Exception as exc:
                        logger.warning("[RENEWAL_FETCH][CHUNK] failed for %s: %s", item["domain"], exc)
                await asyncio.gather(*[_fetch_renewal_chunk(it) for it in chunk_premium_items])
            payload = {
                "label": label,
                "source": registrar_source(),
                "total": len(items),
                "page": 1,
                "pageSize": page_size,
                "totalPages": 2,
                "moreAvailable": True,
                "chunkIndex": chunk_index,
                "chunkTotal": chunk_total,
                "moreChunks": more_chunks,
                "items": items,
            }
            _tld_search_cache_put(cache_key, payload)
            return payload

        if page == 1:
            # ── Fast first page ──────────────────────────────────────────────
            # Only the curated priority TLDs, checked in one concurrent wave.
            # Aftermarket premiums are loaded separately via search-premium.
            try:
                raw_results, _more, _token = await search_domains_label_first_page(label)
            except Exception as exc:
                logger.exception("[TLD_SEARCH] OpenProvider first-page search failed for %s", label)
                detail = str(exc).strip() or "Registrar request failed."
                if "openprovider" in detail.lower() or "open provider" in detail.lower():
                    user_msg = (
                        "Could not fetch available extensions from the registrar. "
                        "Please try again shortly."
                    )
                else:
                    user_msg = (
                        "Could not fetch available extensions from the registrar. "
                        f"{detail}"
                    )
                raise AppException(
                    user_msg,
                    status_code=http_status_for_openprovider_error(detail),
                ) from exc

            # Build items list for first page
            items = [it for it in self._build_tld_items(raw_results, label) if it.get("available")]
            # Fetch missing renewal prices for premium / high-tier domains on this page
            premium_items = [
                it for it in items
                if (it.get("isPremium") or (it.get("registrationPrice") and it.get("registrationPrice") > 2000))
                and it.get("renewalPrice") is None
            ]
            if premium_items:
                from app.integrations.openprovider.client import (
                    get_domain_price,
                    extract_getprice_renewal_details,
                )
                import asyncio
                async def _fetch_renewal(item):
                    try:
                        ren_quote = await get_domain_price(item["name"], item["tld"].lstrip("."), operation="renew", period=1)
                        ren_unit, ren_curr = extract_getprice_renewal_details(ren_quote)
                        if ren_unit and ren_unit > 0:
                            if ren_curr and ren_curr.upper() != "INR":
                                from app.service.currency.exchange_rate_service import convert_foreign_to_inr
                                conv = convert_foreign_to_inr(ren_unit, ren_curr.upper())
                                renewal_inr = round(float(conv["amountInr"]), 2)
                            else:
                                renewal_inr = round(float(ren_unit), 2)
                            item["renewalPrice"] = renewal_inr
                            if ren_quote.get("is_premium") or ren_quote.get("isPremium"):
                                item["isPremium"] = True
                                item["registryTier"] = "premium"
                            logger.info("[RENEWAL_FETCH][PAGE1] domain=%s renewal=%s isPremium=%s", item["domain"], renewal_inr, item.get("isPremium"))
                    except Exception as exc:
                        logger.warning("[RENEWAL_FETCH][PAGE1] failed for %s: %s", item["domain"], exc)
                await asyncio.gather(*[_fetch_renewal(it) for it in premium_items])
            payload = {
                "label": label,
                "source": registrar_source(),
                "total": len(items),
                "page": 1,
                "pageSize": page_size,
                "totalPages": 2,
                # The remaining catalog is always fetched on demand, so advertise
                # that more pages exist; page 2 resolves whether any remain.
                "moreAvailable": True,
                "items": items,
            }
            _tld_search_cache_put(cache_key, payload)
            return payload

        # ── Load more (page >= 2) ────────────────────────────────────────────
        # Scan exactly ONE bounded window of the remaining catalog per request.
        offset = (page - 2) * _TLD_REMAINING_WINDOW
        try:
            rem_raw, more_available, _token = await search_domains_label_remaining(
                label, offset=offset, chunk_size=_TLD_REMAINING_WINDOW
            )
        except Exception as exc:
            logger.warning(
                "[TLD_SEARCH] Remaining-catalog fetch failed for %s (page %s): %s",
                label, page, exc,
            )
            rem_raw, more_available = [], False

        items = []
        for it in self._build_tld_items(list(rem_raw), label):
            if not it.get("available"):
                continue
            price = it.get("registrationPrice")
            # Keep premium inventory visible even when customer price is high.
            if it.get("isPremium"):
                items.append(it)
            elif price is not None and price < 3000:
                items.append(it)
        # Fetch missing renewal prices for premium / high-tier domains in this page
        premium_items = [
            it for it in items
            if (it.get("isPremium") or (it.get("registrationPrice") and it.get("registrationPrice") > 2000))
            and it.get("renewalPrice") is None
        ]
        if premium_items:
            from app.integrations.openprovider.client import (
                get_domain_price,
                extract_getprice_renewal_details,
            )
            import asyncio
            async def _fetch_renewal(item):
                try:
                    ren_quote = await get_domain_price(item["name"], item["tld"].lstrip("."), operation="renew", period=1)
                    ren_unit, ren_curr = extract_getprice_renewal_details(ren_quote)
                    if ren_unit and ren_unit > 0:
                        if ren_curr and ren_curr.upper() != "INR":
                            from app.service.currency.exchange_rate_service import convert_foreign_to_inr
                            conv = convert_foreign_to_inr(ren_unit, ren_curr.upper())
                            renewal_inr = round(float(conv["amountInr"]), 2)
                        else:
                            renewal_inr = round(float(ren_unit), 2)
                        item["renewalPrice"] = renewal_inr
                        if ren_quote.get("is_premium") or ren_quote.get("isPremium"):
                            item["isPremium"] = True
                            item["registryTier"] = "premium"
                        logger.info("[RENEWAL_FETCH][PAGE2+] domain=%s renewal=%s isPremium=%s", item["domain"], renewal_inr, item.get("isPremium"))
                except Exception as exc:
                    logger.warning("[RENEWAL_FETCH][PAGE2+] failed for %s: %s", item["domain"], exc)
            await asyncio.gather(*[_fetch_renewal(it) for it in premium_items])
        items.sort(key=lambda x: x.get("registrationPrice") or float("inf"))

        payload = {
            "label": label,
            "source": registrar_source(),
            "total": len(items),
            "page": page,
            "pageSize": page_size,
            "totalPages": page + 1 if more_available else page,
            "moreAvailable": more_available,
            "items": items,
        }
        _tld_search_cache_put(cache_key, payload)
        return payload

    @staticmethod
    def _build_tld_items(raw_results: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
        from app.service.domain import domain_commission_config as commission

        items: list[dict[str, Any]] = []
        for entry in raw_results:
            fqdn = entry.get("domain") or ""
            name = entry.get("name") or label
            ext = entry.get("extension") or ""
            if not ext and "." in fqdn:
                ext = fqdn.split(".", 1)[1]
            if not ext:
                continue
            ext_lc = ext.lower().lstrip(".")
            # Premium ≠ taken. Use shared OpenProvider availability helper.
            from app.integrations.openprovider.client import is_free as op_is_free

            is_available = op_is_free(entry)
            is_premium = bool(entry.get("is_premium"))
            premium_block = entry.get("premium") if isinstance(entry.get("premium"), dict) else None

            price_block = entry.get("price") or {}
            reseller = price_block.get("reseller") if isinstance(price_block, dict) else None
            product = price_block.get("product") if isinstance(price_block, dict) else None

            def _num(block, key):
                if not isinstance(block, dict):
                    return None
                val = block.get(key)
                if val is None:
                    return None
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return None

            def _positive_num(block, key):
                val = _num(block, key)
                return val if val is not None and val > 0 else None

            premium_price = None
            if isinstance(premium_block, dict):
                raw_price = premium_block.get("price")
                if isinstance(raw_price, dict):
                    premium_price = raw_price
                elif raw_price is not None:
                    premium_price = {"create": raw_price}
                    # Do not assume scalar premium.price also represents renewal.
                    # Renewal must come from an explicit 'renew' field or dedicated OP renew quote.

            create_raw = None
            # Reseller/product first (OpenProvider billable base); premium.create is fallback.
            if isinstance(reseller, dict):
                create_raw = _positive_num(reseller, "price")
            if create_raw is None and isinstance(product, dict):
                create_raw = _positive_num(product, "price")
            if create_raw is None:
                create_raw = _positive_num(price_block, "create")
            if create_raw is None and isinstance(premium_price, dict):
                create_raw = _positive_num(premium_price, "create")

            renew_raw = None
            if isinstance(reseller, dict):
                renew_raw = _positive_num(reseller, "renew")
            if renew_raw is None and isinstance(product, dict):
                renew_raw = _positive_num(product, "renew")
            if renew_raw is None:
                renew_raw = _positive_num(price_block, "renew")
            if renew_raw is None and isinstance(premium_price, dict):
                renew_raw = _positive_num(premium_price, "renew")
                # Additional fallback: top-level premium block may contain a direct 'renew' field
                if renew_raw is None and isinstance(premium_block, dict):
                    renew_raw = _positive_num(premium_block, "renew")
            currency = None
            if isinstance(reseller, dict) and reseller.get("currency"):
                currency = str(reseller["currency"]).upper()
            elif isinstance(product, dict) and product.get("currency"):
                currency = str(product["currency"]).upper()
            elif isinstance(price_block, dict):
                currency = str(price_block.get("currency") or "").upper() or None

            # Optional panel-INR uplift (OPENPROVIDER_PANEL_INR_FACTOR > 1 only).
            # Default factor is 1.0 so list/card/checkout share raw reseller INR.
            from app.integrations.openprovider.client import (
                _panel_inr_create_price,
                tld_min_registration_years,
                yearly_create_price_from_check,
            )
            if create_raw is not None and create_raw > 0:
                panel_create = _panel_inr_create_price(entry, create_raw)
                if panel_create is not None and panel_create > 0:
                    create_raw = float(panel_create)
                # Check/list prices for min-period TLDs (.ai) are full-period totals.
                create_raw = yearly_create_price_from_check(create_raw, ext_lc)
            if renew_raw is not None and renew_raw > 0:
                panel_renew = _panel_inr_create_price(entry, renew_raw)
                if panel_renew is not None and panel_renew > 0:
                    renew_raw = float(panel_renew)

            registration_inr = None
            provider_unit_inr = None
            if create_raw is not None and create_raw > 0:
                priced = commission.calculate_customer_price(
                    create_raw,
                    is_premium=is_premium,
                    service=commission.CommissionService.REGISTRATION,
                    currency=currency or "INR",
                    tld=ext_lc,
                )
                registration_inr = float(priced["customerUnitInr"])
                provider_unit_inr = float(priced["providerUnitInr"])

            renewal_inr = None
            if renew_raw is not None and renew_raw > 0:
                code = (currency or "INR").upper()
                if code != "INR":
                    from app.service.currency.exchange_rate_service import convert_foreign_to_inr
                    try:
                        converted = convert_foreign_to_inr(renew_raw, code)
                        renewal_inr = round(float(converted["amountInr"]), 2)
                    except Exception:
                        renewal_inr = round(float(renew_raw), 2)
                else:
                    renewal_inr = round(float(renew_raw), 2)

            items.append({
                "domain": fqdn or f"{name}.{ext_lc}",
                "name": name,
                "tld": f".{ext_lc}",
                "status": "available" if is_available else "taken",
                "available": is_available,
                "isPremium": is_premium,
                "registryTier": "premium" if is_premium else "standard",
                "registrationPrice": registration_inr,
                "renewalPrice": renewal_inr,
                "providerUnitPriceInr": provider_unit_inr,
                "currency": currency,
                "minPeriodYears": tld_min_registration_years(ext_lc),
                "source": registrar_source(),
            })

        return items

    async def check_registration_domain(
        self,
        full_domain: str,
        *,
        include_aftermarket: bool = True,
    ) -> DomainCheckResponse:
        """
        Storefront / full registration pre-check.

        1. HubRegistrar marketplace listing (if listed and not taken down)
        2. Active registrar availability + price

        ``include_aftermarket=True`` (default) is required for checkout / cart so
        Afternic/Sedo premiums are purchasable. The storefront search HTTP check
        should pass ``include_aftermarket=False`` and load premiums via
        ``search_premium_marketplace`` so Standard results are not blocked.
        """
        full_domain = compose_search_fqdn(full_domain)
        if not full_domain:
            raise AppException(
                "Invalid domain format. Use name.tld e.g. example.com",
                status_code=400,
            )
        name, _, ext_no_dot = full_domain.partition(".")
        ext_dot = f".{ext_no_dot}"

        listing = await self._listings.find_active_by_name(name, ext_dot)
        if listing is not None:
            snippet = _listing_snippet(listing)
            return DomainCheckResponse(
                status="marketplace",
                domain=full_domain,
                price=snippet.askingPrice,
                listing=snippet,
                source="marketplace",
                message="Domain is listed on HubRegistrar marketplace",
            )

        result = await self.check_openprovider_domain(
            full_domain,
            include_aftermarket=include_aftermarket,
        )
        # The storefront full check labels the source with the active registrar
        # name (e.g. "openprovider") rather than the generic "registrar".
        result.source = registrar_source()
        return result

    async def search_premium_marketplace(self, label: str) -> dict[str, Any]:
        """Background Afternic/Sedo premium lookup (cached). Does not block Standard search."""
        from app.integrations.openprovider.client import lookup_aftermarket_premium_checks

        label = _sanitize_sld(label)
        if not label:
            raise AppException("Query param 'name' is required.", status_code=400)

        raw = await lookup_aftermarket_premium_checks(label)
        items = [
            it for it in self._build_tld_items(raw, label)
            if it.get("available") and it.get("isPremium")
        ]
        # Fetch missing renewal prices for premium domains in marketplace search
        premium_items = [it for it in items if it.get("renewalPrice") is None]
        if premium_items:
            from app.integrations.openprovider.client import (
                get_domain_price,
                extract_getprice_renewal_details,
            )
            import asyncio
            async def _fetch_renewal(item):
                try:
                    ren_quote = await get_domain_price(item["name"], item["tld"].lstrip("."), operation="renew", period=1)
                    ren_unit, ren_curr = extract_getprice_renewal_details(ren_quote)
                    if ren_unit and ren_unit > 0:
                        if ren_curr and ren_curr.upper() != "INR":
                            from app.service.currency.exchange_rate_service import convert_foreign_to_inr
                            conv = convert_foreign_to_inr(ren_unit, ren_curr.upper())
                            renewal_inr = round(float(conv["amountInr"]), 2)
                        else:
                            renewal_inr = round(float(ren_unit), 2)
                        item["renewalPrice"] = renewal_inr
                        if ren_quote.get("is_premium") or ren_quote.get("isPremium"):
                            item["isPremium"] = True
                            item["registryTier"] = "premium"
                        logger.info("[RENEWAL_FETCH][PREMIUM_MARKETPLACE] domain=%s renewal=%s", item["domain"], renewal_inr)
                except Exception as exc:
                    logger.warning("[RENEWAL_FETCH][PREMIUM_MARKETPLACE] failed for %s: %s", item["domain"], exc)
            await asyncio.gather(*[_fetch_renewal(it) for it in premium_items])

        items.sort(key=lambda x: x.get("registrationPrice") or float("inf"))
        logger.info(
            "analytics.premium_search label=%s count=%s",
            label,
            len(items),
        )
        return {
            "label": label,
            "source": registrar_source(),
            "total": len(items),
            "items": items,
        }

    async def create_order(self, body: dict[str, Any], *, buyer: AppUser) -> dict[str, Any]:
        _require_registrar_runtime(for_checkout=not settings.openprovider_use_sandbox())
        full_domain = str(body.get("domain", "")).lower().strip()
        check = await self.check_registration_domain(full_domain)
        if check.status == "marketplace":
            raise AppException("Domain is listed on HubRegistrar marketplace.", status_code=400)
        if check.status != "available":
            raise AppException("Domain is not available for registration.", status_code=400)

        period = max(1, int(body.get("period") or 1))
        dot = full_domain.find(".")
        name = full_domain[:dot]
        ext_dot = "." + full_domain[dot + 1 :]
        ext_no_dot = full_domain[dot + 1 :]
        reg = active_registrar()
        period = reg.resolve_registration_period(period, ext_no_dot)

        # OP create-price for period=N is the full N-year total. Store that as
        # the order subtotal (years=1 on GST helper) and keep per-year for records.
        quote = await self.quote_registration_period_price(full_domain, period)
        period_total = float(quote.get("price") or 0)
        per_year = float(quote.get("pricePerYear") or 0)
        if period_total <= 0:
            raise AppException("Could not determine registration price.", status_code=400)
        if per_year <= 0:
            per_year = round(period_total / period, 2)
        pricing = domain_price_breakdown(period_total, years=1)
        price_source = str(quote.get("priceSource") or "checkout")
        redeem_points = bool(body.get("redeemPoints") or body.get("redeem_points"))

        contact = body.get("contact") or {}
        for key in ("firstName", "lastName", "email", "phone", "street", "city", "state", "zip"):
            if not contact.get(key):
                raise AppException(f"Contact field '{key}' is required.", status_code=400)
        gstin_raw = str(contact.get("gstin") or "").strip()
        if gstin_raw:
            from app.utils.field_validators import normalize_gstin

            try:
                contact["gstin"] = normalize_gstin(gstin_raw)
            except ValueError as exc:
                raise AppException(str(exc), status_code=400) from exc
        else:
            contact.pop("gstin", None)

        order = DomainRegistrationOrder(
            domain_name=name,
            domain_extension=ext_dot,
            buyer_id=buyer.id,
            buyer_full_name=f"{contact['firstName']} {contact['lastName']}".strip(),
            buyer_email=str(contact["email"]),
            buyer_phone=str(contact["phone"]),
            street=str(contact["street"]),
            city=str(contact["city"]),
            state=str(contact["state"]),
            zip_code=str(contact["zip"]),
            country=str(contact.get("country") or "IN"),
            buyer_gstin=(
                str(contact.get("gstin") or "").strip().upper() or None
            ),
            period_years=period,
            subtotal_inr=pricing["subtotalInr"],
            gst_inr=pricing["gstInr"],
            price_inr=pricing["totalInr"],
            quoted_unit_price_inr=per_year,
            price_source=price_source,
            is_premium=bool(quote.get("isPremium") or getattr(check, "isPremium", False)),
            registry_tier=str(
                quote.get("registryTier")
                or (
                    "premium"
                    if (quote.get("isPremium") or getattr(check, "isPremium", False))
                    else "standard"
                )
            ),
            provider_unit_price_inr=(
                float(quote["providerUnitPriceInr"])
                if quote.get("providerUnitPriceInr") is not None
                else None
            ),
            status=RegistrationOrderStatus.CREATED,
        )

        price_to_charge = pricing["totalInr"]
        points_redeemed = 0
        if price_to_charge > 0:
            from app.service.user.edge_points_service import EdgePointsService
            price_to_charge, points_redeemed = await EdgePointsService.calculate_redemption(
                self._session, buyer, price_to_charge, redeem_points
            )

        rzp_order = rzp.create_order(
            amount_inr=price_to_charge,
            receipt=f"dreg_{name}_{int(datetime.now(timezone.utc).timestamp())}",
            notes={
                "type": "domain_registration",
                "domain": full_domain,
                "buyerId": str(buyer.id),
            },
        )
        if points_redeemed > 0:
            from app.service.user.edge_points_service import EdgePointsService
            await EdgePointsService.create_pending_redemption(
                self._session, buyer.id, rzp_order["id"], points_redeemed
            )
        order.razorpay_order_id = rzp_order["id"]
        order = await self._orders.create(order)
        await self._session.commit()

        return {
            "orderId": order.razorpay_order_id,
            "amount": pricing["totalInr"],
            "subtotalInr": pricing["subtotalInr"],
            "gstInr": pricing["gstInr"],
            "totalInr": pricing["totalInr"],
            "gstRate": pricing["gstRate"],
            "gstEnabled": pricing["gstEnabled"],
            "currency": "INR",
            "keyId": rzp.get_key_id(),
            "registrationOrderId": str(order.id),
            "domain": full_domain,
            "periodYears": period,
        }

    async def verify_and_provision(
        self,
        payload: dict[str, str],
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        _require_registrar_runtime(for_checkout=not settings.openprovider_use_sandbox())
        logger.info(
            "[STOREFRONT_VERIFY_PAYMENT] Starting storefront payment verification for razorpay_order_id=%s, buyer_id=%s",
            payload.get("razorpayOrderId"),
            buyer.id,
        )
        order = await self._orders.get_by_razorpay_order_id(payload["razorpayOrderId"])
        if order is None:
            logger.error("[STOREFRONT_VERIFY_PAYMENT] Order not found for razorpay_order_id=%s", payload.get("razorpayOrderId"))
            raise AppException("Order not found.", status_code=404)
        if order.buyer_id != buyer.id:
            logger.error("[STOREFRONT_VERIFY_PAYMENT] Forbidden: buyer_id mismatch for order_id=%s", order.id)
            raise AppException("Forbidden.", status_code=403)

        if order.status in (
            RegistrationOrderStatus.ACTIVE,
            RegistrationOrderStatus.REGISTRATION_PENDING,
        ):
            if order.status == RegistrationOrderStatus.REGISTRATION_PENDING:
                await self._reconcile_registrar_order(order)
                await self._orders.save(order)
                await self._followup.send_lifecycle_emails(order)
                await self._session.commit()
                order = await self._orders.get_by_id(order.id)
            from app.service.platform.track_record_service import TrackRecordService

            track_service = TrackRecordService(self._session)
            await track_service.record_from_registration_order(
                order,
                cart_batch_id=payload.get("razorpayOrderId"),
            )
            await self._session.commit()
            return self._provision_response(order)

        if order.razorpay_payment_id != payload.get("razorpayPaymentId"):
            if not rzp.verify_payment_signature(
                payload["razorpayOrderId"],
                payload["razorpayPaymentId"],
                payload["razorpaySignature"],
            ):
                logger.error("[STOREFRONT_VERIFY_PAYMENT] Razorpay payment signature verification failed for order_id=%s", order.id)
                from app.service.user.edge_points_service import EdgePointsService
                await EdgePointsService.cancel_redemption(self._session, payload["razorpayOrderId"])
                order.status = RegistrationOrderStatus.FAILED
                await self._orders.save(order)
                await self._session.commit()
                raise AppException("Payment verification failed.", status_code=400)
            order.razorpay_payment_id = payload["razorpayPaymentId"]
            order.status = RegistrationOrderStatus.PAYMENT_COMPLETED
            await self._orders.save(order)
            await self._session.commit()
            logger.info("[STOREFRONT_VERIFY_PAYMENT] Razorpay payment verified & committed to DB: order_id=%s, domain=%s, status=%s", order.id, order.fqdn, order.status)
            from app.service.user.edge_points_service import EdgePointsService
            await EdgePointsService.confirm_redemption(self._session, payload["razorpayOrderId"])

        logger.info("[STOREFRONT_PROVISIONING] Initiating OpenProvider provisioning for order_id=%s, domain=%s", order.id, order.fqdn)
        try:
            await self.provision_order(order)
            await self._orders.save(order)
            await self._session.commit()
            logger.info("[STOREFRONT_PROVISIONING] OpenProvider provisioning complete for order_id=%s, status=%s", order.id, order.status)
        except Exception as exc:
            logger.exception("[STOREFRONT_PROVISIONING] OpenProvider provisioning failed for order_id=%s: %s", order.id, exc)
            try:
                await self._session.rollback()
            except Exception:
                pass
            order.status = RegistrationOrderStatus.PROVISION_FAILED
            order.provision_message = str(exc)[:500]
            self._session.add(order)
            await self._orders.save(order)
            await self._session.commit()

        order = await self._orders.get_by_id(order.id)
        assert order is not None
        try:
            await self._followup.send_lifecycle_emails(order)
            await self._session.commit()
        except Exception as exc:
            logger.warning("[STOREFRONT_PROVISIONING] Lifecycle email sending warning order_id=%s: %s", order.id, exc)
        return self._provision_response(order)

    async def quote_registration_period_price(
        self,
        full_domain: str,
        period_years: int = 1,
        *,
        require_live_price: bool = True,
    ) -> dict[str, Any]:
        """
        Live OpenProvider (or active registrar) selling quote for a registration period.

        OpenProvider ``domains/prices?period=N`` returns the **full N-year create total**
        (not a per-year rate). We apply admin commission once to that total via
        ``calculate_customer_price``.

        When ``require_live_price`` is True (checkout), never fall back to stale
        prices — failures raise AppException (premium gets a dedicated message).
        """
        full_domain = (full_domain or "").lower().strip()
        if "." not in full_domain:
            raise AppException("Invalid domain format.", status_code=400)
        name, ext_no_dot = full_domain.split(".", 1)
        period = max(1, int(period_years or 1))

        reg = active_registrar()
        await _warm_tld_min_period(reg, ext_no_dot)
        period = reg.resolve_registration_period(period, ext_no_dot)

        from app.service.domain import domain_commission_config as commission

        async def _selling_for_period(years: int) -> dict[str, Any]:
            """Return priced quote dict for N years."""
            if not reg.is_configured() and is_demo_mode():
                raw = 499.0 * years
                priced = commission.calculate_customer_price(
                    raw,
                    is_premium=False,
                    service=commission.CommissionService.REGISTRATION,
                    currency="INR",
                    tld=ext_no_dot,
                )
                return {
                    "selling": float(priced["customerUnitInr"]),
                    "provider": float(priced["providerUnitInr"]),
                    "source": "demo",
                    "is_premium": False,
                    "rate": float(priced["commissionRate"]),
                    "currency": "INR",
                }
            try:
                quote = await reg.get_create_price(name, ext_no_dot, period=years)
                raw, cur, source = reg.extract_create_price_details(quote)
                is_prem = bool(quote.get("is_premium"))
            except Exception as exc:
                detail = str(exc).strip() or "Registrar pricing unavailable."
                # Prefer check only to detect premium for a clearer error — never
                # use check price as a checkout charge when GetPrice failed.
                is_prem_hint = False
                try:
                    check = await reg.check_domain(name, ext_no_dot)
                    is_prem_hint = bool(check.get("is_premium"))
                except Exception:
                    is_prem_hint = False
                if is_prem_hint:
                    raise AppException(
                        "Unable to verify the latest premium domain price. Please try again.",
                        status_code=502,
                    ) from exc
                raise AppException(
                    f"Could not fetch registration price for {full_domain} ({years} yr). {detail}",
                    status_code=http_status_for_openprovider_error(detail),
                ) from exc
            raw = round(float(raw or 0), 2)
            if raw <= 0:
                if is_prem:
                    raise AppException(
                        "Unable to verify the latest premium domain price. Please try again.",
                        status_code=502,
                    )
                raise AppException(
                    f"Could not determine registration price for {full_domain} ({years} yr).",
                    status_code=502,
                )
            priced = commission.calculate_customer_price(
                raw,
                is_premium=is_prem,
                service=commission.CommissionService.REGISTRATION,
                currency=cur or "INR",
                tld=ext_no_dot,
            )
            return {
                "selling": float(priced["customerUnitInr"]),
                "provider": float(priced["providerUnitInr"]),
                "source": source,
                "is_premium": is_prem,
                "rate": float(priced["commissionRate"]),
                "currency": cur or "INR",
                "registry_tier": priced["registryTier"],
            }

        period_quote = await _selling_for_period(period)
        if period == 1:
            per_year_quote = period_quote
        else:
            per_year_quote = await _selling_for_period(1)

        return {
            "domain": full_domain,
            "tld": ext_no_dot,
            "periodYears": period,
            "minPeriodYears": reg.resolve_registration_period(1, ext_no_dot),
            "price": float(period_quote["selling"]),
            "pricePerYear": float(per_year_quote["selling"]),
            "registrarTotal": float(period_quote["provider"]),
            "providerUnitPriceInr": float(per_year_quote["provider"]),
            "commissionRate": float(period_quote["rate"]),
            "priceSource": period_quote["source"],
            "isPremium": bool(period_quote["is_premium"]),
            "registryTier": period_quote.get("registry_tier")
            or ("premium" if period_quote["is_premium"] else "standard"),
            "providerCurrency": period_quote.get("currency") or "INR",
        }

    async def _verify_checkout_price(
        self,
        name: str,
        ext_no_dot: str,
        period: int,
        *,
        expected_unit_price: float,
        is_premium_hint: bool = False,
    ) -> tuple[float, str]:
        reg = active_registrar()
        # Demo flag alone must not skip live price checks when registrar is configured.
        if not reg.is_configured():
            if is_demo_mode():
                return expected_unit_price, "checkout"
            raise AppException(
                f"{registrar_source()} is not configured for checkout pricing.",
                status_code=503,
            )

        # expected_unit_price is always the 1-year selling unit (storefront/cart base).
        # Checkout must use live GetPrice — never stale cart prices for premium.
        _ = reg.resolve_registration_period(period, ext_no_dot)
        full_domain = f"{name}.{ext_no_dot}"
        try:
            quote = await self.quote_registration_period_price(full_domain, 1)
        except AppException:
            raise
        except Exception as exc:
            if is_premium_hint:
                raise AppException(
                    "Unable to verify the latest premium domain price. Please try again.",
                    status_code=502,
                ) from exc
            logger.warning(
                "Price check failed during checkout for %s.%s: %s", name, ext_no_dot, exc
            )
            raise AppException(
                "Unable to verify the latest domain price. Please try again.",
                status_code=502,
            ) from exc

        unit_inr_marked_up = float(quote.get("pricePerYear") or quote.get("price") or 0)
        source = str(quote.get("priceSource") or "checkout")
        if unit_inr_marked_up <= 0:
            if bool(quote.get("isPremium")) or is_premium_hint:
                raise AppException(
                    "Unable to verify the latest premium domain price. Please try again.",
                    status_code=502,
                )
            raise AppException(
                "Unable to verify the latest domain price. Please try again.",
                status_code=502,
            )

        tolerance = _PRICE_TOLERANCE_INR
        if abs(unit_inr_marked_up - expected_unit_price) > tolerance:
            raise AppException(
                "Registration price changed at the registrar. Refresh the page and try again.",
                status_code=409,
            )
        return unit_inr_marked_up, source

    def _registrar_order_id(self, order: DomainRegistrationOrder) -> str | None:
        return order.open_provider_domain_id

    async def _refresh_order_row(self, order: DomainRegistrationOrder) -> None:
        """Reload local row so a concurrent webhook/verify commit is visible."""
        refresh = getattr(self._session, "refresh", None)
        if refresh is None:
            return
        try:
            result = refresh(order)
            if hasattr(result, "__await__"):
                await result
        except Exception:
            logger.debug(
                "provision_order.refresh_skipped order_id=%s",
                getattr(order, "id", None),
            )

    def _provision_already_succeeded(self, order: DomainRegistrationOrder) -> bool:
        return order.status in (
            RegistrationOrderStatus.ACTIVE,
            RegistrationOrderStatus.REGISTRATION_PENDING,
        )

    def _apply_registrar_registration(
        self,
        order: DomainRegistrationOrder,
        reg_result: dict[str, Any],
    ) -> None:
        order_id = reg_result.get("id") or reg_result.get("entityid")
        if order_id is not None:
            order.open_provider_domain_id = str(order_id)
        ns_hosts = reg_result.get("nameservers")
        ns_source = reg_result.get("nameserverSource")
        if isinstance(ns_hosts, list) and ns_hosts:
            set_order_nameservers(order, ns_hosts, ns_source or "openprovider")
        attrs = reg_result.get("attributes")
        if isinstance(attrs, dict):
            order.registrar_response_json = json.dumps(attrs)
        order.open_provider_status = (
            str(reg_result.get("status") or reg_result.get("actionstatus") or "")
        )

    async def _reconcile_registrar_order(self, order: DomainRegistrationOrder) -> bool:
        """Confirm registration via active registrar; return True if Active."""
        confirmed, _order = await self._followup.sync_from_registrar(order)
        return confirmed

    def _order_is_paid(self, order: DomainRegistrationOrder) -> bool:
        return bool(str(order.razorpay_payment_id or "").strip())

    def _log_isolated_provision(
        self,
        order: DomainRegistrationOrder,
        *,
        action: str,
        reason: str,
        provider_domain_id: str | None = None,
        level: int = logging.INFO,
    ) -> None:
        logger.log(
            level,
            "provision_order.isolated target_order=%s domain=%s razorpay_order=%s "
            "razorpay_payment=%s provider_domain_id=%s action=%s reason=%s",
            order.id,
            order.fqdn,
            order.razorpay_order_id,
            order.razorpay_payment_id,
            provider_domain_id if provider_domain_id is not None else order.open_provider_domain_id,
            action,
            reason,
        )

    async def _other_orders_with_provider_domain_id(
        self,
        order: DomainRegistrationOrder,
        provider_domain_id: str,
    ) -> list[str]:
        list_fn = getattr(self._orders, "list_by_openprovider_domain_id", None)
        raw = None
        if list_fn is not None:
            try:
                raw = await list_fn(provider_domain_id)
            except TypeError:
                raw = None
        if raw is None:
            get_fn = getattr(self._orders, "get_by_openprovider_domain_id", None)
            if get_fn is None:
                return []
            other = await get_fn(provider_domain_id)
            raw = [other] if other is not None else []
        try:
            rows = list(raw)
        except TypeError:
            return []
        other_ids: list[str] = []
        for row in rows:
            rid = getattr(row, "id", None)
            if rid is None or rid == order.id:
                continue
            try:
                uuid.UUID(str(rid))
            except (TypeError, ValueError, AttributeError):
                continue
            other_ids.append(str(rid))
        return other_ids

    async def _provider_owner_email(
        self,
        reg,
        details: dict[str, Any],
    ) -> str | None:
        from app.service.domain.provider_domain_correlation import (
            emails_from_provider_details,
            owner_handle_from_provider_details,
        )

        emails = emails_from_provider_details(details)
        if emails:
            return next(iter(emails))
        handle = owner_handle_from_provider_details(details)
        get_customer = getattr(reg, "get_customer", None)
        if not handle or get_customer is None:
            return None
        try:
            payload = await get_customer(handle)
        except Exception:
            logger.warning(
                "provision_order.isolated action=attention reason=CUSTOMER_LOOKUP_FAILED "
                "handle_set=%s",
                bool(handle),
            )
            return None
        email = email_from_customer_payload(payload if isinstance(payload, dict) else None)
        return email or None

    async def _verify_provider_domain_belongs_to_order(
        self,
        order: DomainRegistrationOrder,
        reg,
        provider_domain_id: str,
    ) -> ProviderLinkDecision:
        pid = str(provider_domain_id or "").strip()
        paid = self._order_is_paid(order)
        if not paid or not pid:
            return decide_provider_link(
                paid=paid,
                order_fqdn=order.fqdn,
                order_email=order.buyer_email,
                order_handle=order.open_provider_handle,
                order_already_has_provider_id=order.open_provider_domain_id,
                provider_domain_id=pid or None,
                other_order_ids_with_provider_id=[],
                details=None,
                provider_owner_email=None,
            )

        others = await self._other_orders_with_provider_domain_id(order, pid)
        details: dict[str, Any] | None = None
        owner_email: str | None = None
        get_details = getattr(reg, "get_domain_all_details", None)
        if get_details is not None:
            try:
                raw = await get_details(pid)
                if isinstance(raw, dict):
                    details = raw
            except Exception:
                logger.warning(
                    "provision_order.isolated target_order=%s domain=%s "
                    "provider_domain_id=%s action=attention reason=PROVIDER_DETAILS_UNAVAILABLE",
                    order.id,
                    order.fqdn,
                    pid,
                )
        if details is None:
            lookup_record = getattr(reg, "lookup_domain_record_by_fqdn", None)
            if lookup_record is not None:
                try:
                    raw = await lookup_record(order.fqdn)
                except Exception:
                    raw = None
                if isinstance(raw, dict) and str(raw.get("id") or "") == pid:
                    details = raw
        if isinstance(details, dict):
            owner_email = await self._provider_owner_email(reg, details)
        if details is None:
            return ProviderLinkDecision(
                action="attention",
                reason="PROVIDER_DETAILS_UNAVAILABLE",
                provider_domain_id=pid,
            )
        return decide_provider_link(
            paid=paid,
            order_fqdn=order.fqdn,
            order_email=order.buyer_email,
            order_handle=order.open_provider_handle,
            order_already_has_provider_id=order.open_provider_domain_id,
            provider_domain_id=pid,
            other_order_ids_with_provider_id=others,
            details=details,
            provider_owner_email=owner_email,
        )

    async def _attach_and_reconcile_provider_domain(
        self,
        order: DomainRegistrationOrder,
        provider_domain_id: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        from app.service.domain.domain_registration_followup import (
            stamp_registration_pending_since,
        )

        order.open_provider_domain_id = str(provider_domain_id)
        if order.status != RegistrationOrderStatus.ACTIVE:
            order.status = RegistrationOrderStatus.REGISTRATION_PENDING
            stamp_registration_pending_since(order)
            order.provision_message = (
                "Existing registrar domain linked to this paid order; "
                "reconciling provider state."
            )
        confirmed = await self._reconcile_registrar_order(order)
        await self._orders.save(order)
        self._log_isolated_provision(
            order,
            action="reconcile",
            reason=reason,
            provider_domain_id=str(provider_domain_id),
        )
        return {
            "action": "reconcile",
            "skipReason": reason,
            "registerDomainCalled": False,
        } if not confirmed else {
            "action": "reconcile",
            "skipReason": reason,
            "registerDomainCalled": False,
        }

    async def _maybe_reconcile_existing_provider_domain(
        self,
        order: DomainRegistrationOrder,
        reg,
        provider_domain_id: str | None,
        *,
        source: str,
    ) -> dict[str, Any] | None:
        """Attach an existing OpenProvider domain only when it belongs to THIS order.

        Unpaid / new-registration callers get None so DOMAIN_NOT_FREE still applies.
        """
        pid = str(provider_domain_id or "").strip()
        if not pid:
            return None
        decision = await self._verify_provider_domain_belongs_to_order(order, reg, pid)
        self._log_isolated_provision(
            order,
            action=decision.action,
            reason=f"{decision.reason}:{source}",
            provider_domain_id=pid,
            level=logging.WARNING if decision.action == "attention" else logging.INFO,
        )
        if decision.action == "reconcile" and decision.provider_domain_id:
            return await self._attach_and_reconcile_provider_domain(
                order,
                decision.provider_domain_id,
                reason=f"{decision.reason}:{source}",
            )
        if decision.action == "attention":
            order.status = RegistrationOrderStatus.PROVISION_FAILED
            order.provision_message = (
                "Paid order could not be safely linked to the existing registrar "
                f"domain ({decision.reason}). Requires attention."
            )
            await self._orders.save(order)
            return {
                "action": "attention",
                "skipReason": decision.reason,
                "registerDomainCalled": False,
            }
        return None

    async def provision_order(
        self,
        order: DomainRegistrationOrder,
        *,
        return_meta: bool = False,
    ) -> dict | None:
        # ── Transfer safety guard ──────────────────────────────────────────────
        # Domain transfer orders MUST NEVER enter this registration flow.
        # They are handled exclusively by _provision_transfer(), which is called
        # from complete_payment_from_webhook() when is_transfer=True.
        # All other callers (retry_provision, admin_retry, run_provision_retries,
        # stale-pending recovery) funnel through this function, so a single guard
        # here protects every path.
        _is_transfer = (
            order.transfer_status is not None
            and order.transfer_status != "NONE"
        )
        if _is_transfer:
            logger.error(
                "provision_order.REFUSED_TRANSFER domain=%s%s order_id=%s "
                "transfer_status=%s — transfer orders must use _provision_transfer, "
                "NOT provision_order. This is a programming error.",
                order.domain_name,
                order.domain_extension,
                order.id,
                order.transfer_status,
            )
            raise RuntimeError(
                f"provision_order() called on a domain TRANSFER order "
                f"(id={order.id}, domain={order.fqdn}, "
                f"transfer_status={order.transfer_status}). "
                "Transfer orders must be routed to _provision_transfer()."
            )
        # ── /Transfer safety guard ─────────────────────────────────────────────

        meta: dict = {
            "registerDomainCalled": False,
            "skipReason": None,
            "action": None,
        }

        def _done(**kwargs):
            meta.update(kwargs)
            return meta if return_meta else None

        if order.status == RegistrationOrderStatus.ACTIVE:
            self._log_isolated_provision(
                order,
                action="skip",
                reason="ALREADY_ACTIVE",
            )
            logger.info(
                "provision_order.skip reason=ALREADY_ACTIVE domain=%s%s order_id=%s",
                order.domain_name,
                order.domain_extension,
                order.id,
            )
            return _done(action="skip", skipReason="ALREADY_ACTIVE")

        logger.info(
            "provision_order.started domain=%s%s order_id=%s status=%s attempts=%s",
            order.domain_name,
            order.domain_extension,
            order.id,
            order.status,
            order.provision_attempts + 1,
        )

        reg = active_registrar()
        paid = self._order_is_paid(order)
        # Paid orders must never skip registrar readiness via demo fallback.
        _require_registrar_runtime(
            for_checkout=not reg.is_sandbox(),
            allow_demo_skip=not paid,
        )

        order.provision_attempts += 1
        ext_no_dot = order.domain_extension.lstrip(".")

        try:
            if self._registrar_order_id(order):
                logger.info(
                    "provision_order.early reason=EXISTING_REGISTRAR_ORDER_ID "
                    "domain=%s%s order_id=%s registrar_id=%s — reconcile only, "
                    "register_domain NOT called",
                    order.domain_name,
                    order.domain_extension,
                    order.id,
                    self._registrar_order_id(order),
                )
                if await self._reconcile_registrar_order(order):
                    await self._orders.save(order)
                    return _done(
                        action="reconcile_existing_registrar_id",
                        skipReason="EXISTING_REGISTRAR_ORDER_ID_RECONCILED",
                    )
                if order.status == RegistrationOrderStatus.REGISTRATION_PENDING:
                    order.provision_message = (
                        "Registration submitted; waiting for registrar confirmation"
                    )
                    await self._orders.save(order)
                    return _done(
                        action="reconcile_existing_registrar_id",
                        skipReason="EXISTING_REGISTRAR_ORDER_STILL_PENDING",
                    )

            if reg.is_configured() and hasattr(reg, "lookup_order_id_by_domain"):
                existing = await reg.lookup_order_id_by_domain(order.fqdn)
                if existing:
                    reconciled = await self._maybe_reconcile_existing_provider_domain(
                        order,
                        reg,
                        existing,
                        source="LOOKUP_BEFORE_CHECK",
                    )
                    if reconciled is not None:
                        return _done(**reconciled)

            if reg.is_configured():
                check = await reg.check_domain(order.domain_name, ext_no_dot)
                check_status = str((check or {}).get("status") or "")
                check_reason = str(
                    (check or {}).get("reason") or (check or {}).get("message") or ""
                )
                if not reg.is_free(check):
                    if paid:
                        existing_paid = None
                        if hasattr(reg, "lookup_order_id_by_domain"):
                            existing_paid = await reg.lookup_order_id_by_domain(
                                order.fqdn
                            )
                        if existing_paid:
                            reconciled = await self._maybe_reconcile_existing_provider_domain(
                                order,
                                reg,
                                existing_paid,
                                source="LOOKUP_AFTER_NOT_FREE",
                            )
                            if reconciled is not None:
                                return _done(**reconciled)
                        await self._refresh_order_row(order)
                        if self._provision_already_succeeded(order):
                            await self._orders.save(order)
                            self._log_isolated_provision(
                                order,
                                action="skip",
                                reason="ALREADY_IN_FLIGHT_AFTER_NOT_FREE",
                            )
                            return _done(
                                action="skip",
                                skipReason="ALREADY_IN_FLIGHT_AFTER_NOT_FREE",
                            )
                        from app.service.domain.domain_registration_followup import (
                            stamp_registration_pending_since,
                        )

                        order.status = RegistrationOrderStatus.REGISTRATION_PENDING
                        order.provision_message = (
                            "Payment captured; registrar reports the domain is no "
                            "longer free. Waiting for webhook/reconcile confirmation."
                        )
                        stamp_registration_pending_since(order)
                        await self._orders.save(order)
                        self._log_isolated_provision(
                            order,
                            action="attention",
                            reason="PAID_NOT_FREE_PROVIDER_UNRESOLVED",
                            provider_domain_id=existing_paid,
                            level=logging.WARNING,
                        )
                        logger.warning(
                            "provision_order.deferred reason=DOMAIN_NOT_FREE_PAID "
                            "domain=%s%s order_id=%s check_status=%s check_reason=%s "
                            "— register_domain NOT called",
                            order.domain_name,
                            order.domain_extension,
                            order.id,
                            check_status,
                            check_reason,
                        )
                        return _done(
                            action="attention",
                            skipReason="DOMAIN_NOT_FREE_PAID_PENDING",
                        )
                    order.status = RegistrationOrderStatus.PROVISION_FAILED
                    order.provision_message = "Domain no longer available at registrar"
                    await self._orders.save(order)
                    await self._followup.send_lifecycle_emails(order)
                    self._log_isolated_provision(
                        order,
                        action="skip",
                        reason="DOMAIN_NOT_FREE",
                        level=logging.WARNING,
                    )
                    logger.warning(
                        "provision_order.early reason=DOMAIN_NOT_FREE "
                        "domain=%s%s order_id=%s check_status=%s check_reason=%s "
                        "— register_domain NOT called",
                        order.domain_name,
                        order.domain_extension,
                        order.id,
                        check_status,
                        check_reason,
                    )
                    return _done(action="skip", skipReason="DOMAIN_NOT_FREE")

            phone_digits = "".join(c for c in (order.buyer_phone or "") if c.isdigit())
            if len(phone_digits) > 10:
                phone_digits = phone_digits[-10:]
            if len(phone_digits) < 10:
                raise ValueError("Valid 10-digit phone number is required for domain registration")

            parts = (order.buyer_full_name or "Registrant User").split(None, 1)
            first, last = parts[0], parts[1] if len(parts) > 1 else parts[0]

            if not order.open_provider_handle and reg.is_configured():
                customer = {
                    "name": {"first_name": first, "last_name": last, "full_name": order.buyer_full_name},
                    "email": str(order.buyer_email or "").strip(),
                    "phone": {
                        "country_code": "+91",
                        "area_code": "0",
                        "subscriber_number": phone_digits,
                    },
                    "address": {
                        "street": order.street,
                        "number": "1",
                        "city": order.city,
                        "zipcode": order.zip_code,
                        "state": order.state,
                        "country": order.country,
                    },
                }
                order.open_provider_handle = await reg.create_customer(customer)

            period = reg.resolve_registration_period(order.period_years, ext_no_dot)
            order.period_years = period

            if reg.is_configured() and order.open_provider_handle:
                if hasattr(reg, "lookup_order_id_by_domain"):
                    existing = await reg.lookup_order_id_by_domain(order.fqdn)
                    if existing:
                        reconciled = await self._maybe_reconcile_existing_provider_domain(
                            order,
                            reg,
                            existing,
                            source="LOOKUP_BEFORE_REGISTER",
                        )
                        if reconciled is not None:
                            return _done(**reconciled)
                        order.status = RegistrationOrderStatus.PROVISION_FAILED
                        order.provision_message = (
                            "Domain no longer available at registrar"
                        )
                        await self._orders.save(order)
                        await self._followup.send_lifecycle_emails(order)
                        self._log_isolated_provision(
                            order,
                            action="skip",
                            reason="DOMAIN_NOT_FREE",
                            provider_domain_id=existing,
                            level=logging.WARNING,
                        )
                        return _done(action="skip", skipReason="DOMAIN_NOT_FREE")

                # Keep PAYMENT_COMPLETED until register_domain returns so a mid-call
                # crash is not left as a permanent REGISTRATION_PENDING orphan.
                # Auto-enable WHOIS privacy when the TLD supports it (no separate fee).
                whois_privacy = False
                if hasattr(reg, "is_private_whois_allowed"):
                    try:
                        whois_privacy = bool(await reg.is_private_whois_allowed(ext_no_dot))
                    except Exception as exc:
                        logger.warning(
                            "WHOIS privacy TLD check failed for .%s: %s",
                            ext_no_dot,
                            exc,
                        )
                order.whois_privacy = whois_privacy
                self._log_isolated_provision(
                    order,
                    action="register",
                    reason="NEW_DOMAIN_REGISTRATION",
                )
                logger.info(
                    "openprovider.register_domain.start domain=%s%s handle=%s period=%s order_id=%s",
                    order.domain_name,
                    order.domain_extension,
                    order.open_provider_handle,
                    period,
                    order.id,
                )
                meta["registerDomainCalled"] = True
                meta["action"] = "register"
                reg_result = await reg.register_domain(
                    order.domain_name,
                    ext_no_dot,
                    order.open_provider_handle,
                    period,
                    is_private_whois_enabled=whois_privacy if whois_privacy else None,
                )
                logger.info(
                    "openprovider.register_domain.done domain=%s%s result_keys=%s order_id=%s",
                    order.domain_name,
                    order.domain_extension,
                    list(reg_result.keys()) if isinstance(reg_result, dict) else type(reg_result).__name__,
                    order.id,
                )
                self._apply_registrar_registration(order, reg_result)
                if order.status != RegistrationOrderStatus.ACTIVE:
                    order.status = RegistrationOrderStatus.REGISTRATION_PENDING
                    from app.service.domain.domain_registration_followup import (
                        stamp_registration_pending_since,
                    )

                    stamp_registration_pending_since(order)
                reg_status = str(reg_result.get("actionstatus") or reg_result.get("status") or "").lower()
                if reg_status in ("success", "active", "act"):
                    logger.info(
                        "provision_order.registration_success domain=%s%s order_id=%s "
                        "op_status=%s",
                        order.domain_name,
                        order.domain_extension,
                        order.id,
                        reg_status,
                    )
                    if await self._reconcile_registrar_order(order):
                        await self._orders.save(order)
                        return _done(action="register_domain_success")
                if await self._reconcile_registrar_order(order):
                    await self._orders.save(order)
                    return _done(action="register_domain_submitted_reconciled")
                order.provision_message = (
                    "Domain registration submitted; confirmation pending"
                )
                logger.info(
                    "provision_order.registration_pending domain=%s%s order_id=%s",
                    order.domain_name,
                    order.domain_extension,
                    order.id,
                )
                meta["action"] = "register_domain_submitted_pending"
            elif is_demo_mode() and not reg.is_configured() and not paid:
                logger.warning(
                    "provision_order.early reason=DEMO_MODE_NO_REGISTRAR "
                    "domain=%s%s order_id=%s — register_domain NOT called",
                    order.domain_name,
                    order.domain_extension,
                    order.id,
                )
                self._provision_demo_success(order)
                await self._orders.save(order)
                return _done(action="demo_success", skipReason="DEMO_MODE_NO_REGISTRAR")
            else:
                raise RuntimeError(
                    f"{registrar_source()} is not configured"
                    + (" (refusing demo success for paid order)" if paid else ".")
                )

        except Exception as exc:
            err = str(exc)
            logger.exception(
                "openprovider.provision_order.failed domain=%s%s order_id=%s err=%s",
                order.domain_name,
                order.domain_extension,
                order.id,
                err,
            )
            if self._registrar_order_id(order):
                if await self._reconcile_registrar_order(order):
                    await self._orders.save(order)
                    return _done(
                        action="failed_then_reconciled",
                        skipReason="EXCEPTION_THEN_RECONCILED",
                    )
            # Never fake ACTIVE for a paid order — always PROVISION_FAILED.
            if (
                is_demo_mode()
                and not reg.is_configured()
                and not paid
                and "phone" not in err.lower()
            ):
                self._provision_demo_success(order)
                meta["action"] = "demo_success_after_exception"
                meta["skipReason"] = "DEMO_FALLBACK_AFTER_EXCEPTION"
            else:
                await self._refresh_order_row(order)
                if self._provision_already_succeeded(order):
                    meta["action"] = "exception_ignored_already_in_flight"
                    meta["skipReason"] = "EXCEPTION_BUT_ALREADY_IN_FLIGHT"
                else:
                    order.status = RegistrationOrderStatus.PROVISION_FAILED
                    order.provision_message = active_registrar().friendly_error_from_body(err)
                    meta["action"] = "failed"
                    meta["skipReason"] = "EXCEPTION"

        await self._orders.save(order)
        await self._followup.send_lifecycle_emails(order)
        logger.info(
            "provision_order.finished domain=%s%s order_id=%s status=%s "
            "registerDomainCalled=%s action=%s skipReason=%s",
            order.domain_name,
            order.domain_extension,
            order.id,
            order.status,
            meta.get("registerDomainCalled"),
            meta.get("action"),
            meta.get("skipReason"),
        )
        return _done()

    def _provision_demo_success(self, order: DomainRegistrationOrder) -> None:
        years = max(1, order.period_years)
        now = datetime.now(timezone.utc)
        order.open_provider_domain_id = f"DEMO-{order.id}"
        order.open_provider_status = "ACT"
        order.open_provider_handle = f"DEMO-HANDLE-{order.buyer_id}"
        order.status = RegistrationOrderStatus.ACTIVE
        order.completed_at = now
        order.expires_at = now + timedelta(days=365 * years)
        order.provision_message = "Demo registration complete."

    def _provision_response(self, order: DomainRegistrationOrder) -> dict[str, Any]:
        active = order.status == RegistrationOrderStatus.ACTIVE
        lifecycle = registration_lifecycle_status(order)
        rc_id = order.open_provider_domain_id
        return {
            "success": active,
            "status": order.status.value,
            "lifecycleStatus": lifecycle,
            "orderId": str(order.id),
            "domain": order.fqdn,
            "message": order.provision_message,
            "openProviderDomainId": order.open_provider_domain_id,
            "registrarOrderId": rc_id,
            "openProviderStatus": order.open_provider_status,
            "registrarStatus": order.open_provider_status,
            "demoMode": bool(rc_id and str(rc_id).startswith("DEMO-")),
            "expiresAt": order.expires_at.isoformat() if order.expires_at else None,
            "canRetry": not active and order.status in (
                RegistrationOrderStatus.PROVISION_FAILED,
                RegistrationOrderStatus.PAYMENT_COMPLETED,
                RegistrationOrderStatus.REGISTRATION_PENDING,
            ),
            "icannVerificationStatus": order.icann_verification_status,
            "raaVerificationStatus": (
                order.icann_verification_status
                if order.icann_verification_status != "UNKNOWN"
                else None
            ),
        }

    async def list_my_orders(self, buyer: AppUser) -> list[dict[str, Any]]:
        orders = await self._orders.list_by_buyer(buyer.id)
        
        # Deduplicate domain transfers to prevent showing abandoned checkout attempts
        # alongside actual paid transfers.
        final_orders = []
        transfers_by_domain: dict[str, DomainRegistrationOrder] = {}
        
        for o in orders:
            is_transfer = o.transfer_status and o.transfer_status != "NONE"
            if not is_transfer:
                final_orders.append(o)
                continue
                
            domain = o.fqdn
            existing = transfers_by_domain.get(domain)
            if not existing:
                transfers_by_domain[domain] = o
            else:
                # When deduplicating by domain, prefer a record that has an
                # actual successful payment/transfer over an abandoned checkout,
                # even if the paid record is older. An expired or unpaid record
                # should never mask a completed transfer with a real payment ID
                # and invoice.
                existing_has_payment = bool(existing.razorpay_payment_id)
                current_has_payment = bool(o.razorpay_payment_id)
                existing_completed = existing.transfer_status in ('COMPLETED', 'ACTIVE', 'PROCESSING')
                current_completed = o.transfer_status in ('COMPLETED', 'ACTIVE', 'PROCESSING')
                # Keep the current record if it has a successful transfer/payment
                # and the existing one does not, or if neither has one and current is newer.
                if current_completed and not existing_completed:
                    transfers_by_domain[domain] = o
                elif current_has_payment and not existing_has_payment:
                    transfers_by_domain[domain] = o
        final_orders.extend(transfers_by_domain.values())
        # Re-sort to maintain overall descending order
        final_orders.sort(key=lambda x: x.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        
        return [self._order_summary(o) for o in final_orders]

    def _order_summary(self, order: DomainRegistrationOrder) -> dict[str, Any]:
        from app.service.domain.domain_registration_followup import (
            build_domain_management,
            is_legacy_resellerclub_order,
        )

        is_reseller = is_legacy_resellerclub_order(order) or bool(order.resellerclub_order_id) or "reseller" in str(order.price_source or "").lower()
        registrar_name = "Reseller" if is_reseller else "OpenProvider"
        category_name = "Domain Registration (Reseller)" if is_reseller else "Domain Registration (OpenProvider)"

        mgmt = build_domain_management(order)
        reg_date = order.created_at.isoformat() if order.created_at else None
        exp_date = (
            (order.created_at + timedelta(days=365 * int(order.period_years or 1))).isoformat()
            if order.created_at
            else None
        )

        return {
            "id": str(order.id),
            "domain": order.fqdn,
            "domainName": order.domain_name,
            "domainExtension": order.domain_extension,
            "registrar": registrar_name,
            "category": category_name,
            "razorpayPaymentId": order.razorpay_payment_id,
            "razorpayOrderId": order.razorpay_order_id,
            "buyerName": order.buyer_full_name,
            "buyerFullName": order.buyer_full_name,
            "buyerEmail": order.buyer_email,
            "buyerPhone": order.buyer_phone,
            "buyerGstin": getattr(order, "buyer_gstin", None),
            "taxInvoiceNumber": getattr(order, "tax_invoice_number", None),
            "invoiceNumber": getattr(order, "tax_invoice_number", None),
            "street": order.street,
            "city": order.city,
            "state": order.state,
            "zipCode": order.zip_code,
            "country": order.country,
            "amountPaid": float(order.price_inr or 0.0),
            "registrationDate": reg_date,
            "expiryDate": exp_date,
            **_order_gst_fields(order),
            "periodYears": int(order.period_years or 1),
            "status": order.status.value,
            "lifecycleStatus": registration_lifecycle_status(order),
            "isTransfer": order.transfer_status is not None and order.transfer_status != "NONE",
            "transferStatus": order.transfer_status,
            "canRetryPayment": self._can_retry_transfer_payment(order),
            "createdAt": reg_date,
            "message": order.provision_message,
            "canManageDomain": mgmt["available"],
            "customerPanelUrl": mgmt.get("customerPanelUrl"),
            "nameservers": mgmt.get("nameservers"),
            "supportsDnssec": mgmt.get("supportsDnssec", False),
            "isPremium": bool(getattr(order, "is_premium", False)),
            "registryTier": str(getattr(order, "registry_tier", None) or "standard"),
            "providerUnitPriceInr": getattr(order, "provider_unit_price_inr", None),
            "customerUnitPriceInr": order.quoted_unit_price_inr,
            "priceSource": order.price_source,
        }

    async def get_order(self, order_id: uuid.UUID, *, buyer: AppUser) -> DomainRegistrationOrder:
        order = await self._orders.get_by_id(order_id)
        if order is None or order.buyer_id != buyer.id:
            raise AppException("Order not found.", status_code=404)
        return order

    @staticmethod
    def _assert_manageable(order: DomainRegistrationOrder) -> None:
        """Raise 400 if the order is in a state that blocks DNS management.

        Refunded, cancelled, expired, or failed orders must not allow
        nameserver / DNS record mutations.
        """
        status = getattr(order.status, 'value', str(order.status) or '').upper()
        if status in ('REFUNDED', 'EXPIRED', 'FAILED', 'PAYMENT_FAILED'):
            raise AppException(
                f"Domain management is unavailable because this order has status '{status}'.",
                status_code=400,
            )

    async def get_order_detail(
        self,
        order_id: uuid.UUID,
        *,
        buyer: AppUser,
        sync: bool = True,
    ) -> dict[str, Any]:
        return await self._followup.get_enriched_order(
            order_id, buyer=buyer, sync=sync,
        )

    async def sync_order(self, order_id: uuid.UUID, *, buyer: AppUser) -> dict[str, Any]:
        order = await self.get_order(order_id, buyer=buyer)
        await self._followup.sync_from_registrar(order)
        await self._followup.send_lifecycle_emails(order)
        await self._session.commit()
        return await self.get_order_detail(order_id, buyer=buyer, sync=False)

    async def resend_verification(
        self,
        order_id: uuid.UUID,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        return await self._followup.resend_verification(order_id, buyer=buyer)

    async def retry_provision(self, order_id: uuid.UUID, *, buyer: AppUser) -> dict[str, Any]:
        order = await self.get_order(order_id, buyer=buyer)
        await self.provision_order(order)
        await self._session.commit()
        order = await self._orders.get_by_id(order.id)
        return self._provision_response(order)

    async def complete_payment_from_webhook(
        self,
        razorpay_order_id: str,
        payment_id: str,
    ) -> dict:
        """Fulfill domain registration after Razorpay payment.captured.

        Returns an explicit outcome so the webhook response can distinguish
        payment accepted vs registration attempted vs registration successful.
        """
        orders = list(await self._orders.list_by_razorpay_order_id(razorpay_order_id))
        if not orders:
            logger.warning(
                "razorpay.webhook.no_registration_orders order_id=%s payment_id=%s "
                "REGISTRATION_NOT_ATTEMPTED",
                razorpay_order_id,
                payment_id,
            )
            return {
                "ordersFound": 0,
                "registrationAttempted": False,
                "registrationSuccessful": False,
                "needsAttention": True,
                "skipReason": "NO_PENDING_ORDERS",
                "results": [],
            }

        logger.info(
            "razorpay.webhook.orders_found count=%s order_id=%s payment_id=%s",
            len(orders),
            razorpay_order_id,
            payment_id,
        )

        from app.service.platform.track_record_service import TrackRecordService

        track_service = TrackRecordService(self._session)

        # Safely determine transfer flow from Razorpay order notes
        from app.integrations.razorpay.client import fetch_order
        rzp_order = fetch_order(razorpay_order_id)
        is_transfer = str(rzp_order.get("notes", {}).get("type")) == "domain_transfer"

        results: list[dict] = []
        registration_attempted = False
        registration_successful = False
        needs_attention = False

        for raw_order in orders:
            if is_transfer:
                order = await self._orders.get_by_id_for_update(raw_order.id)
                if not order:
                    logger.error("razorpay.webhook.skip reason=LOCKED_ORDER_NOT_FOUND id=%s", raw_order.id)
                    results.append({"action": "skipped", "skipReason": "LOCKED_ORDER_NOT_FOUND"})
                    needs_attention = True
                    continue
            else:
                order = raw_order

            domain = f"{order.domain_name}{order.domain_extension}"
            row: dict = {
                "orderId": str(order.id),
                "domain": domain,
                "statusBefore": order.status.value if hasattr(order.status, "value") else str(order.status),
                "registerDomainCalled": False,
                "skipReason": None,
                "action": None,
            }

            if order.status == RegistrationOrderStatus.ACTIVE:
                row["action"] = "skipped_intentional"
                row["skipReason"] = "ALREADY_ACTIVE"
                logger.info(
                    "razorpay.webhook.skip_register_domain reason=ALREADY_ACTIVE "
                    "domain=%s order_id=%s",
                    domain,
                    order.id,
                )
                await track_service.record_from_registration_order(
                    order,
                    cart_batch_id=razorpay_order_id,
                )
                registration_successful = True
                results.append(row)
                continue

            if order.status == RegistrationOrderStatus.REFUNDED:
                row["action"] = "skipped_intentional"
                row["skipReason"] = "REFUNDED"
                logger.info(
                    "razorpay.webhook.skip_register_domain reason=REFUNDED "
                    "domain=%s order_id=%s",
                    domain,
                    order.id,
                )
                await track_service.record_from_registration_order(
                    order,
                    cart_batch_id=razorpay_order_id,
                )
                results.append(row)
                continue

            existing_pay = str(order.razorpay_payment_id or "").strip()
            if existing_pay and existing_pay != str(payment_id or "").strip():
                row["action"] = "skip"
                row["skipReason"] = "PAYMENT_ID_MISMATCH"
                self._log_isolated_provision(
                    order,
                    action="skip",
                    reason="PAYMENT_ID_MISMATCH",
                    level=logging.WARNING,
                )
                needs_attention = True
                results.append(row)
                continue
            if not existing_pay:
                order.razorpay_payment_id = payment_id

            listed_rzp = str(order.razorpay_order_id or "").strip()
            if listed_rzp and listed_rzp != str(razorpay_order_id or "").strip():
                row["action"] = "skip"
                row["skipReason"] = "RAZORPAY_ORDER_MISMATCH"
                self._log_isolated_provision(
                    order,
                    action="skip",
                    reason="RAZORPAY_ORDER_MISMATCH",
                    level=logging.WARNING,
                )
                needs_attention = True
                results.append(row)
                continue

            transfer_pending = (
                order.transfer_status is not None
                and str(order.transfer_status) not in ("", "NONE")
                and (
                    is_transfer
                    or str(order.transfer_status).upper() == "PENDING"
                )
            )
            has_provider_id = bool(self._registrar_order_id(order))
            if transfer_pending or (
                order.status == RegistrationOrderStatus.REGISTRATION_PENDING
                and has_provider_id
            ):
                row["action"] = "reconcile_only"
                row["skipReason"] = "ALREADY_REGISTRATION_PENDING_RECONCILE"
                self._log_isolated_provision(
                    order,
                    action="reconcile",
                    reason="ALREADY_REGISTRATION_PENDING_RECONCILE",
                )
                logger.info(
                    "razorpay.webhook.skip_register_domain reason=ALREADY_REGISTRATION_PENDING "
                    "domain=%s order_id=%s — reconciling existing registrar order only",
                    domain,
                    order.id,
                )
                await self._reconcile_registrar_order(order)
                await self._orders.save(order)
                await self._followup.send_lifecycle_emails(order)
                await track_service.record_from_registration_order(
                    order,
                    cart_batch_id=razorpay_order_id,
                )
                if order.status == RegistrationOrderStatus.ACTIVE:
                    registration_successful = True
                results.append(row)
                continue

            prev_status = order.status
            if order.status in (
                RegistrationOrderStatus.CREATED,
                RegistrationOrderStatus.EXPIRED,
                RegistrationOrderStatus.PAYMENT_FAILED,
                RegistrationOrderStatus.FAILED,
                RegistrationOrderStatus.PROVISION_FAILED,
            ):
                order.status = RegistrationOrderStatus.PAYMENT_COMPLETED
                if prev_status != RegistrationOrderStatus.CREATED:
                    logger.info(
                        "razorpay.webhook.status_recovered from=%s to=PAYMENT_COMPLETED "
                        "domain=%s order_id=%s payment_id=%s — "
                        "user retried payment after earlier failure",
                        prev_status,
                        domain,
                        order.id,
                        payment_id,
                    )
            await self._orders.save(order)

            if order.status not in (
                RegistrationOrderStatus.PAYMENT_COMPLETED,
                RegistrationOrderStatus.REGISTRATION_PENDING,
            ):
                row["action"] = "skip"
                row["skipReason"] = f"UNEXPECTED_STATUS_{order.status}"
                logger.warning(
                    "razorpay.webhook.skip_provision reason=%s domain=%s order_id=%s status=%s",
                    row["skipReason"],
                    domain,
                    order.id,
                    order.status,
                )
                needs_attention = True
                results.append(row)
                continue

            self._log_isolated_provision(
                order,
                action="register" if not has_provider_id else "reconcile",
                reason="WEBHOOK_PROVISION",
            )
            logger.info(
                "razorpay.webhook.provision_order.started order_db_id=%s "
                "rzp_order=%s payment_id=%s domain=%s",
                order.id,
                razorpay_order_id,
                payment_id,
                domain,
            )
            
            if is_transfer:
                logger.info("razorpay.webhook.provision_transfer routed domain=%s", domain)
                from app.entity.user.app_user import AppUser
                buyer = await self._session.get(AppUser, order.buyer_id)
                if not buyer:
                    row["action"] = "skipped"
                    row["skipReason"] = "BUYER_NOT_FOUND"
                    needs_attention = True
                    results.append(row)
                    continue

                try:
                    await self._provision_transfer(order, buyer=buyer)
                    row["transferDomainCalled"] = True
                    row["action"] = "provision_transfer"
                    row["skipReason"] = None
                    registration_attempted = True
                except Exception as e:
                    logger.exception("Transfer provision failed in webhook domain=%s", domain)
                    row["action"] = "failed"
                    row["skipReason"] = f"TRANSFER_FAILED: {str(e)}"
                    needs_attention = True
            else:
                provision_meta = await self.provision_order(order, return_meta=True)
                row["registerDomainCalled"] = bool(
                    (provision_meta or {}).get("registerDomainCalled")
                )
                row["skipReason"] = (provision_meta or {}).get("skipReason")
                row["action"] = (provision_meta or {}).get("action") or "provisioned"
                if row["registerDomainCalled"] or row["action"] in (
                    "adopt_existing",
                    "reconcile_existing_registrar_id",
                    "reconcile",
                    "register",
                ):
                    registration_attempted = True
                if row["action"] == "attention":
                    needs_attention = True

            refreshed = await self._orders.get_by_id(order.id)
            if refreshed is not None:
                st = refreshed.status.value if hasattr(refreshed.status, "value") else str(refreshed.status)
                row["statusAfter"] = st
                if refreshed.status == RegistrationOrderStatus.ACTIVE:
                    registration_successful = True
                elif refreshed.status == RegistrationOrderStatus.PROVISION_FAILED:
                    needs_attention = True
                elif refreshed.status == RegistrationOrderStatus.REGISTRATION_PENDING:
                    registration_attempted = True
                await track_service.record_from_registration_order(
                    refreshed,
                    cart_batch_id=razorpay_order_id,
                )
                await self._followup.send_lifecycle_emails(refreshed)
            results.append(row)

        # Clear matching cart lines so purchased domains don't linger if the
        # browser never completed verify (webhook-only fulfill). Cart rows only.
        try:
            from app.service.cart.cart_checkout_service import CartCheckoutService

            ok_domains: list[str] = []
            for o in orders:
                d = f"{o.domain_name}{o.domain_extension}".lower().strip()
                if d and d not in ok_domains:
                    ok_domains.append(d)
            for row in results:
                domain = str(row.get("domain") or "").lower().strip()
                if domain and domain not in ok_domains:
                    ok_domains.append(domain)

            buyer_ids = {o.buyer_id for o in orders if getattr(o, "buyer_id", None)}
            cart_svc = CartCheckoutService(self._session)
            for buyer_id in buyer_ids:
                await cart_svc.remove_fulfilled_cart_items_for_payment(
                    buyer_id,
                    razorpay_order_id=razorpay_order_id,
                    domains=ok_domains,
                )
        except Exception:
            logger.exception(
                "razorpay.webhook.cart_cleanup_failed order_id=%s payment_id=%s",
                razorpay_order_id,
                payment_id,
            )

        await self._session.commit()
        return {
            "ordersFound": len(orders),
            "registrationAttempted": registration_attempted,
            "registrationSuccessful": registration_successful,
            "needsAttention": needs_attention or (
                not registration_successful and not registration_attempted
            ),
            "skipReason": None,
            "results": results,
        }

    async def update_nameservers(
        self,
        order_id: uuid.UUID,
        nameservers: list[str],
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        order = await self.get_order(order_id, buyer=buyer)
        self._assert_manageable(order)
        if is_legacy_resellerclub_order(order):
            raise AppException(
                sanitize_customer_registrar_message(
                    "This domain is still at the previous registrar. Transfer it to "
                    "OpenProvider before managing nameservers in HubRegistrar. "
                    "See docs/LEGACY_RESELLERCLUB_TO_OPENPROVIDER.md."
                ),
                status_code=400,
            )
        reg = active_registrar()
        if reg.is_configured():
            from app.integrations.openprovider.client import (
                lookup_order_id_by_domain,
                update_nameservers as op_update,
            )
            domain_id = str(order.open_provider_domain_id or "").strip()
            rc_id = str(order.resellerclub_order_id or "").strip()
            # When RC/OP ids were conflated, resolve the live OpenProvider id by FQDN
            # for the API call only (do not rewrite the database row).
            if not domain_id or domain_id.startswith("DEMO-") or (rc_id and domain_id == rc_id):
                looked_up = await lookup_order_id_by_domain(order.fqdn)
                if looked_up:
                    domain_id = looked_up
            if domain_id and not domain_id.startswith("DEMO-"):
                await op_update(domain_id, nameservers)

        # Store the requested hosts immediately (canonical JSON), then let the
        # registrar sync below overwrite with the registrar-confirmed state.
        set_order_nameservers(order, nameservers, "custom")
        await self._orders.save(order)
        await self._followup.sync_from_registrar(order)
        await self._session.commit()
        return await self.get_order_detail(order_id, buyer=buyer, sync=False)

    async def renew_domain_direct(
        self,
        order_id: uuid.UUID,
        period_years: int = 1,
        *,
        buyer: AppUser,
        _payment_verified: bool = False,
    ) -> dict[str, Any]:
        if not _payment_verified:
            raise AppException(
                "Renewal requires payment. Use the renew/payment checkout flow.",
                status_code=402,
            )
        return await self._provision_renewal(order_id, period_years, buyer=buyer)

    async def _provision_renewal(
        self,
        order_id: uuid.UUID,
        period_years: int = 1,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        order = await self.get_order(order_id, buyer=buyer)
        self._assert_renewal_window(order)

        reg = active_registrar()
        if reg.is_configured():
            from app.integrations.openprovider.client import renew_domain as op_renew
            if order.open_provider_domain_id and not str(order.open_provider_domain_id).startswith("DEMO-"):
                await op_renew(order.open_provider_domain_id, period_years)

        order.renewal_count += 1
        order.pending_renewal_razorpay_order_id = None
        order.pending_renewal_years = None
        order.pending_renewal_amount_inr = None
        await self._orders.save(order)
        await self._followup.sync_from_registrar(order)
        await self._session.commit()
        return await self.get_order_detail(order_id, buyer=buyer, sync=False)

    @staticmethod
    def _assert_renewal_window(order: DomainRegistrationOrder) -> None:
        if not order.expires_at:
            return
        now = datetime.now(timezone.utc)
        expires_at = order.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        days_left = (expires_at - now).days
        if days_left > 7:
            raise AppException(
                f"Domain can only be renewed within 7 days of expiration. Currently {days_left} days left.",
                status_code=400,
            )

    async def _resolve_renewal_unit_price_inr(
        self,
        order: DomainRegistrationOrder,
    ) -> tuple[float, str]:
        from app.service.domain import domain_commission_config as commission

        ext = order.domain_extension.lstrip(".")
        fallback = float(settings.DOMAIN_STOREFRONT_RENEWAL_FALLBACK_UNIT_INR or 799.0)
        base_price = fallback
        source = "fallback"

        reg = active_registrar()
        if reg.is_configured():
            try:
                from app.integrations.openprovider.client import (
                    get_domain_price,
                    extract_getprice_renewal_details,
                )

                quote = await get_domain_price(
                    order.domain_name or "example",
                    ext,
                    operation="renew",
                    period=1,
                )
                ren_unit, _ = extract_getprice_renewal_details(quote)
                if ren_unit and float(ren_unit) > 0:
                    base_price = max(1.0, round(float(ren_unit), 2))
                    source = "registrar"
            except Exception as exc:
                logger.warning(
                    "renewal price lookup failed for %s: %s",
                    order.fqdn,
                    exc,
                )

        rate = commission.get_rate("renewal", order.domain_extension)
        return commission.apply_markup(base_price, rate), source

    async def _resolve_transfer_unit_price_inr(self, domain: str) -> tuple[float, str]:
        from app.service.domain import domain_commission_config as commission

        domain = domain.strip().lower()
        if "." not in domain:
            raise AppException("Invalid domain format.", status_code=400)
        name, ext = domain.split(".", 1)
        ext_dot = f".{ext}"
        fallback = float(settings.DOMAIN_STOREFRONT_RENEWAL_FALLBACK_UNIT_INR or 799.0)
        base_price = fallback
        source = "fallback"

        reg = active_registrar()
        if reg.is_configured():
            try:
                from app.integrations.openprovider.client import (
                    get_domain_price,
                    extract_reseller_price_details,
                )

                quote = await get_domain_price(name, ext, operation="transfer", period=1)
                unit, _ = extract_reseller_price_details(quote)
                if unit and float(unit) > 0:
                    base_price = max(1.0, round(float(unit), 2))
                    source = "registrar"
            except Exception as exc:
                logger.warning("transfer price lookup failed for %s: %s", domain, exc)

        rate = commission.get_rate("transfer", ext_dot)
        return commission.apply_markup(base_price, rate), source

    async def get_renewal_quote(
        self,
        order_id: uuid.UUID,
        period_years: int = 1,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        order = await self.get_order(order_id, buyer=buyer)
        self._assert_renewal_window(order)
        unit_inr, source = await self._resolve_renewal_unit_price_inr(order)
        pricing = domain_price_breakdown(unit_inr, years=period_years)
        return {
            "registrationOrderId": str(order.id),
            "domain": order.fqdn,
            "periodYears": period_years,
            "unitPriceInr": unit_inr,
            "priceSource": source,
            **pricing,
        }

    async def create_renewal_payment_order(
        self,
        order_id: uuid.UUID,
        period_years: int = 1,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        if not rzp.is_configured():
            raise AppException("Payment gateway is not configured.", status_code=503)

        order = await self.get_order(order_id, buyer=buyer)
        self._assert_renewal_window(order)

        unit_inr, price_source = await self._resolve_renewal_unit_price_inr(order)
        pricing = domain_price_breakdown(unit_inr, years=period_years)

        rzp_order = rzp.create_order(
            amount_inr=pricing["totalInr"],
            receipt=f"dren_{order.domain_name}_{int(datetime.now(timezone.utc).timestamp())}",
            notes={
                "type": "domain_renewal",
                "domain": order.fqdn,
                "buyerId": str(buyer.id),
                "orderId": str(order.id),
                "periodYears": str(period_years),
            },
        )

        order.pending_renewal_razorpay_order_id = rzp_order["id"]
        order.pending_renewal_years = period_years
        order.pending_renewal_amount_inr = pricing["totalInr"]
        await self._orders.save(order)
        await self._session.commit()

        return {
            "orderId": rzp_order["id"],
            "amount": pricing["totalInr"],
            "subtotalInr": pricing["subtotalInr"],
            "gstInr": pricing["gstInr"],
            "totalInr": pricing["totalInr"],
            "unitPriceInr": unit_inr,
            "priceSource": price_source,
            "currency": "INR",
            "keyId": rzp.get_key_id(),
            "registrationOrderId": str(order.id),
            "domain": order.fqdn,
            "periodYears": period_years,
        }

    async def verify_renewal_payment(
        self,
        order_id: uuid.UUID,
        payload: dict[str, str],
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        order = await self.get_order(order_id, buyer=buyer)
        razorpay_order_id = str(payload.get("razorpayOrderId") or "").strip()
        razorpay_payment_id = str(payload.get("razorpayPaymentId") or "").strip()
        razorpay_signature = str(payload.get("razorpaySignature") or "").strip()
        if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
            raise AppException("Payment verification payload is incomplete.", status_code=400)

        if order.pending_renewal_razorpay_order_id != razorpay_order_id:
            raise AppException("Renewal payment order mismatch or expired.", status_code=400)

        if order.last_renewal_payment_id == razorpay_payment_id:
            period_years = int(payload.get("period") or order.pending_renewal_years or 1)
            return await self.get_order_detail(order_id, buyer=buyer, sync=True)

        if not rzp.verify_payment_signature(
            razorpay_order_id,
            razorpay_payment_id,
            razorpay_signature,
        ):
            raise AppException("Payment verification failed.", status_code=400)

        period_years = int(payload.get("period") or order.pending_renewal_years or 1)
        order.last_renewal_payment_id = razorpay_payment_id
        await self._orders.save(order)
        await self._session.flush()

        result = await self._provision_renewal(
            order_id,
            period_years,
            buyer=buyer,
        )
        return result

    async def get_transfer_quote(self, domain: str) -> dict[str, Any]:
        unit_inr, source = await self._resolve_transfer_unit_price_inr(domain)
        pricing = domain_price_breakdown(unit_inr, years=1)
        return {
            "domain": domain.strip().lower(),
            "unitPriceInr": unit_inr,
            "priceSource": source,
            **pricing,
        }

    async def create_transfer_payment_order(
        self,
        payload: dict[str, Any],
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        if not rzp.is_configured():
            raise AppException("Payment gateway is not configured.", status_code=503)

        domain = str(payload.get("domain", "")).strip().lower()
        auth_code = str(payload.get("authCode", "")).strip()
        if not domain or not auth_code:
            raise AppException("Domain and authorization code are required.", status_code=400)
        if "." not in domain:
            raise AppException("Invalid domain format.", status_code=400)

        name, ext = domain.split(".", 1)
        unit_inr, price_source = await self._resolve_transfer_unit_price_inr(domain)
        pricing = domain_price_breakdown(unit_inr, years=1)

        # ── Idempotency guard ──────────────────────────────────────────────────
        # A transfer order for this buyer+domain may already exist from an earlier
        # click/attempt. Decide per state whether to (a) reopen the same unpaid
        # Razorpay checkout, (b) block because a payment is in flight, or
        # (c) create a fresh attempt (failed/refunded/expired previous attempt).
        existing = await self._orders.get_active_transfer_by_buyer_and_domain(
            buyer.id, name, f".{ext}"
        )
        if existing is not None:
            st = existing.status
            paid = bool(existing.razorpay_payment_id)
            ts = existing.transfer_status or ""

            # Already transferred — never allow another attempt.
            if st == RegistrationOrderStatus.ACTIVE:
                raise AppException(
                    f"{domain} has already been transferred successfully.",
                    status_code=409,
                )

            # Transfer already submitted/processing after payment — reconciliation
            # is in progress; do not create a duplicate payment.
            if (
                st == RegistrationOrderStatus.REGISTRATION_PENDING
                or ts == "PENDING"
            ):
                if paid:
                    raise AppException(
                        "Your transfer payment was received and the transfer is "
                        "being processed. Track it in My Orders.",
                        status_code=409,
                    )

            # Payment was captured but the transfer failed and has not been
            # refunded yet — never silently create a second charge. The existing
            # admin refund flow (and the Razorpay refund webhook) will move the
            # order to REFUNDED; only then may the customer start a new attempt.
            if paid and st in (
                RegistrationOrderStatus.PROVISION_FAILED,
                RegistrationOrderStatus.FAILED,
            ):
                raise AppException(
                    "Your previous transfer attempt failed after payment. The "
                    "payment will be refunded; once the refund is complete you "
                    "can start a new transfer attempt with a corrected "
                    "authorization code.",
                    status_code=409,
                )

            # Unpaid abandoned checkout: reopen the SAME attempt with the LATEST
            # code the customer entered (never reuse a stale code) and ALWAYS mint
            # a fresh Razorpay order on the same row. A stale Razorpay order id
            # from an abandoned checkout makes the checkout refuse to open, so it
            # is never presented again. Repeated cancelled checkouts also never
            # accumulate duplicate database orders.
            if not paid and st == RegistrationOrderStatus.CREATED:
                existing.transfer_auth_code = auth_code
                recent = self._recent_retry_mint(existing.id)
                if recent and existing.razorpay_order_id == recent:
                    # Same double-click burst — the order minted by the previous
                    # click is still valid and unpaid.
                    await self._orders.save(existing)
                    await self._session.commit()
                    logger.info(
                        "domain_transfer.payment_order.reuse_dup_click buyer=%s domain=%s order_id=%s",
                        buyer.id, domain, existing.id,
                    )
                    return self._transfer_payment_payload(existing, recent, domain)
                rzp_order = rzp.create_order(
                    amount_inr=float(existing.price_inr or pricing["totalInr"]),
                    receipt=f"dtrf_{name}_{int(datetime.now(timezone.utc).timestamp())}",
                    notes={
                        "type": "domain_transfer",
                        "domain": domain,
                        "buyerId": str(buyer.id),
                    },
                )
                existing.razorpay_order_id = rzp_order["id"]
                _RETRY_MINT_GUARD[existing.id] = (
                    datetime.now(timezone.utc).timestamp(),
                    rzp_order["id"],
                )
                await self._orders.save(existing)
                await self._session.commit()
                logger.info(
                    "domain_transfer.payment_order.fresh_rzp buyer=%s domain=%s order_id=%s",
                    buyer.id, domain, existing.id,
                )
                return self._transfer_payment_payload(existing, rzp_order["id"], domain)

            # Everything else (REFUNDED, EXPIRED, PAYMENT_FAILED, FAILED without
            # a captured payment, PROVISION_FAILED without a captured payment)
            # is a clean-slate retry: create a fresh order with the new code.
            logger.info(
                "domain_transfer.payment_order.new_attempt buyer=%s domain=%s prev_status=%s prev_transfer_status=%s",
                buyer.id,
                domain,
                st.value if hasattr(st, "value") else st,
                ts,
            )
        # ── /Idempotency guard ─────────────────────────────────────────────────

        order = DomainRegistrationOrder(
            domain_name=name,
            domain_extension=f".{ext}",
            buyer_id=buyer.id,
            buyer_full_name=buyer.full_name,
            buyer_email=buyer.email,
            buyer_phone=buyer.phone_number or "9999999999",
            street="Reseller Street",
            city="City",
            state="State",
            zip_code="560001",
            country="IN",
            period_years=1,
            subtotal_inr=pricing["subtotalInr"],
            gst_inr=pricing["gstInr"],
            price_inr=pricing["totalInr"],
            quoted_unit_price_inr=unit_inr,
            price_source=price_source,
            status=RegistrationOrderStatus.CREATED,
            transfer_auth_code=auth_code,
            transfer_status="PAYMENT_PENDING",
        )

        rzp_order = rzp.create_order(
            amount_inr=pricing["totalInr"],
            receipt=f"dtrf_{name}_{int(datetime.now(timezone.utc).timestamp())}",
            notes={
                "type": "domain_transfer",
                "domain": domain,
                "buyerId": str(buyer.id),
            },
        )
        order.razorpay_order_id = rzp_order["id"]
        order = await self._orders.create(order)
        await self._session.commit()

        return self._transfer_payment_payload(order, rzp_order["id"], domain)

    @staticmethod
    def _recent_retry_mint(
        order_id: uuid.UUID,
    ) -> Optional[str]:
        """Return a just-minted Razorpay order id for a rapid duplicate click.

        Razorpay orders are minted fresh on every retry (a stale order id from
        an abandoned checkout makes the Razorpay checkout refuse to open). To
        still absorb a double-click burst, a very recent mint (same attempt,
        seconds ago) is returned instead of minting a second order.
        """
        entry = _RETRY_MINT_GUARD.get(order_id)
        if not entry:
            return None
        minted_at, rzp_order_id = entry
        if datetime.now(timezone.utc).timestamp() - minted_at > _RETRY_MINT_TTL_SECONDS:
            _RETRY_MINT_GUARD.pop(order_id, None)
            return None
        return rzp_order_id

    @staticmethod
    def _can_retry_transfer_payment(order: DomainRegistrationOrder) -> bool:
        """True only for an unpaid/cancelled transfer attempt.

        A captured Razorpay payment, an in-flight transfer, a successful
        transfer, or a failed/refunded attempt is never retryable as a payment.
        """
        if order.transfer_status in (None, "NONE"):
            return False
        if order.razorpay_payment_id:
            return False
        return order.status in (
            RegistrationOrderStatus.CREATED,
            RegistrationOrderStatus.EXPIRED,
            RegistrationOrderStatus.PAYMENT_FAILED,
        )

    @staticmethod
    def _transfer_payment_payload(
        order: DomainRegistrationOrder,
        rzp_order_id: str,
        domain: str,
    ) -> dict[str, Any]:
        """Razorpay checkout payload shared by create/reuse/retry paths."""
        return {
            "orderId": rzp_order_id,
            "amount": float(order.price_inr or 0),
            "subtotalInr": float(order.subtotal_inr or order.price_inr or 0),
            "gstInr": float(order.gst_inr or 0),
            "totalInr": float(order.price_inr or 0),
            "unitPriceInr": float(order.quoted_unit_price_inr or order.price_inr or 0),
            "priceSource": order.price_source,
            "currency": "INR",
            "keyId": rzp.get_key_id(),
            "registrationOrderId": str(order.id),
            "domain": domain,
        }

    async def retry_transfer_payment(
        self,
        order_id: uuid.UUID,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        """Reopen Razorpay checkout for an unpaid/cancelled transfer attempt.

        Only cancelled/unpaid attempts (no captured Razorpay payment) may be
        retried. A completed payment is never reused, no new database order row
        is created, and OpenProvider is never contacted here — the transfer is
        only submitted after the retried payment is verified.
        """
        if not rzp.is_configured():
            raise AppException("Payment gateway is not configured.", status_code=503)

        order = await self._orders.get_by_id_for_update(order_id)
        if order is None or order.buyer_id != buyer.id:
            raise AppException("Transfer order not found.", status_code=404)
        is_transfer = order.transfer_status is not None and order.transfer_status != "NONE"
        if not is_transfer:
            raise AppException("This order is not a domain transfer.", status_code=400)

        st = order.status
        ts = order.transfer_status or ""
        paid = bool(order.razorpay_payment_id)

        if st == RegistrationOrderStatus.ACTIVE:
            raise AppException(
                f"{order.fqdn} has already been transferred successfully.",
                status_code=409,
            )
        if (
            st == RegistrationOrderStatus.REGISTRATION_PENDING
            or ts == "PENDING"
            or st == RegistrationOrderStatus.PAYMENT_COMPLETED
        ):
            raise AppException(
                "A payment for this transfer was received and the transfer is "
                "being processed. Do not pay again.",
                status_code=409,
            )
        if st in (
            RegistrationOrderStatus.PROVISION_FAILED,
            RegistrationOrderStatus.FAILED,
            RegistrationOrderStatus.REFUNDED,
        ):
            raise AppException(
                "This transfer attempt failed or was refunded. Start a new "
                "transfer request with a corrected authorization code from the "
                "storefront.",
                status_code=409,
            )
        if paid:
            raise AppException(
                "This payment was already completed successfully and cannot be "
                "retried.",
                status_code=409,
            )
        if not order.transfer_auth_code:
            raise AppException(
                "This attempt has no saved authorization code. Re-enter your "
                "domain and EPP/Auth Code on the Transfer to HubRegistrar form to retry.",
                status_code=400,
            )

        domain = order.fqdn
        recent = self._recent_retry_mint(order.id)
        if recent and order.razorpay_order_id == recent:
            # Same double-click burst — the order minted by the previous click is
            # still valid and unpaid; never mint a duplicate.
            logger.info(
                "domain_transfer.payment_retry.dup_click buyer=%s domain=%s order_id=%s",
                buyer.id, domain, order.id,
            )
            return self._transfer_payment_payload(order, recent, domain)

        # ALWAYS mint a completely NEW Razorpay order on the same row. The old
        # order id from the abandoned checkout is stale and makes the Razorpay
        # checkout refuse to open — it is never reused, so the old cancelled
        # order can never be charged again.
        rzp_order = rzp.create_order(
            amount_inr=float(order.price_inr or 0),
            receipt=f"dtrf_{order.domain_name}_{int(datetime.now(timezone.utc).timestamp())}",
            notes={
                "type": "domain_transfer",
                "domain": domain,
                "buyerId": str(buyer.id),
            },
        )
        order.razorpay_order_id = rzp_order["id"]
        order.status = RegistrationOrderStatus.CREATED
        order.transfer_status = "PAYMENT_PENDING"
        _RETRY_MINT_GUARD[order.id] = (
            datetime.now(timezone.utc).timestamp(),
            rzp_order["id"],
        )
        await self._orders.save(order)
        await self._session.commit()
        logger.info(
            "domain_transfer.payment_retry.new_order buyer=%s domain=%s order_id=%s rzp_order=%s",
            buyer.id, domain, order.id, rzp_order["id"],
        )
        return self._transfer_payment_payload(order, rzp_order["id"], domain)

    async def verify_transfer_payment(
        self,
        payload: dict[str, str],
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        razorpay_order_id = str(payload.get("razorpayOrderId") or "").strip()
        razorpay_payment_id = str(payload.get("razorpayPaymentId") or "").strip()
        razorpay_signature = str(payload.get("razorpaySignature") or "").strip()
        registration_order_id = payload.get("registrationOrderId")
        if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
            raise AppException("Payment verification payload is incomplete.", status_code=400)

        order = await self._orders.get_by_razorpay_order_id(razorpay_order_id)
        if order is None and registration_order_id:
            order = await self.get_order(uuid.UUID(str(registration_order_id)), buyer=buyer)
        if order is None or order.buyer_id != buyer.id:
            raise AppException("Transfer order not found.", status_code=404)
        if order.razorpay_order_id != razorpay_order_id:
            raise AppException("Transfer payment order mismatch.", status_code=400)

        # Serialize concurrent verifications/webhooks
        order = await self._orders.get_by_id_for_update(order.id)
        if order is None:
            raise AppException("Transfer order not found.", status_code=404)

        # Same-payment replay guard: if this payment was already processed, never
        # re-attempt the provider submission (OpenProvider has no idempotency).
        # Return the current state only for in-flight transfers; any terminal
        # state (failed, refunded, already active) is surfaced as an error so
        # the frontend never shows a false success on a replay.
        if order.razorpay_payment_id == razorpay_payment_id:
            if (
                order.transfer_status == "PENDING"
                or order.status == RegistrationOrderStatus.REGISTRATION_PENDING
                or order.status == RegistrationOrderStatus.PAYMENT_COMPLETED
            ):
                return {
                    "id": str(order.id),
                    "domain": order.fqdn,
                    "status": order.status.value,
                    "transferStatus": order.transfer_status,
                }
            raise AppException(
                order.provision_message
                or "Domain transfer was not completed and your payment has been refunded.",
                status_code=502,
            )

        if not rzp.verify_payment_signature(
            razorpay_order_id,
            razorpay_payment_id,
            razorpay_signature,
        ):
            order.status = RegistrationOrderStatus.FAILED
            await self._orders.save(order)
            await self._session.commit()
            raise AppException("Payment verification failed.", status_code=400)

        order.razorpay_payment_id = razorpay_payment_id
        order.status = RegistrationOrderStatus.PAYMENT_COMPLETED
        await self._orders.save(order)
        # Persist the captured payment BEFORE calling the provider: a successful
        # payment must never disappear because OpenProvider rejects or is
        # unreachable. Provider outcome is recorded separately below.
        await self._session.commit()

        return await self._provision_transfer(order, buyer=buyer)

    async def _provision_transfer(
        self,
        order: DomainRegistrationOrder,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        auth_code = (order.transfer_auth_code or "").strip()
        if not auth_code:
            raise AppException("Transfer authorization code is missing.", status_code=400)

        # ── Transfer re-entry safety guard ────────────────────────────────────
        # If OpenProvider has already returned a domain id for this transfer,
        # the transfer is ALREADY submitted. NEVER call transfer_domain() again
        # (no duplicate OP transfer orders, no duplicate charges). Adopt the
        # existing registrar record and stay REGISTRATION_PENDING until
        # OpenProvider completes the transfer on its own timeline.
        existing_op_id = (order.open_provider_domain_id or "").strip()
        if existing_op_id and not existing_op_id.upper().startswith("DEMO-"):
            logger.info(
                "Adopt existing transfer domain=%s existing_id=%s - transfer_domain NOT called (re-entry guard)",
                order.fqdn,
                existing_op_id,
            )
            order.transfer_status = "PENDING"
            order.status = RegistrationOrderStatus.REGISTRATION_PENDING
            from app.service.domain.domain_registration_followup import (
                stamp_registration_pending_since,
            )

            stamp_registration_pending_since(order)
            await self._orders.save(order)
            await self._session.commit()
            return {
                "id": str(order.id),
                "domain": order.fqdn,
                "status": order.status.value,
                "transferStatus": order.transfer_status,
            }

        name = order.domain_name
        ext = order.domain_extension.lstrip(".")

        reg = active_registrar()
        if reg.is_configured():
            if hasattr(reg, "lookup_order_id_by_domain"):
                existing = await reg.lookup_order_id_by_domain(order.fqdn)
                if existing:
                    logger.info("Adopt existing transfer at registrar domain=%s existing_id=%s - transfer_domain NOT called", order.fqdn, existing)
                    order.open_provider_domain_id = existing
                    order.transfer_status = "PENDING"
                    order.status = RegistrationOrderStatus.REGISTRATION_PENDING
                    from app.service.domain.domain_registration_followup import stamp_registration_pending_since
                    stamp_registration_pending_since(order)
                    await self._orders.save(order)
                    await self._session.commit()
                    return {
                        "id": str(order.id),
                        "domain": order.fqdn,
                        "status": order.status.value,
                        "transferStatus": order.transfer_status,
                    }

            from app.integrations.openprovider.client import transfer_domain as op_transfer

            phone_digits = (buyer.phone_number or "9999999999")[-10:]
            customer = {
                "name": {
                    "first_name": buyer.firstname or "Transfer",
                    "last_name": buyer.lastname or "User",
                    "full_name": buyer.full_name,
                },
                "email": str(buyer.email).strip(),
                "phone": {
                    "country_code": "+91",
                    "area_code": "0",
                    "subscriber_number": phone_digits,
                },
                "address": {
                    "street": "Street",
                    "number": "1",
                    "city": "City",
                    "zipcode": "560001",
                    "state": "State",
                    "country": "IN",
                },
            }
            try:
                handle = await reg.create_customer(customer)
                order.open_provider_handle = handle
                transfer_res = await op_transfer(
                    name=name,
                    extension_no_dot=ext,
                    auth_code=auth_code,
                    handle=handle,
                    period_years=1,
                )
            except Exception as exc:
                # A captured payment must never disappear and a provider
                # rejection must never be misrepresented. Record the real
                # outcome and raise an honest customer-facing error.
                return await self._handle_transfer_provision_failure(
                    order, exc, buyer=buyer,
                )
            order.open_provider_domain_id = str(transfer_res.get("id")) if transfer_res.get("id") is not None else None
            order.registrar_response_json = str(transfer_res)
            # transfer_domain() submits our default nameservers to OpenProvider;
            # store the same intent so DNS validation works while the transfer is
            # pending. sync_from_registrar() confirms the real value on completion.
            default_ns = _default_nameservers_for_order(order)
            if default_ns:
                set_order_nameservers(order, default_ns, "openprovider")

        order.transfer_status = "PENDING"
        order.status = RegistrationOrderStatus.REGISTRATION_PENDING
        await self._orders.save(order)
        await self._session.commit()
        return {
            "id": str(order.id),
            "domain": order.fqdn,
            "status": order.status.value,
            "transferStatus": order.transfer_status,
        }

    async def _handle_transfer_provision_failure(
        self,
        order: DomainRegistrationOrder,
        exc: Exception,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        """Record the REAL outcome of a failed provider transfer submission.

        The payment is already captured and committed by the caller. This method
        only records the provider result:

        * Definitive rejection (invalid EPP/auth code, locked domain, duplicate,
          insufficient balance, etc.): mark PROVISION_FAILED / FAILED, send the
          failure email, auto-refund the captured payment through the existing
          refund machinery, and raise a customer-facing AppException so the
          customer is never charged for a transfer that cannot proceed.
        * Registrar unreachable / ambiguous (timeout, connection, 5xx): leave
          the order PAYMENT_COMPLETED / PENDING so the transfer reconcile worker
          retries safely (bounded by provision_attempts); only after the retry
          limit is the transfer failed and refunded.
        """
        raw = str(exc)
        # Definitive rejections (invalid EPP/auth code, locked domain, duplicate,
        # insufficient balance, forbidden, etc.) are terminal: mark FAILED, email
        # the customer, and initiate the existing refund flow exactly once.
        if _is_definitive_transfer_failure(raw):
            logger.error(
                "domain_transfer.provision_failed order_id=%s domain=%s err=%s",
                order.id,
                order.fqdn,
                raw,
            )
            message = _friendly_transfer_error(raw, order.fqdn)
            await self._fail_transfer_and_refund(order, message)
            raise AppException(order.provision_message, status_code=502)

        # Transient / unknown provider failures (timeout, connection, 5xx,
        # ambiguous response): never refund yet and never blindly resubmit. Leave
        # the order PAYMENT_COMPLETED / PENDING so the transfer reconcile worker
        # retries safely, bounded by provision_attempts.
        attempts = int(order.provision_attempts or 0) + 1
        order.provision_attempts = attempts
        if attempts >= int(settings.DOMAIN_REGISTRATION_MAX_PROVISION_ATTEMPTS):
            logger.error(
                "domain_transfer.provision_unreachable_final order_id=%s domain=%s attempts=%s err=%s",
                order.id,
                order.fqdn,
                attempts,
                raw,
            )
            message = (
                "Payment received, but the registrar could not be reached after "
                "repeated attempts. Your payment is being refunded."
            )
            await self._fail_transfer_and_refund(order, message)
            raise AppException(order.provision_message, status_code=502)

        order.transfer_status = "PENDING"
        order.provision_message = (
            "Payment received — the registrar was temporarily unavailable "
            "while activating the transfer. The transfer will be retried "
            "automatically."
        )
        await self._orders.save(order)
        await self._session.commit()
        logger.error(
            "domain_transfer.provision_unreachable order_id=%s domain=%s attempts=%s err=%s",
            order.id,
            order.fqdn,
            attempts,
            raw,
        )
        return {
            "id": str(order.id),
            "domain": order.fqdn,
            "status": order.status.value,
            "transferStatus": order.transfer_status,
            "paymentReceived": True,
            "message": order.provision_message,
        }

    async def _fail_transfer_and_refund(self, order, message: str) -> None:
        """Record a definitive transfer failure, notify the customer, and refund.

        The failure state + email come first (so the failure email fires while
        the status is still PROVISION_FAILED), then the captured Razorpay
        payment is refunded exactly once through the EXISTING admin refund flow
        (rzp.refund_payment + razorpay_refund_id + REFUNDED status + webhook
        reconciliation). If the refund itself fails, the order stays
        PROVISION_FAILED with the failure message and the existing admin/webhook
        refund path can complete it — the customer is never charged permanently.
        """
        order.status = RegistrationOrderStatus.PROVISION_FAILED
        order.transfer_status = "FAILED"
        order.provision_message = message
        await self._orders.save(order)
        await self._session.commit()
        await self._followup.send_lifecycle_emails(order)

        # Duplicate-refund safety: skip if a refund is already recorded or the
        # order already moved to REFUNDED.
        if order.razorpay_refund_id or order.status == RegistrationOrderStatus.REFUNDED:
            return
        try:
            from app.service.domain.domain_registration_ops_service import (
                DomainRegistrationOpsService,
            )

            ops = DomainRegistrationOpsService(self._session)
            await ops.admin_refund(order.id)
        except Exception as exc:
            logger.warning(
                "domain_transfer.auto_refund_failed order_id=%s domain=%s err=%s",
                order.id,
                order.fqdn,
                exc,
            )

    async def initiate_transfer(
        self,
        payload: dict,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        raise AppException(
            "Domain transfer requires payment. Use the transfer/payment checkout flow.",
            status_code=402,
        )

    async def _service_price_catalog(self) -> dict[str, Any]:
        return await self.get_service_prices()

    @staticmethod
    def _ssl_foreign_to_inr(amount: float, currency: str) -> float:
        """OP SSL price → INR (no markup)."""
        code = (currency or "EUR").upper()
        if code == "INR":
            return round(float(amount), 2)
        from app.service.currency.exchange_rate_service import get_exchange_rates

        snapshot = get_exchange_rates()
        rates = snapshot.get("rates") or {}
        rate = float(rates.get(code) or 0)
        if rate <= 0:
            raise AppException(
                f"Cannot convert SSL price from {code} to INR.",
                status_code=503,
            )
        # rates are INR→foreign; invert for foreign→INR
        return round(float(amount) / rate, 2)

    @staticmethod
    def _is_domain_validation_ssl(product: dict[str, Any]) -> bool:
        category = str(product.get("category") or "").strip().lower()
        return category in {"domain_validation", "dv"}

    async def _fetch_ssl_products_priced(self) -> list[dict[str, Any]]:
        from app.integrations.openprovider.client import list_ssl_products

        reg = active_registrar()
        if not reg.is_configured():
            return []
        try:
            return await list_ssl_products(with_price=True, with_description=False)
        except Exception as exc:
            logger.warning("[SSL] list_ssl_products failed: %s", exc)
            return []

    async def _build_live_ssl_price_block(self, _apply) -> dict[str, Any]:
        """Live OP SSL catalog → FX → Admin SSL commission → customer prices."""
        from app.integrations.openprovider.client import extract_ssl_period_price
        from app.service.domain import domain_commission_config as commission

        products_out: list[dict[str, Any]] = []
        standard_pick: dict[str, Any] | None = None
        wildcard_pick: dict[str, Any] | None = None

        for product in await self._fetch_ssl_products_priced():
            if not self._is_domain_validation_ssl(product):
                continue
            try:
                base_amt, currency = extract_ssl_period_price(product, 1)
                base_inr = self._ssl_foreign_to_inr(base_amt, currency)
            except Exception as exc:
                logger.debug("[SSL] skip product %s: %s", product.get("id"), exc)
                continue

            marked = _apply(base_inr, "ssl")
            wildcard = bool(product.get("is_wildcard_supported"))
            entry = {
                "id": int(product["id"]),
                "name": product.get("name") or "",
                "brandName": product.get("brand_name") or "",
                "category": product.get("category") or "",
                "wildcard": wildcard,
                "periodYearsMax": int(product.get("max_period") or 1),
                "base": marked["base"],
                "commissionRate": marked["commissionRate"],
                "unitInr": marked["final"],
                "currency": "INR",
                "sourceCurrency": currency,
                "label": f"₹{int(marked['final'])} / yr",
            }
            products_out.append(entry)
            if wildcard:
                if wildcard_pick is None or entry["unitInr"] < wildcard_pick["unitInr"]:
                    wildcard_pick = entry
            else:
                if standard_pick is None or entry["unitInr"] < standard_pick["unitInr"]:
                    standard_pick = entry

        products_out.sort(key=lambda p: (p["wildcard"], p["unitInr"], p["id"]))

        block: dict[str, Any] = {
            "source": "openprovider" if products_out else "unavailable",
            "products": products_out,
            "commissionRate": commission.get_rate("ssl"),
        }
        if standard_pick:
            block["standard"] = {
                "productId": standard_pick["id"],
                "base": standard_pick["base"],
                "commissionRate": standard_pick["commissionRate"],
                "unitInr": standard_pick["unitInr"],
                "label": standard_pick["label"],
                "name": standard_pick["name"],
            }
        if wildcard_pick:
            block["wildcard"] = {
                "productId": wildcard_pick["id"],
                "base": wildcard_pick["base"],
                "commissionRate": wildcard_pick["commissionRate"],
                "unitInr": wildcard_pick["unitInr"],
                "label": wildcard_pick["label"],
                "name": wildcard_pick["name"],
            }
        cheapest = None
        for pick in (standard_pick, wildcard_pick):
            if pick and (cheapest is None or pick["unitInr"] < cheapest):
                cheapest = pick["unitInr"]
        if cheapest is not None:
            block["label"] = f"From ₹{int(cheapest)} / yr"
            block["unitInr"] = cheapest
        else:
            block["label"] = None
            block["unitInr"] = None
        return block

    async def _resolve_ssl_product_quote(
        self,
        *,
        product_id: int,
        period: int,
    ) -> dict[str, Any]:
        """OP list price → FX → Admin SSL markup for one product/period."""
        from app.integrations.openprovider.client import extract_ssl_period_price
        from app.service.domain import domain_commission_config as commission

        products = await self._fetch_ssl_products_priced()
        product = next((p for p in products if int(p.get("id") or 0) == int(product_id)), None)
        if product is None:
            raise AppException("SSL product not found or unavailable.", status_code=404)
        if not self._is_domain_validation_ssl(product):
            raise AppException(
                "Only domain-validation SSL products are available for purchase.",
                status_code=400,
            )
        years = max(1, int(period or 1))
        max_period = int(product.get("max_period") or 1)
        if years > max_period:
            raise AppException(
                f"Maximum certificate period for this product is {max_period} year(s).",
                status_code=400,
            )
        try:
            base_amt, currency = extract_ssl_period_price(product, years)
            base_inr = self._ssl_foreign_to_inr(base_amt, currency)
        except RuntimeError as exc:
            raise AppException(str(exc), status_code=400) from exc
        except AppException:
            raise
        except Exception as exc:
            raise AppException("Unable to price this SSL product.", status_code=502) from exc

        rate = commission.get_rate("ssl")
        unit_inr = commission.apply_markup(base_inr, rate)
        return {
            "productId": int(product["id"]),
            "productName": product.get("name") or "",
            "brandName": product.get("brand_name") or "",
            "wildcard": bool(product.get("is_wildcard_supported")),
            "period": years,
            "baseInr": base_inr,
            "sourceCurrency": currency,
            "commissionRate": rate,
            "unitInr": unit_inr,
        }

    @staticmethod
    def _read_addons_json(order: DomainRegistrationOrder) -> dict[str, Any]:
        if not order.dns_records_json:
            return {}
        try:
            data = json.loads(order.dns_records_json)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _write_addons_json(order: DomainRegistrationOrder, addons: dict[str, Any]) -> None:
        order.dns_records_json = json.dumps(addons)

    async def _set_pending_addon_payment(
        self,
        order: DomainRegistrationOrder,
        *,
        addon_type: str,
        razorpay_order_id: str,
        amount_inr: float,
        payload: dict[str, Any],
    ) -> None:
        addons = self._read_addons_json(order)
        existing = addons.get("_pendingAddon") or {}
        if isinstance(existing, dict) and existing.get("paymentVerified"):
            logger.warning(
                "addon.pending.blocked_duplicate order=%s existing_type=%s existing_payment=%s attempted_type=%s",
                order.id,
                existing.get("type"),
                existing.get("razorpayPaymentId"),
                addon_type,
            )
            raise AppException(
                "A paid addon is still being provisioned for this domain. "
                "Retry the previous payment verification, or contact support if it stays pending.",
                status_code=409,
            )
        if isinstance(existing, dict) and existing.get("razorpayOrderId"):
            logger.info(
                "addon.pending.replace order=%s old_type=%s old_rzp=%s new_type=%s new_rzp=%s",
                order.id,
                existing.get("type"),
                existing.get("razorpayOrderId"),
                addon_type,
                razorpay_order_id,
            )
        addons["_pendingAddon"] = {
            "type": addon_type,
            "razorpayOrderId": razorpay_order_id,
            "amountInr": amount_inr,
            "payload": payload,
            "paymentVerified": False,
            "provisionStatus": "pending_payment",
        }
        self._write_addons_json(order, addons)

    async def _clear_pending_addon_payment(self, order: DomainRegistrationOrder) -> None:
        addons = self._read_addons_json(order)
        addons.pop("_pendingAddon", None)
        self._write_addons_json(order, addons)

    async def _mark_pending_addon_paid(
        self,
        order: DomainRegistrationOrder,
        *,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> dict[str, Any]:
        addons = self._read_addons_json(order)
        pending = dict(addons.get("_pendingAddon") or {})
        pending["paymentVerified"] = True
        pending["provisionStatus"] = "paid_pending_provision"
        pending["razorpayPaymentId"] = razorpay_payment_id
        pending["razorpaySignature"] = razorpay_signature
        pending["paidAt"] = datetime.now(timezone.utc).isoformat()
        addons["_pendingAddon"] = pending
        self._write_addons_json(order, addons)
        return pending

    async def _consume_verified_pending_addon(
        self,
        order: DomainRegistrationOrder,
        payload: dict[str, str],
        *,
        expected_type: str,
    ) -> dict[str, Any]:
        """
        Validate Razorpay payment for a pending addon without clearing it.

        If payment was already verified, allow re-entry so OpenProvider provision
        can be retried after a transient failure (no second charge).
        """
        pending = dict(self._read_addons_json(order).get("_pendingAddon") or {})
        razorpay_order_id = str(payload.get("razorpayOrderId") or "").strip()
        razorpay_payment_id = str(payload.get("razorpayPaymentId") or "").strip()
        razorpay_signature = str(payload.get("razorpaySignature") or "").strip()
        if not pending:
            raise AppException(
                f"No pending {expected_type} addon payment found for this domain.",
                status_code=400,
            )
        if pending.get("razorpayOrderId") != razorpay_order_id:
            raise AppException(
                f"{expected_type.capitalize()} addon payment order mismatch.",
                status_code=400,
            )
        if pending.get("type") != expected_type:
            raise AppException(
                f"Pending addon is not a {expected_type} payment.",
                status_code=400,
            )

        already_paid = bool(pending.get("paymentVerified")) and (
            not razorpay_payment_id
            or str(pending.get("razorpayPaymentId") or "") == razorpay_payment_id
        )
        if already_paid:
            logger.info(
                "addon.verify.retry order=%s type=%s payment=%s",
                order.id,
                expected_type,
                pending.get("razorpayPaymentId"),
            )
            return pending
        if not rzp.verify_payment_signature(
            razorpay_order_id,
            razorpay_payment_id,
            razorpay_signature,
        ):
            raise AppException("Payment verification failed.", status_code=400)
        pending = await self._mark_pending_addon_paid(
            order,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
        )
        await self._orders.save(order)
        # Commit before OpenProvider provision so a later OP failure does not
        # roll back paymentVerified (get_async_db rolls back on exceptions).
        await self._session.commit()
        logger.info(
            "addon.verify.paid order=%s type=%s payment=%s amount=%s",
            order.id,
            expected_type,
            razorpay_payment_id,
            pending.get("amountInr"),
        )
        return pending

    async def _finalize_pending_addon_after_success(
        self,
        order: DomainRegistrationOrder,
        *,
        expected_type: str,
    ) -> None:
        addons = self._read_addons_json(order)
        pending = addons.get("_pendingAddon") or {}
        if isinstance(pending, dict) and pending.get("type") == expected_type:
            addons.pop("_pendingAddon", None)
            self._write_addons_json(order, addons)

    async def get_email_addon_quote(
        self,
        order_id: uuid.UUID,
        *,
        months: int = 1,
        buyer: AppUser,
    ) -> dict[str, Any]:
        await self.get_order(order_id, buyer=buyer)
        prices = await self._service_price_catalog()
        unit_inr = float(prices.get("email", {}).get("unitInr") or 100.0)
        pricing = domain_price_breakdown(unit_inr * max(1, months), years=1)
        return {
            "registrationOrderId": str(order_id),
            "months": months,
            "unitPriceInr": unit_inr,
            **pricing,
        }

    async def create_email_addon_payment_order(
        self,
        order_id: uuid.UUID,
        body: dict[str, Any],
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        if not rzp.is_configured():
            raise AppException("Payment gateway is not configured.", status_code=503)
        order = await self.get_order(order_id, buyer=buyer)
        raw_mailbox = body.get("mailbox")
        if isinstance(raw_mailbox, str):
            email_prefix = raw_mailbox.strip()
            months = int(body.get("duration") or 1)
            try:
                quota_gb = int(body.get("size") or 5)
            except (TypeError, ValueError):
                quota_gb = 5
        else:
            mailbox = raw_mailbox if isinstance(raw_mailbox, dict) else {}
            email_prefix = str(
                mailbox.get("email")
                or mailbox.get("mailbox")
                or mailbox.get("prefix")
                or body.get("email")
                or ""
            ).strip()
            months = int(mailbox.get("duration") or body.get("duration") or 1)
            try:
                quota_gb = int(mailbox.get("size") or body.get("size") or 5)
            except (TypeError, ValueError):
                quota_gb = 5
        if not email_prefix:
            raise AppException("Email address is required.", status_code=400)
        quota_gb = max(1, min(quota_gb, 100))
        quote = await self.get_email_addon_quote(order_id, months=months, buyer=buyer)
        rzp_order = rzp.create_order(
            amount_inr=quote["totalInr"],
            receipt=f"dmail_{order.domain_name}_{int(datetime.now(timezone.utc).timestamp())}",
            notes={"type": "domain_email_addon", "orderId": str(order.id)},
        )
        await self._set_pending_addon_payment(
            order,
            addon_type="email",
            razorpay_order_id=rzp_order["id"],
            amount_inr=quote["totalInr"],
            payload={
                "mailbox": email_prefix.split("@")[0].strip().lower(),
                "months": months,
                "quotaGb": quota_gb,
            },
        )
        await self._orders.save(order)
        await self._session.commit()
        return {
            "orderId": rzp_order["id"],
            "amount": quote["totalInr"],
            "amountSmallest": int(round(float(quote["totalInr"]) * 100)),
            "currency": "INR",
            "keyId": rzp.get_key_id(),
            "registrationOrderId": str(order.id),
            **quote,
        }

    async def verify_email_addon_payment(
        self,
        order_id: uuid.UUID,
        payload: dict[str, str],
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        order = await self.get_order(order_id, buyer=buyer)
        pending = await self._consume_verified_pending_addon(
            order, payload, expected_type="email"
        )
        pending_payload = dict(pending.get("payload") or {})
        mailbox = str(pending_payload.get("mailbox") or "")
        try:
            detail = await self.add_email_addon(
                order_id,
                mailbox,
                buyer=buyer,
                _payment_verified=True,
                pending_payload=pending_payload,
            )
        except Exception:
            logger.exception(
                "email addon provision failed after payment order=%s payment=%s",
                order_id,
                pending.get("razorpayPaymentId"),
            )
            raise
        order = await self.get_order(order_id, buyer=buyer)
        await self._finalize_pending_addon_after_success(order, expected_type="email")
        await self._orders.save(order)
        await self._session.commit()
        return detail

    async def get_ssl_addon_quote(
        self,
        order_id: uuid.UUID,
        *,
        buyer: AppUser,
        product_id: int | None = None,
        period: int = 1,
        cert_type: str | None = None,
    ) -> dict[str, Any]:
        await self.get_order(order_id, buyer=buyer)
        resolved_product_id = product_id
        if resolved_product_id is None:
            # Backward-compatible fallback: cheapest standard/wildcard from live catalog
            catalog = await self._service_price_catalog()
            ssl_prices = catalog.get("ssl") or {}
            key = "wildcard" if (cert_type or "").lower() in {"ev", "wildcard"} else "standard"
            bucket = ssl_prices.get(key) or {}
            resolved_product_id = bucket.get("productId")
            if resolved_product_id is None and ssl_prices.get("products"):
                resolved_product_id = ssl_prices["products"][0].get("id")
        if resolved_product_id is None:
            raise AppException(
                "SSL products are currently unavailable. Please try again later.",
                status_code=503,
            )
        resolved = await self._resolve_ssl_product_quote(
            product_id=int(resolved_product_id),
            period=period,
        )
        pricing = domain_price_breakdown(resolved["unitInr"], years=1)
        return {
            "registrationOrderId": str(order_id),
            "productId": resolved["productId"],
            "productName": resolved["productName"],
            "years": resolved["period"],
            "period": resolved["period"],
            "wildcard": resolved["wildcard"],
            "certType": "wildcard" if resolved["wildcard"] else "standard",
            "unitPriceInr": resolved["unitInr"],
            "baseInr": resolved["baseInr"],
            "commissionRate": resolved["commissionRate"],
            **pricing,
        }

    async def create_ssl_addon_payment_order(
        self,
        order_id: uuid.UUID,
        body: dict[str, Any],
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        if not rzp.is_configured():
            raise AppException("Payment gateway is not configured.", status_code=503)
        order = await self.get_order(order_id, buyer=buyer)
        handle = (order.open_provider_handle or "").strip()
        if not handle or handle.startswith("DEMO-"):
            raise AppException(
                "SSL certificates require a registrar contact handle on this domain. "
                "Complete domain registration first.",
                status_code=400,
            )

        product_id_raw = body.get("productId") or body.get("product_id")
        period = int(body.get("period") or body.get("duration") or 1)
        cert_type = body.get("certType")
        approver_email = str(body.get("approverEmail") or body.get("approver_email") or "").strip()
        validation_method = str(
            body.get("validationMethod") or body.get("validation_method") or ""
        ).strip().lower()
        if validation_method and validation_method not in {"https", "email"}:
            raise AppException(
                "validationMethod must be 'https' or 'email'.",
                status_code=400,
            )

        quote = await self.get_ssl_addon_quote(
            order_id,
            buyer=buyer,
            product_id=int(product_id_raw) if product_id_raw is not None else None,
            period=period,
            cert_type=str(cert_type) if cert_type else None,
        )

        if not approver_email:
            raise AppException("approverEmail is required.", status_code=400)

        # Default validation: email when not specified; https when OP DNS automation likely
        if not validation_method:
            ns_hosts, _ = _parse_order_nameservers(order)
            from app.service.domain.domain_registration_followup import dnssec_management_supported

            validation_method = "https" if dnssec_management_supported(order) else "email"

        if validation_method == "email":
            from app.integrations.openprovider.client import list_ssl_approver_emails

            try:
                allowed = await list_ssl_approver_emails(int(quote["productId"]), order.fqdn)
            except Exception as exc:
                logger.warning("[SSL] approver-emails failed: %s", exc)
                allowed = []
            if allowed and approver_email.lower() not in {a.lower() for a in allowed}:
                raise AppException(
                    "approverEmail must be one of the registrar-approved addresses for this domain.",
                    status_code=400,
                )

        host_names: list[str] = []
        if not quote.get("wildcard"):
            www = f"www.{order.fqdn}"
            if www != order.fqdn:
                host_names.append(www)

        rzp_order = rzp.create_order(
            amount_inr=quote["totalInr"],
            receipt=f"dssl_{order.domain_name}_{int(datetime.now(timezone.utc).timestamp())}",
            notes={"type": "domain_ssl_addon", "orderId": str(order.id)},
        )
        await self._set_pending_addon_payment(
            order,
            addon_type="ssl",
            razorpay_order_id=rzp_order["id"],
            amount_inr=quote["totalInr"],
            payload={
                "productId": quote["productId"],
                "productName": quote.get("productName"),
                "period": quote["period"],
                "approverEmail": approver_email,
                "validationMethod": validation_method,
                "hostNames": host_names,
                "wildcard": bool(quote.get("wildcard")),
                "unitInr": quote["unitPriceInr"],
                "commissionRate": quote.get("commissionRate"),
                "baseInr": quote.get("baseInr"),
            },
        )
        await self._orders.save(order)
        await self._session.commit()
        return {
            "orderId": rzp_order["id"],
            "amount": quote["totalInr"],
            "currency": "INR",
            "keyId": rzp.get_key_id(),
            "registrationOrderId": str(order.id),
            "approverEmail": approver_email,
            "validationMethod": validation_method,
            **quote,
        }

    async def verify_ssl_addon_payment(
        self,
        order_id: uuid.UUID,
        payload: dict[str, str],
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        order = await self.get_order(order_id, buyer=buyer)
        pending = await self._consume_verified_pending_addon(
            order, payload, expected_type="ssl"
        )
        pending_payload = dict(pending.get("payload") or {})
        try:
            detail = await self.add_ssl_addon(
                order_id,
                buyer=buyer,
                _payment_verified=True,
                pending_payload=pending_payload,
            )
        except Exception:
            logger.exception(
                "ssl addon provision failed after payment order=%s payment=%s",
                order_id,
                pending.get("razorpayPaymentId"),
            )
            raise
        order = await self.get_order(order_id, buyer=buyer)
        await self._finalize_pending_addon_after_success(order, expected_type="ssl")
        await self._orders.save(order)
        await self._session.commit()
        return detail

    async def add_email_addon(
        self,
        order_id: uuid.UUID,
        mailbox: str,
        *,
        buyer: AppUser,
        _payment_verified: bool = False,
        pending_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not _payment_verified:
            raise AppException(
                "Email addon requires payment. Use the email addon payment checkout flow.",
                status_code=402,
            )
        import secrets

        from app.integrations.openprovider.client import (
            mailcow_add_domain,
            mailcow_assign_mailbox,
            mailcow_create_order,
            mailcow_get_mailbox_password,
            mailcow_increase_mailbox_quota,
            mailcow_list_domains,
        )

        order = await self.get_order(order_id, buyer=buyer)
        handle = (order.open_provider_handle or "").strip()
        if not handle or handle.startswith("DEMO-"):
            raise AppException(
                "Cannot provision email without a registrar contact handle.",
                status_code=400,
            )

        payload = dict(pending_payload or {})
        local_part = (mailbox or payload.get("mailbox") or "").strip().lower().split("@")[0]
        if not local_part:
            raise AppException("Mailbox prefix is required.", status_code=400)
        months = max(1, int(payload.get("months") or 1))
        try:
            quota_gb = max(1, min(int(payload.get("quotaGb") or 5), 100))
        except (TypeError, ValueError):
            quota_gb = 5

        name = (order.domain_name or "").strip().lower()
        ext = (order.domain_extension or "").strip().lower().lstrip(".")
        full_mailbox = f"{local_part}@{order.fqdn}"
        generated_password = secrets.token_urlsafe(14)

        # Idempotent retry: mailbox already recorded after a prior successful OP call.
        addons_existing = self._read_addons_json(order)
        prior_mailboxes = addons_existing.get("mailboxes")
        if isinstance(prior_mailboxes, list):
            for item in prior_mailboxes:
                if not isinstance(item, dict):
                    continue
                if str(item.get("address") or "").strip().lower() != full_mailbox.lower():
                    continue
                if item.get("opOrderId") is None:
                    break
                logger.info(
                    "email.addon.idempotent_hit order=%s mailbox=%s opOrderId=%s",
                    order_id,
                    full_mailbox,
                    item.get("opOrderId"),
                )
                password = ""
                try:
                    password = await mailcow_get_mailbox_password(int(item["opOrderId"]))
                except Exception as exc:
                    logger.warning(
                        "email.addon.idempotent_password_fetch_failed order=%s: %s",
                        order_id,
                        exc,
                    )
                detail = await self.get_order_detail(order_id, buyer=buyer, sync=False)
                detail["mailboxProvisioned"] = {
                    "address": full_mailbox.lower(),
                    "password": password,
                    "quotaGb": item.get("quotaGb") or quota_gb,
                    "months": item.get("months") or months,
                    "opOrderId": item.get("opOrderId"),
                    "alreadyProvisioned": True,
                }
                return detail

        try:
            existing = await mailcow_list_domains(limit=200, offset=0)
            domain_present = False
            for row in existing:
                dom = row.get("domain") if isinstance(row.get("domain"), dict) else {}
                if (
                    str(dom.get("name") or "").lower() == name
                    and str(dom.get("extension") or "").lower().lstrip(".") == ext
                ):
                    domain_present = True
                    break
            if not domain_present:
                await mailcow_add_domain(
                    name=name,
                    extension_no_dot=ext,
                    owner_handle=handle,
                    description=f"HubRegistrar order {order.id}",
                )

            await mailcow_create_order(period_months=months, quantity=1)
            assigned = await mailcow_assign_mailbox(
                name=name,
                extension_no_dot=ext,
                mailbox=local_part,
                password=generated_password,
                full_name=(order.buyer_full_name or "").strip(),
                subscription_period_months=months,
                reset_password=False,
            )
            op_order_id = assigned.get("id")
            if op_order_id is not None and not generated_password:
                try:
                    generated_password = await mailcow_get_mailbox_password(int(op_order_id))
                except Exception as exc:
                    logger.warning("mailcow password fetch failed order=%s: %s", order_id, exc)

            if quota_gb > 1:
                try:
                    await mailcow_increase_mailbox_quota(
                        name=name,
                        extension_no_dot=ext,
                        mailbox=local_part,
                        quota_gb=quota_gb,
                    )
                except Exception as exc:
                    logger.warning(
                        "mailcow quota increase skipped order=%s mailbox=%s: %s",
                        order_id,
                        local_part,
                        exc,
                    )
        except RuntimeError as exc:
            logger.warning("Mailcow provision failed order=%s: %s", order_id, exc)
            raise AppException(
                "We were unable to provision this mailbox with the email provider. "
                "Your payment was received — please contact support if the mailbox does not appear.",
                status_code=http_status_for_openprovider_error(str(exc)),
            ) from exc

        addons = self._read_addons_json(order)
        mailboxes = addons.get("mailboxes")
        if not isinstance(mailboxes, list):
            mailboxes = []
        # Migrate legacy string entries; store structured mailbox records going forward.
        normalized: list[Any] = []
        seen = set()
        for item in mailboxes:
            if isinstance(item, str):
                addr = item.strip().lower()
                if addr and addr not in seen:
                    normalized.append({"address": addr, "status": "local"})
                    seen.add(addr)
            elif isinstance(item, dict):
                addr = str(item.get("address") or "").strip().lower()
                if addr and addr not in seen:
                    normalized.append(item)
                    seen.add(addr)
        if full_mailbox.lower() not in seen:
            normalized.append(
                {
                    "address": full_mailbox.lower(),
                    "localPart": local_part,
                    "opOrderId": int(op_order_id) if op_order_id is not None else None,
                    "status": str(assigned.get("status") or assigned.get("mailbox_status") or "active"),
                    "quotaGb": quota_gb,
                    "months": months,
                    "provisionedAt": datetime.now(timezone.utc).isoformat(),
                }
            )
        addons["mailboxes"] = normalized
        # Never persist mailbox passwords in order JSON.
        addons.pop("mailbox_passwords", None)
        self._write_addons_json(order, addons)
        await self._orders.save(order)
        await self._session.commit()

        detail = await self.get_order_detail(order_id, buyer=buyer, sync=False)
        detail["mailboxProvisioned"] = {
            "address": full_mailbox.lower(),
            "password": generated_password,
            "quotaGb": quota_gb,
            "months": months,
            "opOrderId": int(op_order_id) if op_order_id is not None else None,
        }
        return detail

    async def add_ssl_addon(
        self,
        order_id: uuid.UUID,
        *,
        buyer: AppUser,
        _payment_verified: bool = False,
        pending_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not _payment_verified:
            raise AppException(
                "SSL addon requires payment. Use the SSL addon payment checkout flow.",
                status_code=402,
            )
        from app.integrations.openprovider.client import (
            create_ssl_order,
            generate_ssl_csr,
        )
        from app.service.domain.domain_registration_followup import dnssec_management_supported

        order = await self.get_order(order_id, buyer=buyer)
        handle = (order.open_provider_handle or "").strip()
        if not handle or handle.startswith("DEMO-"):
            raise AppException(
                "Cannot provision SSL without a registrar contact handle.",
                status_code=400,
            )

        payload = dict(pending_payload or {})
        product_id = payload.get("productId")
        if product_id is None:
            raise AppException("Missing SSL product in payment payload.", status_code=400)
        period = max(1, int(payload.get("period") or 1))
        approver_email = str(payload.get("approverEmail") or "").strip()
        if not approver_email:
            raise AppException("Missing approver email in payment payload.", status_code=400)
        validation_method = str(payload.get("validationMethod") or "email").strip().lower()
        if validation_method not in {"https", "email"}:
            validation_method = "email"
        wildcard = bool(payload.get("wildcard"))
        host_names = [str(h).strip().lower() for h in (payload.get("hostNames") or []) if str(h).strip()]

        common_name = f"*.{order.fqdn}" if wildcard else order.fqdn
        san = list(host_names)
        if not wildcard and order.fqdn not in san:
            # CSR SAN for www only; common_name is apex
            pass

        try:
            csr_result = await generate_ssl_csr(
                common_name=common_name,
                country=order.country or "IN",
                email=approver_email or (order.buyer_email or ""),
                organization=(order.buyer_full_name or "Private").strip() or "Private",
                locality=(order.city or order.street or "N/A").strip() or "N/A",
                state=(order.state or order.city or "N/A").strip() or "N/A",
                unit="IT",
                bits=2048,
                subject_alternative_name=san or None,
                with_config=False,
                signature_hash_algorithm="sha2",
            )
        except RuntimeError as exc:
            raise AppException(
                "Unable to generate SSL certificate request. Please try again.",
                status_code=502,
            ) from exc

        enable_dns = bool(dnssec_management_supported(order))
        order_body: dict[str, Any] = {
            "product_id": int(product_id),
            "period": period,
            "csr": csr_result["csr"],
            "software_id": "linux",
            "organization_handle": handle,
            "technical_handle": handle,
            "approver_email": approver_email,
            "signature_hash_algorithm": "sha2",
            "start_provision": True,
            "autorenew": "off",
            "enable_dns_automation": enable_dns,
            "domain_validation_methods": [
                {"host_name": order.fqdn, "method": validation_method}
            ],
        }
        if host_names:
            order_body["host_names"] = host_names
        if wildcard:
            order_body["wildcard_domain_amount"] = 1
        else:
            order_body["domain_amount"] = 1

        try:
            op_order_id = await create_ssl_order(order_body)
        except RuntimeError as exc:
            logger.warning("[SSL] create_ssl_order failed order=%s: %s", order_id, exc)
            raise AppException(
                "Unable to create SSL certificate order with the registrar. Please contact support.",
                status_code=502,
            ) from exc

        addons = self._read_addons_json(order)
        # Drop legacy flags when real SSL object is present
        addons.pop("ssl_active", None)
        addons.pop("ssl_expiry", None)
        addons["ssl"] = {
            "active": False,
            "opOrderId": op_order_id,
            "productId": int(product_id),
            "productName": payload.get("productName") or "",
            "commonName": common_name,
            "status": "REQ",
            "periodYears": period,
            "approverEmail": approver_email,
            "validationMethod": validation_method,
            "orderedAt": datetime.now(timezone.utc).isoformat(),
            "expiresAt": None,
            "privateKey": csr_result["key"],
            "csr": csr_result["csr"],
            "certificate": None,
            "additionalData": None,
            "unitInr": payload.get("unitInr"),
            "commissionRate": payload.get("commissionRate"),
            "lastSyncedAt": datetime.now(timezone.utc).isoformat(),
        }
        self._write_addons_json(order, addons)
        await self._orders.save(order)
        await self._session.commit()
        # Sync once to pull status / validation hints
        await self._followup.sync_ssl_addon(order)
        await self._session.commit()
        return await self.get_order_detail(order_id, buyer=buyer, sync=False)

    async def retrieve_auth_code_and_unlock(
        self,
        domain: str,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        """Retrieve the real EPP/Auth code and disable the registrar transfer lock.

        Security guarantees:
        - Only the authenticated domain owner can initiate Transfer OUT.
        - The domain must be in a transfer-eligible state (ACTIVE).
        - Only the real EPP code from the registrar is returned.
        - No fake/demo EPP code is ever returned.
        - The registrar lock is verified as unlocked via read-back.
        - Concurrent requests are safely rejected.
        - No Razorpay/payment operations are performed.
        """
        from app.service.domain.domain_registration_followup import sanitize_customer_registrar_message

        fqdn = domain.strip().lower()

        # ── 1. Ownership verification ──
        orders = await self._orders.list_by_buyer(buyer.id)
        order = None
        for o in orders:
            if o.fqdn == fqdn:
                order = o
                break

        if not order:
            raise AppException(
                "Domain not found under your registered account.",
                status_code=404,
            )

        # Double-check ownership: buyer_id must match authenticated user.
        if str(order.buyer_id) != str(buyer.id):
            raise AppException(
                "You are not authorized to transfer this domain.",
                status_code=403,
            )

        # ── 2. Concurrency / double-click protection ──
        if order.transfer_status and order.transfer_status not in (
            "NONE", "FAILED", "CANCELLED",
        ):
            raise AppException(
                "A transfer is already in progress for this domain. Please wait for it to complete.",
                status_code=409,
            )

        # ── 3. Domain eligibility validation ──
        if hasattr(order, 'status') and order.status:
            non_transferable_statuses = {
                'EXPIRED', 'REDEMPTION', 'CANCELLED', 'DELETED',
                'FAILED', 'PROVISION_FAILED', 'PAYMENT_FAILED', 'REFUNDED',
            }
            order_status = str(order.status).upper()
            if order_status in non_transferable_statuses:
                raise AppException(
                    f"This domain cannot be transferred because its status is '{order_status}'.",
                    status_code=400,
                )

            if order_status in ('CREATED',) and not order.open_provider_domain_id:
                raise AppException(
                    "This domain has not been fully provisioned and cannot be transferred.",
                    status_code=400,
                )

        # ── 4. Validate OpenProvider domain ID ──
        reg = active_registrar()
        if not reg.is_configured():
            raise AppException(
                "The domain registrar service is not available. Please try again later or contact support.",
                status_code=503,
            )

        if not order.open_provider_domain_id or str(order.open_provider_domain_id).startswith("DEMO-"):
            raise AppException(
                "This domain is not configured for transfer at this time. Please contact support.",
                status_code=400,
            )

        domain_id = str(order.open_provider_domain_id)

        # ── 5. Validate domain status at provider ──
        try:
            if hasattr(reg, 'get_domain_all_details'):
                provider_details = await reg.get_domain_all_details(domain_id)
                provider_status = (
                    provider_details.get('status', '')
                    or provider_details.get('domain_status', '')
                )
                if isinstance(provider_status, str):
                    provider_status_upper = provider_status.upper()
                    if provider_status_upper in ('EXPIRED', 'REDEMPTION', 'CANCELLED', 'DELETED'):
                        raise AppException(
                            f"This domain cannot be transferred because its registrar status is '{provider_status}'.",
                            status_code=400,
                        )
        except AppException:
            raise
        except Exception as exc:
            logger.warning("[TRANSFER_OUT] Could not verify provider status for %s: %s", fqdn, exc)
            raise AppException(
                "Unable to verify domain status with the registrar. Please try again later.",
                status_code=502,
            )

        # ── 6. Retrieve REAL EPP/Auth code ──
        auth_code = None
        try:
            if hasattr(reg, 'get_auth_code'):
                auth_code = await reg.get_auth_code(domain_id)
            elif hasattr(reg, 'get_domain_all_details'):
                details = await reg.get_domain_all_details(domain_id)
                auth_code = details.get('auth_code') or details.get('authCode')
        except Exception as exc:
            logger.warning("[TRANSFER_OUT] Auth code retrieval failed for %s: %s", fqdn, exc)
            # Try reset as fallback
            try:
                if hasattr(reg, 'reset_auth_code'):
                    auth_code = await reg.reset_auth_code(domain_id)
            except Exception as exc2:
                logger.warning("[TRANSFER_OUT] Auth code reset also failed for %s: %s", fqdn, exc2)

        if not auth_code or not str(auth_code).strip():
            raise AppException(
                "Unable to retrieve the domain authorization code from the registrar. "
                "Please try again later or contact support.",
                status_code=502,
            )
        auth_code = str(auth_code).strip()

        # ── 7. Disable transfer lock at provider ──
        unlocked = False
        if hasattr(reg, 'set_domain_locked'):
            try:
                await reg.set_domain_locked(domain_id, False)
            except Exception as exc:
                logger.warning("[TRANSFER_OUT] Unlock failed for %s: %s", fqdn, exc)
                raise AppException(
                    "The domain could not be unlocked at the registrar. "
                    "Please try again later or contact support.",
                    status_code=502,
                )

            # ── 8. Verify lock state via read-back ──
            try:
                if hasattr(reg, 'get_domain_all_details'):
                    verify = await reg.get_domain_all_details(domain_id)
                    is_locked = verify.get('is_locked', True)
                    if is_locked is True or str(is_locked).lower() in ('true', '1'):
                        logger.error(
                            "[TRANSFER_OUT] Lock verification failed for %s: is_locked=%s",
                            fqdn, is_locked,
                        )
                        raise AppException(
                            "The registrar could not confirm that the domain was unlocked. "
                            "Please try again later or contact support.",
                            status_code=502,
                        )
                    unlocked = True
            except AppException:
                raise
            except Exception as exc:
                logger.warning("[TRANSFER_OUT] Lock read-back failed for %s: %s", fqdn, exc)
                raise AppException(
                    "Could not verify domain unlock status. "
                    "Please try again later or contact support.",
                    status_code=502,
                )
        else:
            unlocked = True

        # ── 9. Update local state only after provider confirmation ──
        order.transfer_auth_code = auth_code
        order.registrar_lock = False
        order.transfer_status = "AUTH_CODE_AVAILABLE"
        await self._orders.save(order)
        await self._session.commit()

        # ── 10. Audit log (do NOT log the actual EPP code) ──
        logger.info(
            "[TRANSFER_OUT] SUCCESS user=%s domain=%s unlocked=%s",
            buyer.id, fqdn, unlocked,
        )

        return {
            "domain": order.fqdn,
            "authCode": auth_code,
            "unlocked": unlocked,
            "message": (
                "Domain successfully unlocked. Use the Authorization Code below "
                "at your new registrar to complete the transfer."
            ),
        }

    async def _ensure_dns_managed_nameservers(self, order: DomainRegistrationOrder) -> None:
        """Validate that the domain uses our OpenProvider platform nameservers.

        Refresh-on-failure: validation runs against the database first (no
        registrar call on the happy path). Only when it fails AND the order has
        not been synced recently do we refresh once from OpenProvider and
        re-validate — this self-heals stale rows without hammering OpenProvider
        for domains on external nameservers.

        Legacy ResellerClub test domains are not supported for DNS here; they
        must be transferred to OpenProvider first.
        """
        if is_legacy_resellerclub_order(order):
            raise AppException(
                sanitize_customer_registrar_message(
                    "This domain is still at the previous registrar and must be "
                    "transferred to OpenProvider before DNS can be managed in HubRegistrar. "
                    "See docs/LEGACY_RESELLERCLUB_TO_OPENPROVIDER.md."
                ),
                status_code=400,
            )
        if _order_is_using_default_nameservers(order):
            return
        if _registrar_sync_is_stale(order):
            await self._followup.sync_from_registrar(order)
            await self._session.commit()
            if _order_is_using_default_nameservers(order):
                return
        raise AppException(
            "DNS records can only be managed when the domain uses our default nameservers.",
            status_code=400,
        )

    async def _ensure_dns_zone(self, order: DomainRegistrationOrder) -> None:
        """Ensure an OpenProvider MASTER DNS zone exists before record operations.

        If the zone is missing, create it automatically. If creation fails, raise
        the registrar error so the caller does not mask it.
        """
        reg = active_registrar()
        if not hasattr(reg, "get_dns_zone") or not hasattr(reg, "create_dns_zone"):
            return
        if not reg.is_configured():
            return

        fqdn = order.fqdn
        try:
            zone = await reg.get_dns_zone(fqdn)
        except RuntimeError as exc:
            raise AppException(str(exc), status_code=400) from exc

        if zone is None:
            try:
                await reg.create_dns_zone(fqdn)
            except RuntimeError as exc:
                raise AppException(str(exc), status_code=400) from exc

    async def get_dns_records(self, order_id: uuid.UUID, *, buyer: AppUser) -> list[dict[str, Any]]:
        order = await self.get_order(order_id, buyer=buyer)
        self._assert_manageable(order)
        await self._ensure_dns_managed_nameservers(order)
        await self._ensure_dns_zone(order)
        reg = active_registrar()
        if hasattr(reg, "get_dns_records"):
            try:
                return await reg.get_dns_records(order.fqdn)
            except RuntimeError as exc:
                raise AppException(str(exc), status_code=400) from exc
        return [
            {"id": "mock-dns-1", "type": "A", "name": "@", "value": "192.168.1.1", "ttl": 3600},
            {"id": "mock-dns-2", "type": "CNAME", "name": "www", "value": "drymortar.in", "ttl": 3600},
        ]

    async def create_dns_record(
        self,
        order_id: uuid.UUID,
        payload: dict[str, Any],
        *,
        buyer: AppUser,
    ) -> bool:
        order = await self.get_order(order_id, buyer=buyer)
        self._assert_manageable(order)
        await self._ensure_dns_managed_nameservers(order)
        await self._ensure_dns_zone(order)
        reg = active_registrar()
        if hasattr(reg, "create_dns_record"):
            try:
                return await reg.create_dns_record(order.fqdn, payload)
            except RuntimeError as exc:
                raise AppException(str(exc), status_code=400) from exc
        return True

    async def update_dns_record(
        self,
        order_id: uuid.UUID,
        record_id: str,
        payload: dict[str, Any],
        *,
        buyer: AppUser,
    ) -> bool:
        order = await self.get_order(order_id, buyer=buyer)
        self._assert_manageable(order)
        await self._ensure_dns_managed_nameservers(order)
        await self._ensure_dns_zone(order)
        reg = active_registrar()
        if hasattr(reg, "update_dns_record"):
            try:
                return await reg.update_dns_record(order.fqdn, old_record_id=record_id, new_payload=payload)
            except RuntimeError as exc:
                raise AppException(str(exc), status_code=400) from exc
        return True

    async def delete_dns_record(
        self,
        order_id: uuid.UUID,
        record_id: str,
        *,
        buyer: AppUser,
    ) -> bool:
        order = await self.get_order(order_id, buyer=buyer)
        self._assert_manageable(order)
        await self._ensure_dns_managed_nameservers(order)
        await self._ensure_dns_zone(order)
        reg = active_registrar()
        if hasattr(reg, "delete_dns_record"):
            try:
                return await reg.delete_dns_record(order.fqdn, record_id)
            except RuntimeError as exc:
                raise AppException(str(exc), status_code=400) from exc
        return True

    async def toggle_dnssec(
        self,
        order_id: uuid.UUID,
        enabled: bool,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        order = await self.get_order(order_id, buyer=buyer)
        self._assert_manageable(order)

        from app.service.domain.domain_registration_followup import (
            dnssec_management_supported,
        )

        if not dnssec_management_supported(order):
            # Refresh-on-failure: the stored nameservers may be stale (see
            # _ensure_dns_managed_nameservers). Sync once, then re-check.
            if _registrar_sync_is_stale(order):
                await self._followup.sync_from_registrar(order)
                await self._session.commit()
            if not dnssec_management_supported(order):
                raise AppException(
                    "DNSSEC management is not available for this domain.",
                    status_code=400,
                )

        reg = active_registrar()
        if hasattr(reg, "update_dnssec") and order.open_provider_domain_id and not str(order.open_provider_domain_id).startswith("DEMO-"):
            try:
                await reg.update_dnssec(
                    order.open_provider_domain_id,
                    enabled,
                    domain_fqdn=order.fqdn,
                )
            except RuntimeError as exc:
                logger.warning("DNSSEC update failed order=%s: %s", order_id, exc)
                raise AppException(
                    "We were unable to update DNSSEC settings for this domain. Please try again.",
                    status_code=502,
                ) from exc
            
        # Store state inside dns_records_json
        addons = {}
        if order.dns_records_json:
            try:
                addons = json.loads(order.dns_records_json)
            except Exception:
                addons = {}
        addons["dnssec_enabled"] = enabled
        order.dns_records_json = json.dumps(addons)
        await self._orders.save(order)
        await self._session.commit()
        return await self.get_order_detail(order_id, buyer=buyer, sync=False)

    async def update_mailbox_password(
        self,
        order_id: uuid.UUID,
        mailbox: str,
        password: str,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        from app.integrations.openprovider.client import mailcow_edit_mailbox

        order = await self.get_order(order_id, buyer=buyer)
        local_part = (mailbox or "").strip().lower().split("@")[0]
        new_password = (password or "").strip()
        if not local_part or not new_password:
            raise AppException("mailbox and password are required", status_code=400)
        if len(new_password) < 8:
            raise AppException("Password must be at least 8 characters.", status_code=400)

        name = (order.domain_name or "").strip().lower()
        ext = (order.domain_extension or "").strip().lower().lstrip(".")
        try:
            await mailcow_edit_mailbox(
                name=name,
                extension_no_dot=ext,
                mailbox=local_part,
                password=new_password,
                password_confirmation=new_password,
                reset_password=False,
            )
        except RuntimeError as exc:
            logger.warning("Mailcow password update failed order=%s: %s", order_id, exc)
            raise AppException(
                "We were unable to update the mailbox password. Please try again.",
                status_code=http_status_for_openprovider_error(str(exc)),
            ) from exc

        addons = self._read_addons_json(order)
        addons.pop("mailbox_passwords", None)
        self._write_addons_json(order, addons)
        await self._orders.save(order)
        await self._session.commit()
        return await self.get_order_detail(order_id, buyer=buyer, sync=False)

    # ── Domain Restore / EasyDMARC / SpamExperts addons ───────────────────────

    async def get_restore_addon_quote(
        self,
        order_id: uuid.UUID,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        from app.integrations.openprovider.client import get_domain_price
        from app.service.domain import domain_commission_config as commission

        order = await self.get_order(order_id, buyer=buyer)
        name = (order.domain_name or "").strip().lower()
        ext = (order.domain_extension or "").strip().lower().lstrip(".")
        try:
            raw = await get_domain_price(name, ext, operation="restore", period=1)
        except RuntimeError as exc:
            raise AppException(
                "Restore pricing is unavailable for this domain (it may not be in redemption).",
                status_code=http_status_for_openprovider_error(str(exc)),
            ) from exc
        price_block = raw.get("price") if isinstance(raw, dict) else {}
        reseller = (price_block or {}).get("reseller") if isinstance(price_block, dict) else {}
        product = (price_block or {}).get("product") if isinstance(price_block, dict) else {}
        amount = None
        currency = "INR"
        if isinstance(reseller, dict) and reseller.get("price") is not None:
            amount = float(reseller["price"])
            currency = str(reseller.get("currency") or "INR").upper()
        elif isinstance(product, dict) and product.get("price") is not None:
            amount = float(product["price"])
            currency = str(product.get("currency") or "INR").upper()
        if amount is None or amount <= 0:
            raise AppException("No restore price returned for this domain.", status_code=404)
        priced = commission.calculate_customer_price(
            amount,
            service=commission.CommissionService.RESTORE,
            currency=currency,
            tld=f".{ext}" if ext else None,
        )
        unit_inr = float(priced["customerUnitInr"])
        pricing = domain_price_breakdown(unit_inr, years=1)
        return {
            "registrationOrderId": str(order_id),
            "domain": order.fqdn,
            "providerUnitInr": priced["providerUnitInr"],
            "commissionRate": priced["commissionRate"],
            "unitPriceInr": unit_inr,
            **pricing,
        }

    async def create_restore_addon_payment_order(
        self,
        order_id: uuid.UUID,
        body: dict[str, Any] | None = None,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        if not rzp.is_configured():
            raise AppException("Payment gateway is not configured.", status_code=503)
        order = await self.get_order(order_id, buyer=buyer)
        if not order.open_provider_domain_id or str(order.open_provider_domain_id).startswith("DEMO-"):
            raise AppException(
                "Domain restore requires an OpenProvider domain id on this order.",
                status_code=400,
            )
        quote = await self.get_restore_addon_quote(order_id, buyer=buyer)
        rzp_order = rzp.create_order(
            amount_inr=quote["totalInr"],
            receipt=f"drest_{order.domain_name}_{int(datetime.now(timezone.utc).timestamp())}",
            notes={"type": "domain_restore_addon", "orderId": str(order.id)},
        )
        await self._set_pending_addon_payment(
            order,
            addon_type="restore",
            razorpay_order_id=rzp_order["id"],
            amount_inr=quote["totalInr"],
            payload={},
        )
        await self._orders.save(order)
        await self._session.commit()
        return {
            "orderId": rzp_order["id"],
            "amount": quote["totalInr"],
            "amountSmallest": int(round(float(quote["totalInr"]) * 100)),
            "currency": "INR",
            "keyId": rzp.get_key_id(),
            "registrationOrderId": str(order.id),
            **quote,
        }

    async def verify_restore_addon_payment(
        self,
        order_id: uuid.UUID,
        payload: dict[str, str],
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        order = await self.get_order(order_id, buyer=buyer)
        pending = await self._consume_verified_pending_addon(
            order, payload, expected_type="restore"
        )
        try:
            detail = await self.add_restore_addon(
                order_id, buyer=buyer, _payment_verified=True
            )
        except Exception:
            logger.exception(
                "restore addon provision failed after payment order=%s payment=%s",
                order_id,
                pending.get("razorpayPaymentId"),
            )
            raise
        order = await self.get_order(order_id, buyer=buyer)
        await self._finalize_pending_addon_after_success(order, expected_type="restore")
        await self._orders.save(order)
        await self._session.commit()
        return detail

    async def add_restore_addon(
        self,
        order_id: uuid.UUID,
        *,
        buyer: AppUser,
        _payment_verified: bool = False,
    ) -> dict[str, Any]:
        if not _payment_verified:
            raise AppException(
                "Domain restore requires payment. Use the restore payment checkout flow.",
                status_code=402,
            )
        from app.integrations.openprovider.client import restore_domain

        order = await self.get_order(order_id, buyer=buyer)
        op_id = order.open_provider_domain_id
        if not op_id or str(op_id).startswith("DEMO-"):
            raise AppException("Missing OpenProvider domain id.", status_code=400)

        addons_existing = self._read_addons_json(order)
        prior = addons_existing.get("restore")
        if isinstance(prior, dict) and prior.get("opDomainId"):
            logger.info(
                "restore.addon.idempotent_hit order=%s opDomainId=%s",
                order_id,
                prior.get("opDomainId"),
            )
            detail = await self.get_order_detail(order_id, buyer=buyer, sync=False)
            detail["restoreProvisioned"] = prior
            return detail

        name = (order.domain_name or "").strip().lower()
        ext = (order.domain_extension or "").strip().lower().lstrip(".")
        try:
            result = await restore_domain(op_id, name=name, extension_no_dot=ext)
        except RuntimeError as exc:
            logger.exception(
                "restore.addon.op_failed order=%s opDomainId=%s",
                order_id,
                op_id,
            )
            raise AppException(
                "We were unable to restore this domain with the registrar. "
                "Your payment was received — contact support if status does not update.",
                status_code=http_status_for_openprovider_error(str(exc)),
            ) from exc
        addons = self._read_addons_json(order)
        addons["restore"] = {
            "status": str((result or {}).get("status") or "requested"),
            "restoredAt": datetime.now(timezone.utc).isoformat(),
            "opDomainId": str(op_id),
        }
        self._write_addons_json(order, addons)
        await self._orders.save(order)
        await self._session.commit()
        detail = await self.get_order_detail(order_id, buyer=buyer, sync=False)
        detail["restoreProvisioned"] = addons["restore"]
        return detail

    async def get_easydmarc_addon_quote(
        self,
        order_id: uuid.UUID,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        await self.get_order(order_id, buyer=buyer)
        prices = await self._service_price_catalog()
        unit_inr = float(prices.get("easydmarc", {}).get("unitInr") or 499.0)
        pricing = domain_price_breakdown(unit_inr, years=1)
        return {
            "registrationOrderId": str(order_id),
            "unitPriceInr": unit_inr,
            **pricing,
        }

    async def create_easydmarc_addon_payment_order(
        self,
        order_id: uuid.UUID,
        body: dict[str, Any] | None = None,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        if not rzp.is_configured():
            raise AppException("Payment gateway is not configured.", status_code=503)
        order = await self.get_order(order_id, buyer=buyer)
        quote = await self.get_easydmarc_addon_quote(order_id, buyer=buyer)
        rzp_order = rzp.create_order(
            amount_inr=quote["totalInr"],
            receipt=f"ddmarc_{order.domain_name}_{int(datetime.now(timezone.utc).timestamp())}",
            notes={"type": "domain_easydmarc_addon", "orderId": str(order.id)},
        )
        await self._set_pending_addon_payment(
            order,
            addon_type="easydmarc",
            razorpay_order_id=rzp_order["id"],
            amount_inr=quote["totalInr"],
            payload={},
        )
        await self._orders.save(order)
        await self._session.commit()
        return {
            "orderId": rzp_order["id"],
            "amount": quote["totalInr"],
            "amountSmallest": int(round(float(quote["totalInr"]) * 100)),
            "currency": "INR",
            "keyId": rzp.get_key_id(),
            "registrationOrderId": str(order.id),
            **quote,
        }

    async def verify_easydmarc_addon_payment(
        self,
        order_id: uuid.UUID,
        payload: dict[str, str],
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        order = await self.get_order(order_id, buyer=buyer)
        pending = await self._consume_verified_pending_addon(
            order, payload, expected_type="easydmarc"
        )
        try:
            detail = await self.add_easydmarc_addon(
                order_id, buyer=buyer, _payment_verified=True
            )
        except Exception:
            logger.exception(
                "easydmarc addon provision failed after payment order=%s payment=%s",
                order_id,
                pending.get("razorpayPaymentId"),
            )
            raise
        order = await self.get_order(order_id, buyer=buyer)
        await self._finalize_pending_addon_after_success(order, expected_type="easydmarc")
        await self._orders.save(order)
        await self._session.commit()
        return detail

    async def add_easydmarc_addon(
        self,
        order_id: uuid.UUID,
        *,
        buyer: AppUser,
        _payment_verified: bool = False,
    ) -> dict[str, Any]:
        if not _payment_verified:
            raise AppException(
                "EasyDMARC requires payment. Use the EasyDMARC payment checkout flow.",
                status_code=402,
            )
        from app.integrations.openprovider.client import (
            easydmarc_create,
            easydmarc_get,
            easydmarc_sso_url,
        )

        order = await self.get_order(order_id, buyer=buyer)
        handle = (order.open_provider_handle or "").strip()
        if not handle or handle.startswith("DEMO-"):
            raise AppException(
                "Cannot provision EasyDMARC without a registrar contact handle.",
                status_code=400,
            )

        addons_existing = self._read_addons_json(order)
        prior = addons_existing.get("easydmarc")
        if isinstance(prior, dict) and prior.get("opOrderId") is not None:
            logger.info(
                "easydmarc.addon.idempotent_hit order=%s opOrderId=%s",
                order_id,
                prior.get("opOrderId"),
            )
            if not prior.get("ssoUrl"):
                try:
                    prior["ssoUrl"] = await easydmarc_sso_url(int(prior["opOrderId"]))
                    addons_existing["easydmarc"] = prior
                    self._write_addons_json(order, addons_existing)
                    await self._orders.save(order)
                    await self._session.commit()
                except Exception as exc:
                    logger.warning("easydmarc.addon.sso_refresh_failed order=%s: %s", order_id, exc)
            detail = await self.get_order_detail(order_id, buyer=buyer, sync=False)
            detail["easydmarcProvisioned"] = prior
            return detail

        name = (order.domain_name or "").strip().lower()
        ext = (order.domain_extension or "").strip().lower().lstrip(".")
        try:
            created = await easydmarc_create(
                name=name, extension_no_dot=ext, owner_handle=handle
            )
        except RuntimeError as exc:
            logger.exception("easydmarc.addon.create_failed order=%s", order_id)
            raise AppException(
                "We were unable to create EasyDMARC for this domain. "
                "Your payment was received — contact support if it does not appear.",
                status_code=http_status_for_openprovider_error(str(exc)),
            ) from exc
        op_id = created.get("id")
        record_host = str(created.get("record_host") or "")
        record_type = str(created.get("record_type") or "")
        record_value = str(created.get("record_value") or "")
        easydmarc_email = str(created.get("easydmarc_email_address") or "")
        if op_id is not None and (not record_host or not record_value):
            try:
                fetched = await easydmarc_get(int(op_id))
                if isinstance(fetched, dict):
                    record_host = record_host or str(fetched.get("record_host") or "")
                    record_type = record_type or str(fetched.get("record_type") or "")
                    record_value = record_value or str(fetched.get("record_value") or "")
                    easydmarc_email = easydmarc_email or str(
                        fetched.get("easydmarc_email_address") or ""
                    )
                    logger.info(
                        "easydmarc.addon.dns_filled_from_get order=%s opOrderId=%s",
                        order_id,
                        op_id,
                    )
            except Exception as exc:
                logger.warning(
                    "easydmarc.addon.get_fallback_failed order=%s opOrderId=%s: %s",
                    order_id,
                    op_id,
                    exc,
                )
        sso = ""
        if op_id is not None:
            try:
                sso = await easydmarc_sso_url(int(op_id))
            except Exception as exc:
                logger.warning("EasyDMARC SSO fetch failed order=%s: %s", order_id, exc)
        record = {
            "opOrderId": int(op_id) if op_id is not None else None,
            "status": str(created.get("status") or "active"),
            "recordHost": record_host,
            "recordType": record_type,
            "recordValue": record_value,
            "easydmarcEmail": easydmarc_email,
            "ssoUrl": sso,
            "provisionedAt": datetime.now(timezone.utc).isoformat(),
        }
        addons = self._read_addons_json(order)
        addons["easydmarc"] = record
        self._write_addons_json(order, addons)
        await self._orders.save(order)
        await self._session.commit()
        detail = await self.get_order_detail(order_id, buyer=buyer, sync=False)
        detail["easydmarcProvisioned"] = record
        return detail

    async def get_spamexperts_addon_quote(
        self,
        order_id: uuid.UUID,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        await self.get_order(order_id, buyer=buyer)
        prices = await self._service_price_catalog()
        unit_inr = float(prices.get("spamexperts", {}).get("unitInr") or 299.0)
        pricing = domain_price_breakdown(unit_inr, years=1)
        return {
            "registrationOrderId": str(order_id),
            "unitPriceInr": unit_inr,
            **pricing,
        }

    async def create_spamexperts_addon_payment_order(
        self,
        order_id: uuid.UUID,
        body: dict[str, Any] | None = None,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        if not rzp.is_configured():
            raise AppException("Payment gateway is not configured.", status_code=503)
        order = await self.get_order(order_id, buyer=buyer)
        quote = await self.get_spamexperts_addon_quote(order_id, buyer=buyer)
        rzp_order = rzp.create_order(
            amount_inr=quote["totalInr"],
            receipt=f"dspam_{order.domain_name}_{int(datetime.now(timezone.utc).timestamp())}",
            notes={"type": "domain_spamexperts_addon", "orderId": str(order.id)},
        )
        dest_host = ""
        if isinstance(body, dict):
            dest_host = str(body.get("destinationHost") or body.get("destination") or "").strip()
        await self._set_pending_addon_payment(
            order,
            addon_type="spamexperts",
            razorpay_order_id=rzp_order["id"],
            amount_inr=quote["totalInr"],
            payload={"destinationHost": dest_host},
        )
        await self._orders.save(order)
        await self._session.commit()
        return {
            "orderId": rzp_order["id"],
            "amount": quote["totalInr"],
            "amountSmallest": int(round(float(quote["totalInr"]) * 100)),
            "currency": "INR",
            "keyId": rzp.get_key_id(),
            "registrationOrderId": str(order.id),
            **quote,
        }

    async def verify_spamexperts_addon_payment(
        self,
        order_id: uuid.UUID,
        payload: dict[str, str],
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        order = await self.get_order(order_id, buyer=buyer)
        pending = await self._consume_verified_pending_addon(
            order, payload, expected_type="spamexperts"
        )
        pending_payload = dict(pending.get("payload") or {})
        try:
            detail = await self.add_spamexperts_addon(
                order_id,
                buyer=buyer,
                _payment_verified=True,
                pending_payload=pending_payload,
            )
        except Exception:
            logger.exception(
                "spamexperts addon provision failed after payment order=%s payment=%s",
                order_id,
                pending.get("razorpayPaymentId"),
            )
            raise
        order = await self.get_order(order_id, buyer=buyer)
        await self._finalize_pending_addon_after_success(order, expected_type="spamexperts")
        await self._orders.save(order)
        await self._session.commit()
        return detail

    async def add_spamexperts_addon(
        self,
        order_id: uuid.UUID,
        *,
        buyer: AppUser,
        _payment_verified: bool = False,
        pending_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not _payment_verified:
            raise AppException(
                "SpamExperts requires payment. Use the SpamExperts payment checkout flow.",
                status_code=402,
            )
        from app.integrations.openprovider.client import (
            spam_expert_create_domain,
            spam_expert_generate_login_url,
        )

        order = await self.get_order(order_id, buyer=buyer)
        payload = dict(pending_payload or {})
        dest_host = str(payload.get("destinationHost") or "").strip() or f"mail.{order.fqdn}"

        addons_existing = self._read_addons_json(order)
        prior = addons_existing.get("spamexperts")
        if isinstance(prior, dict) and (
            prior.get("loginUrl") or prior.get("providerData") or prior.get("status") == "active"
        ):
            logger.info(
                "spamexperts.addon.idempotent_hit order=%s domain=%s",
                order_id,
                order.fqdn,
            )
            if not prior.get("mxRecords"):
                prior["mxRecords"] = list(SPAMEXPERTS_MX_RECORDS)
                addons_existing["spamexperts"] = prior
                self._write_addons_json(order, addons_existing)
                await self._orders.save(order)
                await self._session.commit()
            detail = await self.get_order_detail(order_id, buyer=buyer, sync=False)
            detail["spamexpertsProvisioned"] = prior
            return detail

        try:
            created = await spam_expert_create_domain(
                domain_name=order.fqdn,
                destinations=[{"hostname": dest_host, "port": 25}],
                products={"incoming": True, "outgoing": False, "archiving": False},
                bundle=False,
            )
            login_url = await spam_expert_generate_login_url(
                domain_or_email=order.fqdn,
                bundle=False,
            )
        except RuntimeError as exc:
            logger.exception("spamexperts.addon.op_failed order=%s domain=%s", order_id, order.fqdn)
            raise AppException(
                "We were unable to activate SpamExperts for this domain. "
                "Your payment was received — contact support if the filter does not appear.",
                status_code=http_status_for_openprovider_error(str(exc)),
            ) from exc
        record = {
            "status": "active",
            "destinationHost": dest_host,
            "mxRecords": list(SPAMEXPERTS_MX_RECORDS),
            "loginUrl": login_url,
            "providerData": created if isinstance(created, dict) else {},
            "provisionedAt": datetime.now(timezone.utc).isoformat(),
        }
        addons = self._read_addons_json(order)
        addons["spamexperts"] = record
        self._write_addons_json(order, addons)
        await self._orders.save(order)
        await self._session.commit()
        detail = await self.get_order_detail(order_id, buyer=buyer, sync=False)
        detail["spamexpertsProvisioned"] = record
        return detail




