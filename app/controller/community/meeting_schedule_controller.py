"""REST API for community auction meetings (Java MeetingScheduleController parity)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.entity.user.app_user import AppUser
from app.model.community.meeting_schedule_request import MeetingScheduleRequest
from app.service.community.meeting_schedule_service import MeetingScheduleService

router = APIRouter(prefix="/api/v1/meetings", tags=["Meetings"])


@router.post("/auction/{auction_id}", status_code=status.HTTP_200_OK)
def request_meeting(
    auction_id: uuid.UUID,
    body: MeetingScheduleRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    return MeetingScheduleService.request_meeting(db, auction_id, body, current_user)


@router.put("/{meeting_id}/confirm")
def confirm_meeting(
    meeting_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    return MeetingScheduleService.confirm_meeting(db, meeting_id, current_user)


@router.put("/{meeting_id}/cancel")
def cancel_meeting(
    meeting_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
    body: dict[str, str] | None = None,
) -> dict[str, Any]:
    reason = (body or {}).get("reason")
    return MeetingScheduleService.cancel_meeting(db, meeting_id, reason, current_user)


@router.put("/{meeting_id}/complete")
def complete_meeting(
    meeting_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    return MeetingScheduleService.complete_meeting(db, meeting_id, current_user)


@router.get("/my-requests")
def my_requests(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return MeetingScheduleService.list_my_requests(db, current_user)


@router.get("/my-schedule")
def my_schedule(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return MeetingScheduleService.list_my_schedule(db, current_user)


@router.get("/all")
def all_mine(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return MeetingScheduleService.list_all_mine(db, current_user)


@router.get("/auction/{auction_id}")
def for_auction(
    auction_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return MeetingScheduleService.list_for_auction(db, auction_id, current_user)


@router.get("/admin/all")
def admin_all(
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> list[dict[str, Any]]:
    return MeetingScheduleService.list_admin(db)
