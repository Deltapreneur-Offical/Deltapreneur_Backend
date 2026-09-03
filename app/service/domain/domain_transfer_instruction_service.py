"""Registrar-specific self-transfer instructions (Path A)."""

from __future__ import annotations

from typing import Any


_REGISTRAR_STEPS: dict[str, list[str]] = {
    "godaddy": [
        "Log in to GoDaddy.",
        "Open Domains.",
        "Select Transfer Domain.",
        "Enter the domain name.",
        "Enter the authorization code when prompted.",
        "Complete transfer checkout.",
        "When the domain appears in your account, confirm transfer completion in HubRegistrar.",
    ],
    "namecheap": [
        "Log in to Namecheap.",
        "Go to Domain List → Transfer → Transfer a domain in.",
        "Enter the domain name.",
        "Enter the authorization code when prompted.",
        "Pay the transfer fee if required and confirm.",
        "When the domain appears in your account, confirm transfer completion in HubRegistrar.",
    ],
    "hostinger": [
        "Log in to Hostinger.",
        "Open Domains.",
        "Choose Transfer domain.",
        "Enter the domain name.",
        "Enter the authorization code when prompted.",
        "Complete the transfer steps and approve any confirmation emails.",
        "Confirm transfer completion in HubRegistrar once the domain is in your account.",
    ],
    "cloudflare": [
        "Log in to the Cloudflare dashboard.",
        "Go to Domain Registration → Transfer.",
        "Enter the domain name.",
        "Enter the authorization code when prompted.",
        "Follow Cloudflare's transfer wizard to approve.",
        "Confirm transfer completion in HubRegistrar once the domain is active.",
    ],
    "dynadot": [
        "Log in to Dynadot.",
        "Open Transfer Domain.",
        "Enter the domain name.",
        "Enter the authorization code when prompted.",
        "Complete checkout and approve transfer emails if required.",
        "Confirm transfer completion in HubRegistrar once the domain is in your account.",
    ],
    "porkbun": [
        "Log in to Porkbun.",
        "Open Transfer.",
        "Enter the domain name.",
        "Enter the authorization code when prompted.",
        "Complete the transfer checkout.",
        "Confirm transfer completion in HubRegistrar once the domain is in your account.",
    ],
    "name.com": [
        "Log in to Name.com.",
        "Open Transfer a Domain.",
        "Enter the domain name.",
        "Enter the authorization code when prompted.",
        "Complete the transfer process.",
        "Confirm transfer completion in HubRegistrar once the domain is in your account.",
    ],
    "default": [
        "Sign in to your registrar's control panel.",
        "Find Transfer domain in or Import domain.",
        "Enter the domain name and paste the auth (EPP) code from HubRegistrar.",
        "Approve any confirmation emails from your registrar.",
        "When the domain is in your account, confirm transfer completion in HubRegistrar.",
    ],
}

_REGISTRAR_KEYS = (
    "godaddy",
    "namecheap",
    "hostinger",
    "cloudflare",
    "dynadot",
    "porkbun",
    "name.com",
)


def normalize_registrar_key(name: str) -> str:
    n = (name or "").strip().lower()
    for key in _REGISTRAR_KEYS:
        if key in n:
            return key
    return "default"


def detect_registrar_from_text(text: str) -> str | None:
    lowered = (text or "").lower()
    for key in _REGISTRAR_KEYS:
        if key.replace(".", "") in lowered.replace(".", " ") or key in lowered:
            return key
    return None


def get_transfer_instructions(registrar_name: str) -> dict[str, Any]:
    key = normalize_registrar_key(registrar_name)
    return {
        "registrar": registrar_name,
        "registrarKey": key,
        "steps": _REGISTRAR_STEPS.get(key, _REGISTRAR_STEPS["default"]),
    }
