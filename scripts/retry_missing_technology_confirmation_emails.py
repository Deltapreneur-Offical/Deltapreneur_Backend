"""Send missing confirmation emails for active paid technology subscriptions.

Default mode is read-only. Use --apply to send emails and persist
confirmation_sent only after the mail provider accepts the message.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.entity.technology_services.technology_subscription_entity import (  # noqa: E402
    TechnologySubscriptionEntity,
)
from app.entity.user.app_user import AppUser  # noqa: E402
from app.service.platform.track_record_service import PaymentStatus  # noqa: E402
from app.service.technology.technology_subscription_retry_service import (  # noqa: E402
    TechnologySubscriptionRetryService,
)
from app.utils.email_mask import mask_email  # noqa: E402


async def _recipient_for(session, sub: TechnologySubscriptionEntity) -> str:
    try:
        user_result = await session.execute(
            select(AppUser).where(AppUser.id == uuid.UUID(str(sub.user_id)))
        )
        user = user_result.scalar_one_or_none()
        if user is not None and user.email:
            return user.email
    except Exception:
        pass
    return str(sub.user_id)


async def _run(*, apply: bool, limit: int) -> dict[str, object]:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(TechnologySubscriptionEntity)
            .where(
                TechnologySubscriptionEntity.status == "ACTIVE",
                TechnologySubscriptionEntity.payment_status == PaymentStatus.CAPTURED,
                TechnologySubscriptionEntity.confirmation_sent.is_(False),
                TechnologySubscriptionEntity.is_deleted.is_(False),
            )
            .order_by(TechnologySubscriptionEntity.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()

        service = TechnologySubscriptionRetryService(session)
        items: list[dict[str, object]] = []
        for sub in rows:
            recipient = await _recipient_for(session, sub)
            item = {
                "id": str(sub.id),
                "service_slug": sub.service_slug,
                "service_name": sub.service_name,
                "status": sub.status,
                "payment_status": sub.payment_status,
                "confirmation_sent_before": sub.confirmation_sent,
                "recipient": mask_email(recipient),
            }
            if apply:
                outcome = await service._process(sub)
                item["outcome"] = outcome
                item["confirmation_sent_after"] = sub.confirmation_sent
            items.append(item)

        if apply:
            await session.commit()
        else:
            await session.rollback()

    return {
        "apply": apply,
        "count": len(items),
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Retry missing technology confirmation emails")
    parser.add_argument("--apply", action="store_true", help="Actually send emails and commit state")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    payload = asyncio.run(_run(apply=args.apply, limit=args.limit))
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.apply:
        failed = [
            item for item in payload["items"]
            if item.get("outcome") != "email" or item.get("confirmation_sent_after") is not True
        ]
        return 1 if failed else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
