"""Creator follow service."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.service.community.creator_follow_service import CreatorFollowService


def _community(owner_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        app_user_id=owner_id or uuid.uuid4(),
        name="Pooja",
    )


def test_toggle_follow_creates_follow_for_other_user():
    db = MagicMock()
    community = _community()
    follower = SimpleNamespace(id=uuid.uuid4(), firstname="A", lastname="B", email="a@b.c")

    with (
        patch(
            "app.service.community.creator_follow_service.CommunityRepository.find_by_id",
            return_value=community,
        ),
        patch(
            "app.service.community.creator_follow_service.CreatorFollowRepository.find_active",
            return_value=None,
        ),
        patch(
            "app.service.community.creator_follow_service.CreatorFollowRepository.find_any",
            return_value=None,
        ),
        patch(
            "app.service.community.creator_follow_service.CreatorFollowRepository.save",
        ) as save_mock,
        patch(
            "app.service.community.creator_follow_service.CreatorFollowRepository.count_for_community",
            return_value=1,
        ),
        patch.object(CreatorFollowService, "_notify_creator_on_follow"),
    ):
        result = CreatorFollowService.toggle_follow(
            db,
            community_id=community.id,
            current_user=follower,
        )

    assert result["following"] is True
    assert result["followerCount"] == 1
    save_mock.assert_called_once()


def test_toggle_follow_rejects_self_follow():
    db = MagicMock()
    owner_id = uuid.uuid4()
    community = _community(owner_id=owner_id)
    owner = SimpleNamespace(id=owner_id)

    with patch(
        "app.service.community.creator_follow_service.CommunityRepository.find_by_id",
        return_value=community,
    ):
        with pytest.raises(HTTPException) as exc:
            CreatorFollowService.toggle_follow(
                db,
                community_id=community.id,
                current_user=owner,
            )

    assert exc.value.status_code == 400
