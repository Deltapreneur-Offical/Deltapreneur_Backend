"""Tests for authenticated listing view deduplication."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from app.entity.user.app_user import AppUser
from app.service.marketplace import listing_view_counter as counter


def test_should_count_authenticated_view_skips_owner():
    owner_id = uuid.uuid4()
    viewer = MagicMock(spec=AppUser)
    viewer.id = owner_id
    db = MagicMock()

    assert counter._should_count_authenticated_view(
        db,
        viewer=viewer,
        owner_user_id=owner_id,
        has_viewed=lambda *_args, **_kwargs: False,
        entity_id=uuid.uuid4(),
    ) is False


def test_should_count_authenticated_view_skips_anonymous():
    db = MagicMock()

    assert counter._should_count_authenticated_view(
        db,
        viewer=None,
        owner_user_id=uuid.uuid4(),
        has_viewed=lambda *_args, **_kwargs: False,
        entity_id=uuid.uuid4(),
    ) is False


def test_should_count_authenticated_view_counts_first_visit():
    viewer = MagicMock(spec=AppUser)
    viewer.id = uuid.uuid4()
    db = MagicMock()
    entity_id = uuid.uuid4()

    assert counter._should_count_authenticated_view(
        db,
        viewer=viewer,
        owner_user_id=uuid.uuid4(),
        has_viewed=lambda *_args, **_kwargs: False,
        entity_id=entity_id,
    ) is True


def test_should_count_authenticated_view_skips_repeat_viewer():
    viewer = MagicMock(spec=AppUser)
    viewer.id = uuid.uuid4()
    db = MagicMock()
    entity_id = uuid.uuid4()

    assert counter._should_count_authenticated_view(
        db,
        viewer=viewer,
        owner_user_id=uuid.uuid4(),
        has_viewed=lambda *_args, **_kwargs: True,
        entity_id=entity_id,
    ) is False
