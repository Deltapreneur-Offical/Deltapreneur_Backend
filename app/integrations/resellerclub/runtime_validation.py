"""ResellerClub sandbox vs live runtime checks (env, API host, NS, invoice, Razorpay)."""

from __future__ import annotations

from app.core.config import settings


_DEMO_NS_MARKERS = ("onlyfordemo.net",)
_ALLOWED_INVOICE_LIVE = frozenset({"noinvoice"})
_ALLOWED_INVOICE_SANDBOX = frozenset({"noinvoice", "keepinvoice", "payinvoice", "onlyadd"})


def effective_invoice_option() -> str:
    """Live always uses NoInvoice (CoBrother collects payment first)."""
    raw = (settings.RESELLERCLUB_INVOICE_OPTION or "NoInvoice").strip()
    if not settings.resellerclub_use_sandbox():
        return "NoInvoice"
    code = raw or "NoInvoice"
    if code.lower() not in _ALLOWED_INVOICE_SANDBOX:
        return "NoInvoice"
    return code


def list_default_nameserver_hosts() -> list[str]:
    """Mirror client._default_nameservers without circular imports."""
    return settings.resolved_resellerclub_default_nameservers()


def validate_resellerclub_runtime(*, for_live_checkout: bool = False) -> dict:
    """
    Validate active ResellerClub profile matches RESELLERCLUB_ENV.

    When ``for_live_checkout`` is True, apply stricter rules for real-money registration.
    """
    profile = settings.resellerclub_runtime_profile()
    sandbox = bool(profile["sandbox"])
    blocking: list[str] = []
    warnings: list[str] = []

    if not settings.RESELLERCLUB_ENABLED:
        blocking.append("RESELLERCLUB_ENABLED=false.")
    if not profile["configured"]:
        blocking.append(
            "ResellerClub credentials missing (RESELLERCLUB_RESELLER_ID and RESELLERCLUB_API_KEY).",
        )

    api_base = str(profile["apiBaseUrl"]).lower()
    if sandbox:
        if "test.httpapi" not in api_base:
            blocking.append(
                f"RESELLERCLUB_ENV=sandbox but API base is {profile['apiBaseUrl']}. "
                "Use https://test.httpapi.com with demo panel credentials.",
            )
    else:
        if "test.httpapi" in api_base:
            blocking.append(
                "RESELLERCLUB_ENV=live but API base points to test.httpapi.com. "
                "Remove conflicting RESELLERCLUB_API_BASE_URL or set RESELLERCLUB_ENV=live correctly.",
            )
        if "httpapi.com" not in api_base:
            blocking.append(f"Live mode requires https://httpapi.com (got {profile['apiBaseUrl']}).")

    custom_base = settings._resellerclub_custom_api_base()
    if custom_base and not settings._resellerclub_host_matches_env(
        custom_base,
        sandbox=sandbox,
    ):
        warnings.append(
            f"RESELLERCLUB_API_BASE_URL ({custom_base}) ignored — does not match "
            f"RESELLERCLUB_ENV={'sandbox' if sandbox else 'live'}.",
        )

    invoice_raw = (settings.RESELLERCLUB_INVOICE_OPTION or "").strip()
    invoice_eff = effective_invoice_option()
    if not sandbox:
        if invoice_raw.lower() != "noinvoice":
            warnings.append(
                f"RESELLERCLUB_INVOICE_OPTION={invoice_raw!r} overridden to NoInvoice in live mode "
                "(customer already pays via CoBrother/Razorpay).",
            )
    elif invoice_raw.lower() == "keepinvoice":
        warnings.append(
            "RESELLERCLUB_INVOICE_OPTION=KeepInvoice leaves unpaid invoices in the ResellerClub panel "
            "after Razorpay payment. Use NoInvoice for normal storefront flow.",
        )

    nameservers = list_default_nameserver_hosts()
    if len(nameservers) < 2:
        if sandbox:
            warnings.append(
                "No custom nameservers in env — using ResellerClub demo defaults "
                "(ns1.onlyfordemo.net, ns2.onlyfordemo.net).",
            )
        else:
            blocking.append(
                "Live registration requires two nameservers: set RESELLERCLUB_DEFAULT_NAMESERVERS "
                "or RESELLERCLUB_DEFAULT_NS1/NS2 (not onlyfordemo.net).",
            )
    elif sandbox and not settings.RESELLERCLUB_FETCH_NAMESERVERS_FROM_API:
        for ns in nameservers:
            if not any(marker in ns.lower() for marker in _DEMO_NS_MARKERS):
                warnings.append(
                    f"Sandbox .env nameserver {ns!r} may be rejected by ResellerClub. "
                    "Prefer RESELLERCLUB_FETCH_NAMESERVERS_FROM_API=true (default) to use panel defaults.",
                )
                break
    elif sandbox and settings.RESELLERCLUB_FETCH_NAMESERVERS_FROM_API:
        warnings.append(
            "Sandbox: registration nameservers are fetched per customer from "
            "domains/customer-default-ns.json (ResellerClub panel defaults).",
        )
    elif not sandbox:
        for ns in nameservers:
            lower = ns.lower()
            if any(marker in lower for marker in _DEMO_NS_MARKERS):
                blocking.append(
                    f"Live mode cannot use demo nameserver {ns!r}. "
                    "Set production DNS hosts in RESELLERCLUB_DEFAULT_NAMESERVERS.",
                )
                break

    if settings.domain_registrar() == "resellerclub" and settings.DOMAIN_STOREFRONT_DEMO_FALLBACK:
        blocking.append(
            "DOMAIN_STOREFRONT_DEMO_FALLBACK=true simulates registration — "
            "must be false when using real ResellerClub API.",
        )

    if for_live_checkout or not sandbox:
        rzp_key = settings.resolved_razorpay_key_id()
        if rzp_key.startswith("rzp_test_"):
            blocking.append(
                "Razorpay test keys (rzp_test_*) cannot be used with RESELLERCLUB_ENV=live. "
                "Set RAZORPAY_LIVE_KEY_ID=rzp_live_* (or RAZORPAY_KEY_ID) for real payments.",
            )
        if not settings.resolved_razorpay_webhook_secret():
            warnings.append(
                "RAZORPAY_WEBHOOK_SECRET not set — checkout uses payment verify only. "
                "Add a webhook secret in production so registration still runs if the user "
                "closes the browser before verify completes.",
            )
        if not settings.resolved_razorpay_key_id() or not settings.resolved_razorpay_key_secret():
            blocking.append("Razorpay KEY_ID / KEY_SECRET missing.")

    if sandbox and for_live_checkout:
        blocking.append(
            "Cannot run live-money checkout while RESELLERCLUB_ENV=sandbox. "
            "Set RESELLERCLUB_ENV=live with live credentials.",
        )

    frontend = settings.FRONTEND_BASE_URL.strip()
    if not sandbox and ("localhost" in frontend or "127.0.0.1" in frontend):
        warnings.append(
            f"FRONTEND_BASE_URL={frontend} — use https://cobrother.com in production.",
        )

    return {
        "profile": profile,
        "sandbox": sandbox,
        "invoiceOptionEffective": invoice_eff,
        "nameservers": nameservers,
        "ready": len(blocking) == 0,
        "blockingIssues": blocking,
        "warnings": warnings,
    }
