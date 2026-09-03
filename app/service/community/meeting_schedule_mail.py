"""Meeting schedule email helpers (Java MailService parity)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.utils.run_async import run_async_from_sync
from app.entity.community.meeting_schedule import MeetingSchedule
from app.entity.user.app_user import AppUser
from app.service.auth.email_templates import _format_meeting_datetime
from app.service.auth.mail_service import MailService

logger = logging.getLogger(__name__)


def _meetings_url() -> str:
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/meetings"


def _display_name(user: AppUser | None) -> str:
    if user is None:
        return "—"
    parts = [user.firstname or "", user.lastname or ""]
    name = " ".join(p for p in parts if p).strip()
    return name or (user.username or "") or user.email or "—"


def _auction_title(auction: Any | None) -> str:
    if auction is None:
        return "Profile Auction"
    title = getattr(auction, "auction_title", None)
    if title and str(title).strip():
        return str(title).strip()
    return "Profile Auction"


def _meeting_datetime_parts(scheduled_at: datetime | None) -> tuple[str, str]:
    if scheduled_at is None:
        return "—", "—"
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    else:
        scheduled_at = scheduled_at.astimezone(timezone.utc)
    return _format_meeting_datetime(scheduled_at)


async def _send_meeting_request_email_async(
    *,
    lister: AppUser,
    requester: AppUser,
    auction: Any | None,
    scheduled_at: datetime,
    duration_minutes: int,
    topic: str | None,
    meeting_message: str | None,
) -> None:
    if not settings.mail_configured():
        logger.warning("mail.skip meeting_request lister=%s mail not configured", lister.email)
        return
    scheduled_date, scheduled_time = _meeting_datetime_parts(scheduled_at)
    await MailService.send_meeting_request_email(
        to_email=lister.email,
        lister_name=_display_name(lister),
        requester_name=_display_name(requester),
        auction_title=_auction_title(auction),
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        duration_minutes=duration_minutes,
        topic=topic,
        meeting_message=meeting_message,
        meetings_url=_meetings_url(),
    )


async def _send_meeting_confirmed_email_async(
    *,
    recipient: AppUser,
    other_party: AppUser,
    auction: Any | None,
    scheduled_at: datetime,
    duration_minutes: int,
    meeting_link: str,
    calendar_link: str | None = None,
) -> None:
    if not settings.mail_configured():
        logger.warning(
            "mail.skip meeting_confirmed recipient=%s mail not configured",
            recipient.email,
        )
        return
    scheduled_date, scheduled_time = _meeting_datetime_parts(scheduled_at)
    await MailService.send_meeting_confirmed_email(
        to_email=recipient.email,
        recipient_name=_display_name(recipient),
        other_party_name=_display_name(other_party),
        auction_title=_auction_title(auction),
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        duration_minutes=duration_minutes,
        meeting_link=meeting_link,
        calendar_link=calendar_link,
    )


async def _send_meeting_cancelled_email_async(
    *,
    recipient: AppUser,
    canceller: AppUser,
    auction: Any | None,
    scheduled_at: datetime,
    reason: str | None,
) -> None:
    if not settings.mail_configured():
        logger.warning(
            "mail.skip meeting_cancelled recipient=%s mail not configured",
            recipient.email,
        )
        return
    scheduled_date, scheduled_time = _meeting_datetime_parts(scheduled_at)
    await MailService.send_meeting_cancelled_email(
        to_email=recipient.email,
        recipient_name=_display_name(recipient),
        canceller_name=_display_name(canceller),
        auction_title=_auction_title(auction),
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        reason=reason,
    )


def send_meeting_request_email(
    *,
    lister: AppUser,
    requester: AppUser,
    auction: Any | None,
    scheduled_at: datetime,
    duration_minutes: int,
    topic: str | None,
    meeting_message: str | None,
) -> None:
    try:
        run_async_from_sync(
            _send_meeting_request_email_async,
            lister=lister,
            requester=requester,
            auction=auction,
            scheduled_at=scheduled_at,
            duration_minutes=duration_minutes,
            topic=topic,
            meeting_message=meeting_message,
        )
    except Exception:  # noqa: BLE001
        logger.exception("meeting_request.email.failed lister=%s", lister.email)


def send_meeting_confirmed_emails(
    *,
    lister: AppUser,
    requester: AppUser,
    auction: Any | None,
    meeting: MeetingSchedule,
) -> None:
    meet_link = meeting.meeting_link or ""
    calendar_link = meeting.calendar_event_link
    for recipient, other in ((lister, requester), (requester, lister)):
        try:
            run_async_from_sync(
                _send_meeting_confirmed_email_async,
                recipient=recipient,
                other_party=other,
                auction=auction,
                scheduled_at=meeting.scheduled_at,
                duration_minutes=meeting.duration_minutes,
                meeting_link=meet_link,
                calendar_link=calendar_link,
            )
        except Exception:  # noqa: BLE001
            logger.exception("meeting_confirmed.email.failed recipient=%s", recipient.email)


def send_meeting_cancelled_email(
    *,
    recipient: AppUser,
    canceller: AppUser,
    auction: Any | None,
    scheduled_at: datetime,
    reason: str | None,
) -> None:
    try:
        run_async_from_sync(
            _send_meeting_cancelled_email_async,
            recipient=recipient,
            canceller=canceller,
            auction=auction,
            scheduled_at=scheduled_at,
            reason=reason,
        )
    except Exception:  # noqa: BLE001
        logger.exception("meeting_cancelled.email.failed recipient=%s", recipient.email)
