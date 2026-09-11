"""Read-only audit for technology subscription confirmation-email state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import engine  # noqa: E402
from app.utils.email_mask import mask_email  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit technology confirmation email state")
    parser.add_argument("--service-slug", default="cloud-storage")
    parser.add_argument("--unsent-only", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    where_sql = "ts.confirmation_sent = false" if args.unsent_only else (
        "lower(coalesce(ts.service_slug, '')) = lower(:service_slug) or ts.confirmation_sent = false"
    )
    query = text(
        f"""
        select
          ts.id::text as id,
          ts.service_slug,
          ts.service_name,
          ts.status,
          ts.payment_status,
          ts.confirmation_sent,
          ts.email_sent,
          ts.provider_order_id is not null as has_provider_order_id,
          ts.provider_subscription_id is not null as has_provider_subscription_id,
          ts.next_retry_at::text as next_retry_at,
          ts.created_at::text as created_at,
          u.email as recipient_email
        from technology_subscriptions ts
        left join users u on u.id::text = ts.user_id
        where {where_sql}
        order by ts.created_at desc
        limit :limit
        """
    )

    rows: list[dict[str, object]] = []
    with engine.connect() as conn:
        for row in conn.execute(query, {"service_slug": args.service_slug, "limit": args.limit}):
            data = dict(row._mapping)
            recipient_email = str(data.pop("recipient_email") or "")
            data["recipient"] = mask_email(recipient_email)
            rows.append(data)

    print(json.dumps(rows, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
