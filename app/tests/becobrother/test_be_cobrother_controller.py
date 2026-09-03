"""BeCoBrother join form tests."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_becobrother_join_saves_and_emails(client):
    payload = {
        "fullName": "Test Applicant",
        "email": "applicant@example.com",
        "phoneNumber": "9876543210",
        "pinCode": "400001",
        "skill": "WEB_DEV",
        "equipment": True,
    }
    with patch(
        "app.service.becobrother.be_cobrother_service.MailService.send_becobrother_application_email",
        new_callable=AsyncMock,
    ) as send_mail:
        response = client.post("/api/v1/becobrother", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    send_mail.assert_awaited_once()
