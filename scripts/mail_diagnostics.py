"""Run safe backend mail diagnostics.

Usage:
    python scripts/mail_diagnostics.py --config
    python scripts/mail_diagnostics.py --send-test --to someone@example.com

The output never includes SMTP passwords or API keys.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.service.auth.smtp_diagnostics import (  # noqa: E402
    local_runtime_context,
    run_smtp_connectivity_test,
    safe_mail_config_diagnostic,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe Deltapreneur SMTP diagnostics")
    parser.add_argument("--config", action="store_true", help="Print non-secret mail configuration")
    parser.add_argument("--send-test", action="store_true", help="Send one diagnostic email")
    parser.add_argument("--to", default=None, help="Controlled test recipient")
    args = parser.parse_args()

    payload: dict[str, object] = {
        "config": safe_mail_config_diagnostic(),
        "runtime": local_runtime_context(),
    }
    if args.send_test:
        payload["smtp_test"] = run_smtp_connectivity_test(args.to)

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("smtp_test", {"success": True}).get("success", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
