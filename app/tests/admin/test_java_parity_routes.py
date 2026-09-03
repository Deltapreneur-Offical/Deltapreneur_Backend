"""Java parity routes: technology metadata, auth /mee, admin forward validation."""

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
        self.email = "admin@test.com"
        self.email_verified = True
        self.profile_complete = True
        self.active = True
        self.is_deleted = False


class MockAuthUser:
    def __init__(self):
        self.id = uuid4()
        self.role = UserRole.USER
        self.email = "user@test.com"
        self.email_verified = True
        self.profile_complete = True
        self.active = True
        self.is_deleted = False
        self.firstname = "Test"
        self.lastname = "User"
        self.username = "testuser"
        self.phone_number = None
        self.phone_verified = False
        self.address = None


@pytest.fixture
def admin_client():
    app.dependency_overrides[get_current_user] = lambda: MockAdminUser()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def auth_client():
    app.dependency_overrides[get_current_user] = lambda: MockAuthUser()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_technology_categories_returns_java_list():
    with TestClient(app) as client:
        response = client.get("/api/v1/technology/categories")
    assert response.status_code == 200
    assert response.json() == ["AI", "Blockchain", "Web Development"]


def test_technology_test_health():
    with TestClient(app) as client:
        response = client.get("/api/v1/technology/test")
    assert response.status_code == 200
    assert response.json() == "WORKING"


def test_auth_mee_flat_payload(auth_client):
    response = auth_client.get("/api/v1/auth/mee")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"id", "email", "role", "emailVerified"}
    assert body["email"] == "user@test.com"
    assert body["role"] == "USER"


def test_admin_forward_requires_cobrother_id(admin_client):
    response = admin_client.post(
        "/api/v1/admin/forward",
        json={
            "entityId": str(uuid4()),
            "type": "COVENTURE",
        },
    )
    assert response.status_code == 400
    assert response.json().get("error")
