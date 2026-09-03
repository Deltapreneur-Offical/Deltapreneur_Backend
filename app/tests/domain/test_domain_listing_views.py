"""Domain listing view counter."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppException
from app.service.domain.marketplace_domain_service import MarketplaceDomainService


def _listing(*, views: int = 0, owner_id: uuid.UUID | None = None) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        views=views,
        listed_by_user_id=owner_id or uuid.uuid4(),
        updated_at=now,
    )


@pytest.mark.asyncio
@patch(
    "app.service.domain.marketplace_domain_service.record_domain_listing_view",
    new_callable=AsyncMock,
)
async def test_record_view_increments_for_non_owner(mock_record):
    mock_record.return_value = True
    listing = _listing(views=2)
    viewer = SimpleNamespace(id=uuid.uuid4())
    db = MagicMock()

    repo = SimpleNamespace(
        get_by_id=AsyncMock(side_effect=[listing, _listing(views=3)]),
        increment_views=AsyncMock(),
    )
    session = SimpleNamespace(commit=AsyncMock())
    service = MarketplaceDomainService(session)
    service._repo = repo

    result = await service.get_listing_and_record_view(
        listing.id,
        viewer=viewer,
        db=db,
    )

    assert result.views == 3
    repo.increment_views.assert_awaited_once_with(listing.id)
    session.commit.assert_awaited_once()
    mock_record.assert_awaited_once()


@pytest.mark.asyncio
@patch(
    "app.service.domain.marketplace_domain_service.record_domain_listing_view",
    new_callable=AsyncMock,
)
async def test_record_view_skips_repeat_viewer(mock_record):
    mock_record.return_value = False
    listing = _listing(views=2)
    viewer = SimpleNamespace(id=uuid.uuid4())
    db = MagicMock()

    repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=listing),
        increment_views=AsyncMock(),
    )
    session = SimpleNamespace(commit=AsyncMock())
    service = MarketplaceDomainService(session)
    service._repo = repo

    result = await service.get_listing_and_record_view(
        listing.id,
        viewer=viewer,
        db=db,
    )

    assert result.views == 2
    repo.increment_views.assert_not_called()
    session.commit.assert_not_called()
    mock_record.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_view_skips_owner():
    owner_id = uuid.uuid4()
    listing = _listing(views=4, owner_id=owner_id)
    viewer = SimpleNamespace(id=owner_id)
    db = MagicMock()

    repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=listing),
        save=AsyncMock(),
    )
    session = SimpleNamespace(commit=AsyncMock())
    service = MarketplaceDomainService(session)
    service._repo = repo

    result = await service.get_listing_and_record_view(
        listing.id,
        viewer=viewer,
        db=db,
    )

    assert result.views == 4
    repo.save.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_listing_raises_when_missing():
    repo = SimpleNamespace(get_by_id=AsyncMock(return_value=None))
    session = SimpleNamespace(commit=AsyncMock())
    service = MarketplaceDomainService(session)
    service._repo = repo

    with pytest.raises(AppException) as exc:
        await service.get_listing_and_record_view(
            uuid.uuid4(),
            viewer=SimpleNamespace(id=uuid.uuid4()),
            db=MagicMock(),
        )

    assert exc.value.status_code == 404
