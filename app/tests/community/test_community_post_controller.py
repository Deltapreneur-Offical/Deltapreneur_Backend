import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.main import app


client = TestClient(app)


def _fake_user(user_id=None):
    return SimpleNamespace(
        id=user_id or uuid.uuid4(),
        email="test@example.com",
        firstname="Test",
        lastname="User",
        is_deleted=False,
        active=True,
    )


def _fake_community(community_id=None, app_user_id=None):
    now = datetime.now(timezone.utc)

    return SimpleNamespace(
        id=community_id or uuid.uuid4(),
        app_user_id=app_user_id or uuid.uuid4(),
        name="Test Community",
        is_deleted=False,
        created_at=now,
        updated_at=now,
    )


def _fake_post(
    *,
    post_id=None,
    community_id=None,
    author_id=None,
):
    now = datetime.now(timezone.utc)

    return SimpleNamespace(
        id=post_id or uuid.uuid4(),
        community_id=community_id or uuid.uuid4(),
        author_id=author_id or uuid.uuid4(),
        title="Starting backend discussion",
        content="This is a test community post.",
        image_url=None,
        created_at=now,
        updated_at=now,
        is_deleted=False,
        deleted_at=None,
        deleted_by=None,
    )


def _fake_comment(
    *,
    comment_id=None,
    post_id=None,
    author_id=None,
):
    now = datetime.now(timezone.utc)

    return SimpleNamespace(
        id=comment_id or uuid.uuid4(),
        post_id=post_id or uuid.uuid4(),
        author_id=author_id or uuid.uuid4(),
        content="This is a test comment.",
        created_at=now,
        updated_at=now,
        is_deleted=False,
        deleted_at=None,
        deleted_by=None,
    )


def _login_as(user):
    app.dependency_overrides[get_current_user] = lambda: user


def _clear_login():
    app.dependency_overrides.clear()


def test_community_post_module_connected():
    response = client.get("/api/v1/community-posts/test")

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["message"] == "Community post module is connected successfully"
    assert body["data"]["module"] == "community-posts"
    assert body["data"]["status"] == "ready"


def test_create_community_post_success():
    user = _fake_user()
    community_id = uuid.uuid4()
    community = _fake_community(
        community_id=community_id,
        app_user_id=user.id,
    )
    post = _fake_post(
        community_id=community_id,
        author_id=user.id,
    )

    _login_as(user)

    try:
        def save_post_side_effect(**kwargs):
            return kwargs["post"]

        with patch(
            "app.service.community.community_post_service.CommunityRepository.find_by_id",
            return_value=community,
        ), patch(
            "app.service.community.community_post_service.CommunityPostRepository.save",
            side_effect=save_post_side_effect,
        ):
            response = client.post(
                "/api/v1/community-posts",
                json={
                    "community_id": str(community_id),
                    "title": post.title,
                    "content": post.content,
                    "image_url": None,
                },
            )

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Community post created successfully"
        assert body["data"]["community_id"] == str(community_id)
        assert body["data"]["author_id"] == str(user.id)
        assert body["data"]["title"] == post.title

    finally:
        _clear_login()


def test_get_all_community_posts_success():
    post = _fake_post()

    with patch(
        "app.service.community.community_post_service.CommunityPostRepository.find_all",
        return_value=[post],
    ):
        response = client.get("/api/v1/community-posts/all")

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["message"] == "Community posts fetched successfully"
    assert len(body["data"]) == 1


def test_get_my_community_posts_success():
    user = _fake_user()
    post = _fake_post(author_id=user.id)

    _login_as(user)

    try:
        with patch(
            "app.service.community.community_post_service.CommunityPostRepository.find_by_author_id",
            return_value=[post],
        ):
            response = client.get("/api/v1/community-posts/my")

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "My community posts fetched successfully"
        assert len(body["data"]) == 1
        assert body["data"][0]["author_id"] == str(user.id)

    finally:
        _clear_login()


def test_get_community_post_by_id_success():
    post_id = uuid.uuid4()
    post = _fake_post(post_id=post_id)

    with patch(
        "app.service.community.community_post_service.CommunityPostRepository.find_by_id",
        return_value=post,
    ):
        response = client.get(f"/api/v1/community-posts/{post_id}")

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["message"] == "Community post fetched successfully"
    assert body["data"]["id"] == str(post_id)


def test_get_missing_community_post_returns_404():
    post_id = uuid.uuid4()

    with patch(
        "app.service.community.community_post_service.CommunityPostRepository.find_by_id",
        return_value=None,
    ):
        response = client.get(f"/api/v1/community-posts/{post_id}")

    assert response.status_code == 404


def test_delete_community_post_success():
    user = _fake_user()
    post_id = uuid.uuid4()
    post = _fake_post(
        post_id=post_id,
        author_id=user.id,
    )

    _login_as(user)

    try:
        with patch(
            "app.service.community.community_post_service.CommunityPostRepository.find_by_id",
            return_value=post,
        ), patch(
            "app.service.community.community_post_service.CommunityPostRepository.soft_delete",
        ) as soft_delete_mock:
            response = client.delete(f"/api/v1/community-posts/{post_id}")

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Community post deleted successfully"

        soft_delete_mock.assert_called_once()

    finally:
        _clear_login()


def test_add_community_comment_success():
    user = _fake_user()
    post_owner_id = uuid.uuid4()
    post_id = uuid.uuid4()
    post = _fake_post(
        post_id=post_id,
        author_id=post_owner_id,
    )

    _login_as(user)

    try:
        def save_comment_side_effect(**kwargs):
            return kwargs["comment"]

        with patch(
            "app.service.community.community_post_service.CommunityPostRepository.find_by_id",
            return_value=post,
        ), patch(
            "app.service.community.community_post_service.CommunityCommentRepository.save",
            side_effect=save_comment_side_effect,
        ), patch(
            "app.service.community.community_post_service.UserRepository.find_by_id",
            return_value=None,
        ), patch(
            "app.service.community.community_post_service.NotificationService.notify",
        ):
            response = client.post(
                f"/api/v1/community-posts/{post_id}/comments",
                json={
                    "content": "This is a test comment.",
                },
            )

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Community comment added successfully"
        assert body["data"]["post_id"] == str(post_id)
        assert body["data"]["author_id"] == str(user.id)

    finally:
        _clear_login()


def test_get_community_comments_success():
    post_id = uuid.uuid4()
    post = _fake_post(post_id=post_id)
    comment = _fake_comment(post_id=post_id)

    with patch(
        "app.service.community.community_post_service.CommunityPostRepository.find_by_id",
        return_value=post,
    ), patch(
        "app.service.community.community_post_service.CommunityCommentRepository.find_by_post_id",
        return_value=[comment],
    ):
        response = client.get(f"/api/v1/community-posts/{post_id}/comments")

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["message"] == "Community comments fetched successfully"
    assert len(body["data"]) == 1
    assert body["data"][0]["post_id"] == str(post_id)


def test_delete_community_comment_success():
    user = _fake_user()
    comment_id = uuid.uuid4()
    comment = _fake_comment(
        comment_id=comment_id,
        author_id=user.id,
    )

    _login_as(user)

    try:
        with patch(
            "app.service.community.community_post_service.CommunityCommentRepository.find_by_id",
            return_value=comment,
        ), patch(
            "app.service.community.community_post_service.CommunityCommentRepository.soft_delete",
        ) as soft_delete_mock:
            response = client.delete(
                f"/api/v1/community-posts/comments/{comment_id}"
            )

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Community comment deleted successfully"

        soft_delete_mock.assert_called_once()

    finally:
        _clear_login()
