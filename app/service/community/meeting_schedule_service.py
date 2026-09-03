"""Community auction meeting scheduling (Java MeetingScheduleService parity)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.entity.community.community_auction_status import CommunityAuctionStatus
from app.entity.community.meeting_schedule import MeetingSchedule
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.integrations.google.google_calendar_meet import (
    create_meeting_event,
    delete_calendar_event,
    refresh_access_token,
)
from app.model.community.meeting_schedule_request import MeetingScheduleRequest
from app.repository.community_auction_bid_repository import CommunityAuctionBidRepository
from app.repository.community_auction_repository import CommunityAuctionRepository
from app.repository.community_repository import CommunityRepository
from app.repository.meeting_schedule_repository import MeetingScheduleRepository
from app.repository.user_repository import UserRepository
from app.service.community.community_auction_service import CommunityAuctionService
from app.service.community.meeting_schedule_mail import (
    send_meeting_cancelled_email,
    send_meeting_confirmed_emails,
    send_meeting_request_email,
)
from app.service.notification.notification_service import NotificationService

logger = logging.getLogger(__name__)

MIN_NOTICE_HOURS = 1
DEFAULT_DURATION = 30
MAX_DURATION = 120


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _auction_is_live(status: str | None) -> bool:
    normalized = str(status or "").upper()
    return normalized in {
        CommunityAuctionStatus.ACTIVE.value,
        CommunityAuctionStatus.EXTENDED.value,
    }


def _display_name(user: AppUser) -> str:
    parts = [user.firstname or "", user.lastname or ""]
    name = " ".join(p for p in parts if p).strip()
    return name or (user.username or "") or user.email


def _user_summary(user: AppUser | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": str(user.id),
        "firstName": user.firstname or "",
        "lastName": user.lastname or "",
        "email": user.email or "",
    }


def _meeting_to_dict(m: MeetingSchedule) -> dict[str, Any]:
    requester = getattr(m, "requester", None)
    lister = getattr(m, "lister", None)
    return {
        "id": str(m.id),
        "auctionId": str(m.auction_id),
        "requesterId": str(m.requester_id),
        "listerId": str(m.lister_id),
        "requester": _user_summary(requester),
        "lister": _user_summary(lister),
        "scheduledAt": m.scheduled_at.isoformat() if m.scheduled_at else None,
        "durationMinutes": m.duration_minutes,
        "status": m.status,
        "meetingLink": m.meeting_link,
        "googleCalendarEventId": m.google_calendar_event_id,
        "calendarEventLink": m.calendar_event_link,
        "topic": m.topic,
        "message": m.message,
        "cancelReason": m.cancel_reason,
        "cancelledBy": m.cancelled_by,
        "createdAt": m.created_at.isoformat() if m.created_at else None,
        "updatedAt": m.updated_at.isoformat() if m.updated_at else None,
    }


class MeetingScheduleService:
    @staticmethod
    def request_meeting(
        db: Session,
        auction_id: uuid.UUID,
        req: MeetingScheduleRequest,
        requester: AppUser,
    ) -> dict[str, Any]:
        auction = CommunityAuctionRepository.find_by_id(db, auction_id)
        if not auction:
            raise AppException("Auction not found.", status_code=404)

        if not _auction_is_live(auction.status):
            raise AppException(
                "Meeting requests are only available while the auction is active",
                status_code=400,
            )

        community = CommunityRepository.find_by_id(db, auction.community_id)
        if not community:
            raise AppException("Community not found.", status_code=404)

        lister_id = community.app_user_id
        if lister_id == requester.id:
            raise AppException(
                "You cannot schedule a meeting with yourself",
                status_code=400,
            )

        requester_bids = CommunityAuctionBidRepository.find_by_bidder_id(db, requester.id)
        has_bid_for_auction = any(bid.auction_id == auction.id for bid in requester_bids)
        if not has_bid_for_auction:
            raise AppException(
                "You must place at least one bid before requesting a meeting.",
                status_code=403,
            )

        topic = (req.topic or "").strip()
        if not topic:
            raise AppException("Meeting topic is required.", status_code=400)

        scheduled_at = _as_utc(req.scheduled_at)
        if scheduled_at is None:
            raise AppException("scheduledAt is required.", status_code=400)

        now = datetime.now(timezone.utc)
        if scheduled_at <= now + timedelta(hours=MIN_NOTICE_HOURS):
            raise AppException(
                f"Meeting must be scheduled at least {MIN_NOTICE_HOURS} hour(s) in advance",
                status_code=400,
            )

        auction_end = _as_utc(auction.end_time)
        if auction_end and scheduled_at > auction_end:
            raise AppException(
                "Cannot schedule a meeting after the auction ends",
                status_code=400,
            )

        duration = req.duration_minutes or DEFAULT_DURATION
        duration = max(1, min(int(duration), MAX_DURATION))
        meeting_end = scheduled_at + timedelta(minutes=duration)

        lister_conflicts = MeetingScheduleRepository.lister_confirmed_overlap(
            db, lister_id, scheduled_at, meeting_end,
        )
        if lister_conflicts:
            raise AppException(
                "The profile owner already has a confirmed meeting that overlaps "
                "with this time slot. Please choose a different time.",
                status_code=400,
            )

        req_conflicts = MeetingScheduleRepository.requester_confirmed_overlap(
            db, requester.id, scheduled_at, meeting_end,
        )
        if req_conflicts:
            raise AppException(
                "You already have a confirmed meeting that overlaps with this time slot. "
                "Please choose a different time.",
                status_code=400,
            )

        row = MeetingSchedule(
            auction_id=auction.id,
            requester_id=requester.id,
            lister_id=lister_id,
            scheduled_at=scheduled_at,
            duration_minutes=duration,
            status="PENDING",
            topic=topic,
            message=(req.message or "").strip() or None,
        )
        MeetingScheduleRepository.save(db, row)

        lister = UserRepository.find_by_id(db, lister_id)
        if lister:
            NotificationService.notify(
                db,
                user=lister,
                notification_type=NotificationType.GENERAL,
                title="New Meeting Request",
                message=(
                    f"{_display_name(requester)} requested a meeting on "
                    f"{scheduled_at.date()} at {scheduled_at.strftime('%H:%M')} UTC. "
                    f"Topic: {topic}"
                ),
                target_url="/meetings",
            )
            send_meeting_request_email(
                lister=lister,
                requester=requester,
                auction=auction,
                scheduled_at=scheduled_at,
                duration_minutes=duration,
                topic=topic,
                meeting_message=row.message,
            )

        return {
            "success": True,
            "message": "Meeting request sent. Waiting for the profile owner to confirm.",
            "meeting": _meeting_to_dict(row),
        }

    @staticmethod
    def confirm_meeting(db: Session, meeting_id: uuid.UUID, lister: AppUser) -> dict[str, Any]:
        m = MeetingScheduleRepository.get_by_id(db, meeting_id)
        if not m:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
        if m.lister_id != lister.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the profile owner can confirm meetings",
            )
        if (lister.oauth_provider or "").lower() != "google" or not (lister.google_refresh_token or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "The profile owner must log in with Google to enable meeting creation. "
                    "Please ask them to sign out and log back in via Google."
                ),
            )
        if m.status != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Meeting is not in PENDING state",
            )

        start = m.scheduled_at
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        end = start + timedelta(minutes=m.duration_minutes)

        conflicts = MeetingScheduleRepository.lister_confirmed_overlap(
            db, lister.id, start, end, exclude_meeting_id=m.id,
        )
        if conflicts:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "You already have a confirmed meeting that overlaps with this slot. "
                    "Please cancel the conflicting meeting first."
                ),
            )

        requester = UserRepository.find_by_id(db, m.requester_id)
        if not requester:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requester not found")

        try:
            tokens = refresh_access_token(lister.google_refresh_token)
            access = tokens.get("access_token")
            if not access:
                raise RuntimeError("No access_token in Google token response")

            summary = m.topic or "HubRegistrar Meeting"
            desc_lines = [
                "HubRegistrar Platform Meeting",
                "",
                f"Requester: {_display_name(requester)}",
                f"Lister: {_display_name(lister)}",
            ]
            if m.message:
                desc_lines.extend(["", "Message from requester:", m.message])
            description = "\n".join(desc_lines)

            created = create_meeting_event(
                access_token=access,
                summary=summary,
                description=description,
                start=start,
                duration_minutes=m.duration_minutes,
                requester_email=requester.email,
                requester_display_name=_display_name(requester),
                lister_email=lister.email,
                lister_display_name=_display_name(lister),
            )
            m.meeting_link = created.get("meetLink") or ""
            m.google_calendar_event_id = created.get("eventId") or ""
            m.calendar_event_link = created.get("htmlLink") or ""
        except Exception as exc:  # noqa: BLE001
            logger.exception("google.meet.create_failed meeting=%s", meeting_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to create Google Meet: {exc!s}. "
                "Ensure the Google account has Calendar API access and OAuth scopes include calendar.events.",
            ) from exc

        m.status = "CONFIRMED"
        MeetingScheduleRepository.save(db, m)

        NotificationService.notify(
            db,
            user=requester,
            notification_type=NotificationType.GENERAL,
            title="Meeting Confirmed!",
            message=(
                f"Your meeting with {_display_name(lister)} has been confirmed for "
                f"{m.scheduled_at.date()} at {m.scheduled_at.strftime('%H:%M')} UTC"
            ),
            target_url="/meetings",
        )

        NotificationService.notify(
            db,
            user=lister,
            notification_type=NotificationType.GENERAL,
            title="Meeting Confirmed",
            message=(
                f"Your meeting with {_display_name(requester)} is confirmed for "
                f"{m.scheduled_at.date()} at {m.scheduled_at.strftime('%H:%M')} UTC. "
                f"Topic: {m.topic or 'HubRegistrar Meeting'}"
            ),
            target_url="/meetings",
        )

        auction = getattr(m, "auction", None) or CommunityAuctionRepository.find_by_id(db, m.auction_id)
        send_meeting_confirmed_emails(
            lister=lister,
            requester=requester,
            auction=auction,
            meeting=m,
        )

        return {
            "success": True,
            "message": "Meeting confirmed. Google Meet link created and calendar invites sent.",
            "meetingLink": m.meeting_link,
            "calendarEventLink": m.calendar_event_link or "",
            "meeting": _meeting_to_dict(m),
        }

    @staticmethod
    def cancel_meeting(
        db: Session,
        meeting_id: uuid.UUID,
        reason: str | None,
        user: AppUser,
    ) -> dict[str, Any]:
        m = MeetingScheduleRepository.get_by_id(db, meeting_id)
        if not m:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
        is_lister = m.lister_id == user.id
        is_requester = m.requester_id == user.id
        if not is_lister and not is_requester:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not part of this meeting",
            )
        if m.status == "CANCELLED":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Meeting is already cancelled")
        if m.status == "COMPLETED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot cancel a completed meeting",
            )

        m.status = "CANCELLED"
        m.cancel_reason = reason
        m.cancelled_by = "LISTER" if is_lister else "REQUESTER"

        if m.google_calendar_event_id:
            lister = UserRepository.find_by_id(db, m.lister_id)
            if lister and (lister.google_refresh_token or "").strip():
                try:
                    tokens = refresh_access_token(lister.google_refresh_token)
                    access = tokens.get("access_token")
                    if access:
                        delete_calendar_event(
                            access_token=access,
                            event_id=m.google_calendar_event_id,
                        )
                except Exception:  # noqa: BLE001
                    logger.warning("google.calendar.delete_failed meeting=%s", meeting_id, exc_info=True)

        MeetingScheduleRepository.save(db, m)

        other = UserRepository.find_by_id(db, m.requester_id if is_lister else m.lister_id)
        if other:
            NotificationService.notify(
                db,
                user=other,
                notification_type=NotificationType.GENERAL,
                title="Meeting Cancelled",
                message=(
                    f"{_display_name(user)} cancelled the meeting scheduled for "
                    f"{m.scheduled_at.date()} at {m.scheduled_at.strftime('%H:%M')}"
                    + (f". Reason: {reason}" if reason else "")
                ),
                target_url="/meetings",
            )
            auction = getattr(m, "auction", None) or CommunityAuctionRepository.find_by_id(
                db, m.auction_id
            )
            send_meeting_cancelled_email(
                recipient=other,
                canceller=user,
                auction=auction,
                scheduled_at=m.scheduled_at,
                reason=reason,
            )

        return {"success": True, "message": "Meeting cancelled"}

    @staticmethod
    def complete_meeting(db: Session, meeting_id: uuid.UUID, lister: AppUser) -> dict[str, Any]:
        m = MeetingScheduleRepository.get_by_id(db, meeting_id)
        if not m:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
        if m.lister_id != lister.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the profile owner can mark meetings as completed",
            )
        if m.status != "CONFIRMED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only confirmed meetings can be marked as completed",
            )
        m.status = "COMPLETED"
        MeetingScheduleRepository.save(db, m)
        return {"success": True, "message": "Meeting marked as completed"}

    @staticmethod
    def list_my_requests(db: Session, user: AppUser) -> list[dict[str, Any]]:
        rows = MeetingScheduleRepository.find_by_requester_id(db, user.id)
        return [_meeting_to_dict(x) for x in rows]

    @staticmethod
    def list_my_schedule(db: Session, user: AppUser) -> list[dict[str, Any]]:
        rows = MeetingScheduleRepository.find_by_lister_id(db, user.id)
        return [_meeting_to_dict(x) for x in rows]

    @staticmethod
    def list_all_mine(db: Session, user: AppUser) -> list[dict[str, Any]]:
        rows = MeetingScheduleRepository.find_all_for_user(db, user.id)
        return [_meeting_to_dict(x) for x in rows]

    @staticmethod
    def list_for_auction(db: Session, auction_id: uuid.UUID, viewer: AppUser) -> list[dict[str, Any]]:
        auction = CommunityAuctionRepository.find_by_id(db, auction_id)
        if not auction:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Auction not found")
        community = CommunityRepository.find_by_id(db, auction.community_id)
        if not community:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Community not found")
        is_lister = community.app_user_id == viewer.id
        if is_lister:
            rows = MeetingScheduleRepository.find_by_auction_id(db, auction_id)
        else:
            rows = MeetingScheduleRepository.find_by_auction_and_requester(db, auction_id, viewer.id)
        return [_meeting_to_dict(x) for x in rows]

    @staticmethod
    def list_admin(db: Session) -> list[dict[str, Any]]:
        rows = MeetingScheduleRepository.find_all_admin(db)
        return [_meeting_to_dict(x) for x in rows]
