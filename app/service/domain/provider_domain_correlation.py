"""Verify that an OpenProvider domain may be linked to one paid registration order.

Never infer ownership from a buyer's other DomainRegistrationOrder rows.
Correlate only this order's FQDN, Razorpay ids, registrant email/handle, and
whether another local order already stores the same provider domain id.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def normalize_email(value: str | None) -> str:
    return str(value or "").strip().lower()


def normalize_fqdn(value: str | None) -> str:
    return str(value or "").strip().lower().rstrip(".")


def fqdn_from_provider_details(details: dict[str, Any] | None) -> str | None:
    if not isinstance(details, dict):
        return None
    domain = details.get("domain")
    if isinstance(domain, dict):
        name = str(domain.get("name") or "").strip()
        ext = str(domain.get("extension") or "").strip().lstrip(".")
        if name and ext:
            return f"{name}.{ext}".lower()
    name = str(details.get("name") or "").strip()
    ext = str(details.get("extension") or "").strip().lstrip(".")
    if name and ext:
        return f"{name}.{ext}".lower()
    return None


def owner_handle_from_provider_details(details: dict[str, Any] | None) -> str | None:
    if not isinstance(details, dict):
        return None
    for key in ("owner_handle", "ownerHandle"):
        handle = str(details.get(key) or "").strip()
        if handle:
            return handle
    owner = details.get("owner")
    if isinstance(owner, dict):
        handle = str(owner.get("handle") or owner.get("owner_handle") or "").strip()
        if handle:
            return handle
    return None


def emails_from_provider_details(details: dict[str, Any] | None) -> set[str]:
    found: set[str] = set()
    if not isinstance(details, dict):
        return found
    for key in ("email", "owner_email", "verification_email_name"):
        raw = details.get(key)
        email = normalize_email(raw if isinstance(raw, str) else None)
        if email and "@" in email:
            found.add(email)
    owner = details.get("owner")
    if isinstance(owner, dict):
        email = normalize_email(owner.get("email") if isinstance(owner.get("email"), str) else None)
        if email and "@" in email:
            found.add(email)
    for key in ("verification_email", "email_verification", "owner_email_verification"):
        block = details.get(key)
        if isinstance(block, dict):
            email = normalize_email(block.get("email") if isinstance(block.get("email"), str) else None)
            if email and "@" in email:
                found.add(email)
        elif isinstance(block, str):
            email = normalize_email(block)
            if email and "@" in email:
                found.add(email)
    return found


def email_from_customer_payload(data: dict[str, Any] | None) -> str:
    if not isinstance(data, dict):
        return ""
    email = normalize_email(data.get("email") if isinstance(data.get("email"), str) else None)
    if email:
        return email
    for nested_key in ("identity", "address", "additional_data"):
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            email = normalize_email(nested.get("email") if isinstance(nested.get("email"), str) else None)
            if email:
                return email
    return ""


@dataclass(frozen=True)
class ProviderLinkDecision:
    action: str
    reason: str
    provider_domain_id: str | None = None


def decide_provider_link(
    *,
    paid: bool,
    order_fqdn: str,
    order_email: str | None,
    order_handle: str | None,
    order_already_has_provider_id: str | None,
    provider_domain_id: str | None,
    other_order_ids_with_provider_id: list[str],
    details: dict[str, Any] | None,
    provider_owner_email: str | None,
) -> ProviderLinkDecision:
    """Pure correlation rules used by provision_order.

    action is one of: reconcile | attention | skip
    """
    pid = str(provider_domain_id or "").strip() or None
    if not paid:
        return ProviderLinkDecision(action="skip", reason="UNPAID_DO_NOT_ADOPT", provider_domain_id=pid)
    if not pid:
        return ProviderLinkDecision(action="skip", reason="NO_PROVIDER_ID", provider_domain_id=None)

    others = [oid for oid in other_order_ids_with_provider_id if oid]
    if others:
        return ProviderLinkDecision(
            action="attention",
            reason="UNRELATED_ORDER_OWNS_PROVIDER_DOMAIN",
            provider_domain_id=pid,
        )

    provider_fqdn = fqdn_from_provider_details(details)
    if not provider_fqdn:
        return ProviderLinkDecision(
            action="attention",
            reason="PROVIDER_DETAILS_MISSING_FQDN",
            provider_domain_id=pid,
        )
    if normalize_fqdn(provider_fqdn) != normalize_fqdn(order_fqdn):
        return ProviderLinkDecision(
            action="attention",
            reason="PROVIDER_FQDN_MISMATCH",
            provider_domain_id=pid,
        )

    existing = str(order_already_has_provider_id or "").strip()
    if existing and existing == pid:
        return ProviderLinkDecision(
            action="reconcile",
            reason="ALREADY_LINKED_TO_THIS_ORDER",
            provider_domain_id=pid,
        )

    order_handle_n = str(order_handle or "").strip()
    provider_handle = owner_handle_from_provider_details(details) or ""
    if order_handle_n and provider_handle and order_handle_n.lower() == provider_handle.lower():
        return ProviderLinkDecision(
            action="reconcile",
            reason="PROVIDER_HANDLE_MATCHES_THIS_ORDER",
            provider_domain_id=pid,
        )

    wanted = normalize_email(order_email)
    emails = emails_from_provider_details(details)
    provider_email = normalize_email(provider_owner_email)
    if provider_email:
        emails.add(provider_email)
    if wanted and wanted in emails:
        return ProviderLinkDecision(
            action="reconcile",
            reason="PROVIDER_EMAIL_MATCHES_THIS_ORDER",
            provider_domain_id=pid,
        )

    return ProviderLinkDecision(
        action="attention",
        reason="INSUFFICIENT_CORRELATION",
        provider_domain_id=pid,
    )
