"""
Optional live registration test (sandbox). Charges demo reseller balance.

Run only when explicitly enabled:
  set RESELLERCLUB_RUN_REGISTER_E2E=1
  python scripts/test_resellerclub_register_e2e.py
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.integrations.resellerclub import client as rc  # noqa: E402


async def main() -> int:
    if os.environ.get("RESELLERCLUB_RUN_REGISTER_E2E") != "1":
        print("Set RESELLERCLUB_RUN_REGISTER_E2E=1 to run live registration (uses demo balance).")
        return 0

    if not rc.is_configured():
        print("ResellerClub not configured.")
        return 1

    label = f"cobre2e{secrets.token_hex(4)}"
    fqdn = f"{label}.com"
    print("Testing registration for", fqdn)

    check = await rc.check_domain(label, "com")
    if not rc.is_free(check):
        print("Domain not available:", check)
        return 1

    contact = {
        "name": {"first_name": "CoBrother", "last_name": "E2E", "full_name": "CoBrother E2E"},
        "email": "cobrother.registrar.test@gmail.com",
        "phone": {"subscriber_number": "9876543210"},
        "address": {
            "street": "1 Test Street",
            "city": "Hubli",
            "state": "Karnataka",
            "zipcode": "580021",
            "country": "IN",
        },
    }
    handle = await rc.create_customer(contact)
    print("handle:", handle)

    reg = await rc.register_domain(label, "com", handle, 1, contact=contact)
    print("register:", json.dumps(reg, indent=2, default=str))

    order_id = reg.get("id")
    if not order_id:
        print("No order id in response.")
        return 1

    details = await rc.get_domain_order_details(str(order_id))
    print("details:", json.dumps(details, indent=2, default=str)[:3000])
    print("active:", rc.is_order_active(details))
    print("panel:", rc.control_panel_url())
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
