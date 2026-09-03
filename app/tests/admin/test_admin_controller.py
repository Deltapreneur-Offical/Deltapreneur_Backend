from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.entity.user.user_role import UserRole
from app.main import app


class MockAdminUser:

    def __init__(self):
        self.id = uuid4()
        self.role = UserRole.ADMIN


class MockNormalUser:

    def __init__(self):
        self.id = uuid4()
        self.role = UserRole.USER


def override_get_current_user():
    return MockAdminUser()


@pytest.fixture
def admin_client():
    app.dependency_overrides[get_current_user] = override_get_current_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_get_all_cobrothers(admin_client):

    response = admin_client.get(
        "/api/v1/admin/cobrothers"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True

    assert "count" in data

    assert "data" in data


def test_admin_dashboard(admin_client):

    response = admin_client.get(
        "/api/v1/admin/dashboard"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True

    assert "data" in data

    assert "totalUsers" in data["data"]

    assert "totalCoBrothers" in data["data"]

    assert "totalVentureViews" in data["data"]

    assert "totalProfileViews" in data["data"]

    assert "totalVentures" in data["data"]

    assert "totalDomains" in data["data"]

    assert "totalTechnologies" in data["data"]

    assert "totalCreators" in data["data"]


def test_non_admin_forbidden():

    app.dependency_overrides[get_current_user] = lambda: MockNormalUser()

    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/admin/dashboard"
            )
            assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
