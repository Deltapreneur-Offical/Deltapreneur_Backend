"""Create Google Calendar events with Meet using the lister's OAuth refresh token (sync httpx)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
CAL_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    cid = (settings.GOOGLE_CLIENT_ID or "").strip()
    sec = (settings.GOOGLE_CLIENT_SECRET or "").strip()
    if not cid or not sec or not refresh_token:
        raise RuntimeError("Google OAuth client credentials or refresh token missing.")
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": cid,
                "client_secret": sec,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        r.raise_for_status()
        return r.json()


def _extract_meet_link(data: dict[str, Any]) -> str | None:
    link = data.get("hangoutLink")
    if link:
        return str(link)
    for ep in data.get("conferenceData", {}).get("entryPoints", []) or []:
        if ep.get("entryPointType") == "video" and ep.get("uri"):
            return str(ep["uri"])
    return None


def create_meeting_event(
    *,
    access_token: str,
    summary: str,
    description: str,
    start: datetime,
    duration_minutes: int,
    requester_email: str,
    requester_display_name: str,
    lister_email: str,
    lister_display_name: str,
) -> dict[str, Any]:
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = start + timedelta(minutes=duration_minutes)

    body: dict[str, Any] = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "attendees": [
            {"email": lister_email, "displayName": lister_display_name},
            {"email": requester_email, "displayName": requester_display_name},
        ],
        "conferenceData": {
            "createRequest": {
                "requestId": f"meet-{int(start.timestamp())}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=45.0) as client:
        r = client.post(
            f"{CAL_EVENTS_URL}?conferenceDataVersion=1",
            headers=headers,
            json=body,
        )
        if r.status_code >= 400:
            logger.error(
                "google.calendar.create_failed status=%s body=%s",
                r.status_code,
                r.text[:2000],
            )
        r.raise_for_status()
        data = r.json()
        meet = _extract_meet_link(data)
        return {
            "raw": data,
            "meetLink": meet or "",
            "eventId": data.get("id") or "",
            "htmlLink": data.get("htmlLink") or "",
        }


def delete_calendar_event(*, access_token: str, event_id: str) -> None:
    if not event_id:
        return
    url = f"{CAL_EVENTS_URL}/{event_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=30.0) as client:
        r = client.delete(url, headers=headers)
        if r.status_code == 404:
            return
        r.raise_for_status()
