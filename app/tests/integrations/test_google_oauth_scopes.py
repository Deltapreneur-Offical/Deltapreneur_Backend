from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from app.integrations.google.google_calendar_meet import create_meeting_event
from app.integrations.oauth.google_oauth_redirect import build_google_authorization_url


def test_google_oauth_authorization_uses_calendar_events_scope_only() -> None:
    url = build_google_authorization_url("state-123")
    query = parse_qs(urlparse(url).query, keep_blank_values=True)

    assert query["scope"][0] == "openid email profile https://www.googleapis.com/auth/calendar.events"


def test_create_meeting_event_still_uses_calendar_event_payload_for_meet_creation() -> None:
    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "id": "evt_123",
                "htmlLink": "https://calendar.google.com/event",
                "hangoutLink": "https://meet.google.com/abc-defg-hij",
            }

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs
            self.request_payload = None

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, url: str, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            self.request_payload = {"url": url, "headers": headers, "json": json}
            return FakeResponse()

    with patch("app.integrations.google.google_calendar_meet.httpx.Client", FakeClient):
        result = create_meeting_event(
            access_token="token-123",
            summary="HubRegistrar Meeting",
            description="Test",
            start=datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc),
            duration_minutes=30,
            requester_email="requester@example.com",
            requester_display_name="Requester",
            lister_email="lister@example.com",
            lister_display_name="Lister",
        )

    assert result["meetLink"] == "https://meet.google.com/abc-defg-hij"
    assert result["eventId"] == "evt_123"
    assert result["htmlLink"] == "https://calendar.google.com/event"
