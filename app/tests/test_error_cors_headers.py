"""Unhandled 500s must keep CORS headers, or browsers hide the real error."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


BROWSER_ORIGIN = "https://www.deltapreneur.com"

client = TestClient(app, raise_server_exceptions=False)


def _post_feedback():
    return client.post(
        "/api/v1/feedback",
        json={
            "feedbackType": "like",
            "message": "Checking error handling.",
            "pageUrl": "https://www.deltapreneur.com/",
        },
        headers={"Origin": BROWSER_ORIGIN},
    )


def test_unhandled_error_response_keeps_cors_headers() -> None:
    # Force a genuinely unhandled error inside the request (not the backgrounded
    # mail send, which is deliberately swallowed) to prove a 500 still carries
    # CORS headers via UnhandledExceptionMiddleware.
    with patch(
        "app.controller.feedback.feedback_controller.enforce_bot_protection",
        new=AsyncMock(side_effect=RuntimeError("boom inside request")),
    ):
        response = _post_feedback()

    assert response.status_code == 500
    assert response.headers.get("access-control-allow-origin") == BROWSER_ORIGIN
    assert response.json()["success"] is False


def test_successful_response_keeps_cors_headers() -> None:
    with patch("app.core.config.Settings.mail_configured", return_value=True), patch(
        "app.controller.feedback.feedback_controller.FeedbackService.deliver_feedback_email",
        new=AsyncMock(return_value=None),
    ):
        response = _post_feedback()

    assert response.status_code == 202
    assert response.headers.get("access-control-allow-origin") == BROWSER_ORIGIN


def test_handled_error_response_keeps_cors_headers() -> None:
    response = client.post(
        "/api/v1/feedback",
        json={"feedbackType": "like", "message": "   "},
        headers={"Origin": BROWSER_ORIGIN},
    )

    assert response.status_code == 400
    assert response.headers.get("access-control-allow-origin") == BROWSER_ORIGIN
