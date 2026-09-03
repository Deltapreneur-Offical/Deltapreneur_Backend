from uuid import uuid4

import pytest

from fastapi.testclient import TestClient

from app.main import app

from app.core.dependencies import (
    get_current_user,
    get_db
)

from app.core.security import hash_password
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole


class MockUser:

    def __init__(self, user):

        self.id = user.id
        self.email = user.email
        self.role = user.role


@pytest.fixture()
def test_user():

    db = next(get_db())

    existing_user = (
        db.query(AppUser)
        .filter(
            AppUser.email == "analytics@test.com"
        )
        .first()
    )

    if existing_user:
        db.close()
        return existing_user

    user = AppUser(
        email="analytics@test.com",
        password=hash_password("test123"),
        role=UserRole.USER,
        active=True,
        email_verified=True
    )

    db.add(user)

    db.commit()

    db.refresh(user)

    db.close()

    return user

@pytest.fixture()
def client(test_user):

    def override_get_current_user():

        return MockUser(test_user)

    app.dependency_overrides[
        get_current_user
    ] = override_get_current_user

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_swagger_app_loads(client):

    response = client.get("/docs")

    assert response.status_code == 200


def test_track_venture_view(client):

    venture_id = uuid4()

    response = client.post(
        f"/api/v1/analytics/venture/{venture_id}/track"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True

    assert data["message"] == (
        "Venture view tracked successfully"
    )


def test_get_venture_analytics(client):

    venture_id = uuid4()

    client.post(
        f"/api/v1/analytics/venture/{venture_id}/track"
    )

    response = client.get(
        f"/api/v1/analytics/venture/{venture_id}"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True

    analytics = data["data"]

    assert analytics["ventureId"] == str(
        venture_id
    )

    assert analytics["totalViews"] >= 1

    assert "viewsByDay" in analytics


def test_track_profile_view(
    client,
    test_user
):

    profile_id = test_user.id

    response = client.post(
        f"/api/v1/analytics/profile/{profile_id}/track"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True

    assert data["message"] == (
        "Profile view tracked successfully"
    )


def test_get_profile_analytics(
    client,
    test_user
):

    profile_id = test_user.id

    client.post(
        f"/api/v1/analytics/profile/{profile_id}/track"
    )

    response = client.get(
        "/api/v1/analytics/profile"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True

    analytics = data["data"]

    assert analytics["totalViews"] >= 1

    assert "viewsByDay" in analytics

    assert "byIndustry" in analytics

    assert "byRole" in analytics

def test_duplicate_venture_view_prevented(
    client
):

    venture_id = uuid4()

    client.post(
        f"/api/v1/analytics/venture/{venture_id}/track"
    )

    client.post(
        f"/api/v1/analytics/venture/{venture_id}/track"
    )

    response = client.get(
        f"/api/v1/analytics/venture/{venture_id}"
    )

    assert response.status_code == 200

    data = response.json()

    analytics = data["data"]

    assert analytics["totalViews"] == 1