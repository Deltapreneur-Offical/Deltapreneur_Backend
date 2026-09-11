from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_submit_feedback_accepts_and_delivers_in_background() -> None:
    with patch("app.core.config.Settings.mail_configured", return_value=True), patch(
        "app.controller.feedback.feedback_controller.FeedbackService.deliver_feedback_email",
        new=AsyncMock(return_value=None),
    ) as deliver_mock:
        response = client.post(
            "/api/v1/feedback",
            json={
                "feedbackType": "like",
                "message": "Great content quality.",
                "pageUrl": "http://127.0.0.1:5173/",
                "email": "user@example.com",
                "subject": "Home page feedback",
            },
        )

    assert response.status_code == 202
    assert response.json()["status"] == "success"
    # TestClient runs background tasks after the response is returned.
    deliver_mock.assert_awaited_once()


def test_submit_feedback_still_accepts_when_background_send_fails() -> None:
    # A blocked SMTP server must not fail the user's request; delivery is
    # attempted in the background and only logged on failure.
    with patch("app.core.config.Settings.mail_configured", return_value=True), patch(
        "app.service.feedback.feedback_service.MailService.send_feedback_email",
        new=AsyncMock(
            side_effect=RuntimeError(
                "Timed out connecting to smtp.gmail.com on port 587"
            )
        ),
    ):
        response = client.post(
            "/api/v1/feedback",
            json={"feedbackType": "like", "message": "Great content quality."},
        )

    # deliver_feedback_email swallows the error; the endpoint already returned 202.
    assert response.status_code == 202
    assert response.json()["status"] == "success"


def test_submit_feedback_reports_undeliverable_when_mail_unconfigured() -> None:
    with patch("app.core.config.Settings.mail_configured", return_value=False):
        response = client.post(
            "/api/v1/feedback",
            json={"feedbackType": "like", "message": "Great content quality."},
        )

    assert response.status_code == 503
    body = response.json()
    assert body["success"] is False
    # Never leak the SMTP host to the browser.
    assert "smtp" not in body["message"].lower()


def test_submit_feedback_requires_message() -> None:
    with patch("app.core.config.Settings.mail_configured", return_value=True):
        response = client.post(
            "/api/v1/feedback",
            json={
                "feedbackType": "dislike",
                "message": "   ",
                "pageUrl": "http://127.0.0.1:5173/",
            },
        )

    assert response.status_code == 400
    body = response.json()
    assert body["message"] == "Feedback message is required"
