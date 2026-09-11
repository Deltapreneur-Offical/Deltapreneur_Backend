from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_submit_feedback_success_calls_service() -> None:
    with patch(
        "app.controller.feedback.feedback_controller.FeedbackService.send_feedback_email",
        new=AsyncMock(return_value=None),
    ) as send_mock:
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

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    send_mock.assert_awaited_once()


def test_submit_feedback_reports_undeliverable_when_smtp_fails() -> None:
    with patch("app.core.config.Settings.mail_configured", return_value=True), patch(
        "app.service.feedback.feedback_service.MailService.send_feedback_email",
        new=AsyncMock(
            side_effect=RuntimeError(
                "Error connecting to smtp.example.com on port 587: [Errno -5]"
            )
        ),
    ):
        response = client.post(
            "/api/v1/feedback",
            json={"feedbackType": "like", "message": "Great content quality."},
        )

    assert response.status_code == 503
    body = response.json()
    assert body["success"] is False
    assert "smtp" not in body["message"].lower()


def test_submit_feedback_reports_undeliverable_when_mail_unconfigured() -> None:
    with patch("app.core.config.Settings.mail_configured", return_value=False):
        response = client.post(
            "/api/v1/feedback",
            json={"feedbackType": "like", "message": "Great content quality."},
        )

    assert response.status_code == 503
    assert response.json()["success"] is False


def test_submit_feedback_requires_message() -> None:
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

