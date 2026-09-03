"""Live ResellerClub API smoke test (reads credentials from .env). No domain registration."""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.integrations.resellerclub import client as rc  # noqa: E402


def _redact(obj: object) -> object:
    if isinstance(obj, dict):
        return {k: _redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


async def main() -> int:
    print("registrar:", settings.domain_registrar())
    print("configured:", rc.is_configured())
    print("sandbox:", rc.is_sandbox())
    print("api_base:", settings.resolved_resellerclub_api_base())
    print("domaincheck:", settings.resolved_resellerclub_domaincheck_base())
    print("demo_fallback:", settings.domain_storefront_demo_fallback())

    if not rc.is_configured():
        print("ERROR: ResellerClub credentials missing in environment.")
        return 1

    label = f"cobrlivetest{secrets.token_hex(3)}"
    fqdn = f"{label}.com"
    print("\n--- availability ---")
    check = await rc.check_domain(label, "com")
    print(json.dumps(_redact(check), indent=2))

    print("\n--- live price (domorder) ---")
    quote = await rc.get_create_price(label, "com")
    unit, currency, source = rc.extract_create_price_details(quote)
    print(json.dumps(_redact(quote), indent=2))
    print(f"unit_price={unit} {currency} source={source}")

    print("\n--- reseller details ---")
    details = await rc.get_reseller_details()
    print(json.dumps(_redact(details), indent=2)[:2000])

    print("\nOK: live availability and pricing succeeded for", fqdn)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
