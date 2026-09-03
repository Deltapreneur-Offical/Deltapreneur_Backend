"""Domain enquiry CRM pipeline tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppException
from app.service.domain.domain_enquiry_service import (
    DomainEnquiryService,
    _ACTIVE_ENQUIRY_STATUSES,
    _ALLOWED_TRANSITIONS,
)
from app.utils.marketplace_enums import DomainEnquiryStatus, DomainListingStatus


def _admin_user():
    return SimpleNamespace(
        id=uuid.uuid4(),
        email="admin@cobrother.com",
        firstname="Admin",
        lastname="User",
    )


def _enquiry_row(**overrides):
    base = {
        "id": uuid.uuid4(),
        "domain_listing_id": uuid.uuid4(),
        "enquirer_user_id": uuid.uuid4(),
        "full_name": "Buyer",
        "email": "buyer@example.com",
        "phone": "+911234567890",
        "message": "Interested",
        "status": DomainEnquiryStatus.PENDING.value,
        "admin_notes": None,
        "in_progress_at": None,
        "completed_at": None,
        "declined_at": None,
        "is_deleted": False,
        "deleted_at": None,
        "deleted_by": None,
        "created_at": datetime.now(timezone.utc),
        "domain_listing": SimpleNamespace(
            domain_name="example",
            domain_extension=".com",
            asking_price=600000.0,
            domain_status=DomainListingStatus.UNDER_REVIEW,
            listed_by=SimpleNamespace(
                id=uuid.uuid4(),
                firstname="Lister",
                lastname="One",
                email="lister@example.com",
                phone_number=None,
            ),
        ),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _mock_session_with_enquiry(enquiry):
    session = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    result = MagicMock()
    result.scalar_one_or_none.return_value = enquiry
    session.execute = AsyncMock(return_value=result)
    return session


def test_allowed_transition_matrix():
    assert DomainEnquiryStatus.ACCEPTED in _ALLOWED_TRANSITIONS[DomainEnquiryStatus.PENDING]
    assert DomainEnquiryStatus.IN_PROGRESS in _ALLOWED_TRANSITIONS[DomainEnquiryStatus.PENDING]
    assert DomainEnquiryStatus.DECLINED in _ALLOWED_TRANSITIONS[DomainEnquiryStatus.PENDING]
    assert DomainEnquiryStatus.COMPLETED not in _ALLOWED_TRANSITIONS[DomainEnquiryStatus.PENDING]
    assert DomainEnquiryStatus.ACCEPTED in _ALLOWED_TRANSITIONS[DomainEnquiryStatus.IN_PROGRESS]
    assert DomainEnquiryStatus.DECLINED in _ALLOWED_TRANSITIONS[DomainEnquiryStatus.ACCEPTED]
    assert _ALLOWED_TRANSITIONS[DomainEnquiryStatus.COMPLETED] == set()
    assert DomainEnquiryStatus.PENDING in _ALLOWED_TRANSITIONS[DomainEnquiryStatus.DECLINED]


def test_active_enquiry_statuses_include_pipeline():
    assert set(_ACTIVE_ENQUIRY_STATUSES) == {
        DomainEnquiryStatus.PENDING.value,
        DomainEnquiryStatus.IN_PROGRESS.value,
        DomainEnquiryStatus.ACCEPTED.value,
    }


def test_parse_status_rejects_completed_via_status_update():
    with pytest.raises(AppException, match="Mark Domain as Sold"):
        DomainEnquiryService._parse_status("COMPLETED")


def test_parse_status_rejects_forwarded_target():
    with pytest.raises(AppException, match="cannot be set"):
        DomainEnquiryService._parse_status("FORWARDED")


@pytest.mark.parametrize(
    ("current", "new", "timestamp_field"),
    [
        (DomainEnquiryStatus.PENDING, DomainEnquiryStatus.IN_PROGRESS, "in_progress_at"),
        (DomainEnquiryStatus.PENDING, DomainEnquiryStatus.ACCEPTED, None),
        (DomainEnquiryStatus.PENDING, DomainEnquiryStatus.DECLINED, "declined_at"),
        (DomainEnquiryStatus.IN_PROGRESS, DomainEnquiryStatus.ACCEPTED, None),
        (DomainEnquiryStatus.IN_PROGRESS, DomainEnquiryStatus.DECLINED, "declined_at"),
        (DomainEnquiryStatus.ACCEPTED, DomainEnquiryStatus.DECLINED, "declined_at"),
        (DomainEnquiryStatus.DECLINED, DomainEnquiryStatus.PENDING, None),
    ],
)
@pytest.mark.asyncio
async def test_update_status_allowed_transitions(current, new, timestamp_field):
    admin = _admin_user()
    enquiry = _enquiry_row(status=current.value)
    session = _mock_session_with_enquiry(enquiry)
    service = DomainEnquiryService(session)
    service._listings.save = AsyncMock(return_value=enquiry.domain_listing)
    service._notify_buyer_of_update = AsyncMock()

    with patch("app.service.domain.domain_enquiry_service.select"), \
         patch("app.service.domain.domain_enquiry_service.selectinload"), \
         patch(
             "app.service.domain.domain_enquiry_service.serialize_domain_enquiry",
             return_value={"status": new.value, "adminNotes": "Customer agreed."},
         ):
        result = await service.update_status(
            enquiry.id,
            admin=admin,
            status=new.value,
            admin_notes="Customer agreed.",
        )

    assert enquiry.status == new.value
    assert enquiry.admin_notes == "Customer agreed."
    if timestamp_field:
        assert getattr(enquiry, timestamp_field) is not None
    assert result["status"] == new.value
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_enquiry_soft_deletes_completed():
    admin = _admin_user()
    enquiry = _enquiry_row(status=DomainEnquiryStatus.COMPLETED.value)
    session = _mock_session_with_enquiry(enquiry)
    service = DomainEnquiryService(session)

    with patch("app.service.domain.domain_enquiry_service.select"), \
         patch("app.service.domain.domain_enquiry_service.selectinload"):
        result = await service.remove_enquiry(
            enquiry.id,
            admin=admin,
            admin_notes="Archived after sale",
        )

    assert enquiry.is_deleted is True
    assert enquiry.deleted_at is not None
    assert enquiry.deleted_by == admin.id
    assert enquiry.admin_notes == "Archived after sale"
    assert result["success"] is True
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_enquiry_soft_deletes_pending():
    admin = _admin_user()
    enquiry = _enquiry_row(status=DomainEnquiryStatus.PENDING.value)
    session = _mock_session_with_enquiry(enquiry)
    service = DomainEnquiryService(session)
    service._listings.save = AsyncMock(return_value=enquiry.domain_listing)

    with patch("app.service.domain.domain_enquiry_service.select"), \
         patch("app.service.domain.domain_enquiry_service.selectinload"):
        result = await service.remove_enquiry(
            enquiry.id,
            admin=admin,
            admin_notes="Removed from queue",
        )

    assert enquiry.is_deleted is True
    assert enquiry.deleted_at is not None
    assert enquiry.deleted_by == admin.id
    assert enquiry.admin_notes == "Removed from queue"
    assert result["success"] is True
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_allows_after_admin_reopen_to_pending():
    listing_id = uuid.uuid4()
    enquirer = _admin_user()
    listing = SimpleNamespace(
        id=listing_id,
        listed_by_user_id=uuid.uuid4(),
        asking_price=600000.0,
        domain_status=DomainListingStatus.AVAILABLE,
    )
    reopened = _enquiry_row(
        domain_listing_id=listing_id,
        enquirer_user_id=enquirer.id,
        status=DomainEnquiryStatus.PENDING.value,
        completed_at=datetime.now(timezone.utc),
        message="Old buyer message",
        full_name="Buyer",
    )
    created = SimpleNamespace(
        id=uuid.uuid4(),
        domain_listing_id=listing_id,
        status=DomainEnquiryStatus.PENDING.value,
        full_name="Buyer",
        email="buyer@example.com",
        phone=None,
        message="Fresh enquiry",
        created_at=datetime.now(timezone.utc),
    )

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    listings_repo = MagicMock()
    listings_repo.get_by_id = AsyncMock(return_value=listing)
    listings_repo.save = AsyncMock(return_value=listing)

    no_pipeline = MagicMock()
    no_pipeline.scalar_one_or_none.return_value = None
    no_other = MagicMock()
    no_other.scalar_one_or_none.return_value = None
    existing_active = MagicMock()
    existing_active.scalar_one_or_none.return_value = reopened
    session.execute = AsyncMock(side_effect=[no_pipeline, no_other, existing_active])

    service = DomainEnquiryService(session)
    service._listings = listings_repo

    with patch("app.service.domain.domain_enquiry_service.select"), \
         patch.object(DomainEnquiryService, "_not_deleted_filter", return_value=True), \
         patch("app.service.domain.domain_enquiry_service.DomainEnquiry", return_value=created):
        result = await service.submit(
            listing_id,
            enquirer=enquirer,
            full_name="Buyer",
            email="buyer@example.com",
            phone=None,
            message="Fresh enquiry",
        )

    assert reopened.is_deleted is True
    assert result["status"] == DomainEnquiryStatus.PENDING.value
    assert listing.domain_status == DomainListingStatus.UNDER_REVIEW
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_status_rejects_invalid_transition_from_completed():
    admin = _admin_user()
    enquiry = _enquiry_row(status=DomainEnquiryStatus.COMPLETED.value)
    session = _mock_session_with_enquiry(enquiry)
    service = DomainEnquiryService(session)

    with patch("app.service.domain.domain_enquiry_service.select"), \
         patch("app.service.domain.domain_enquiry_service.selectinload"):
        with pytest.raises(AppException, match="Transition not allowed"):
            await service.update_status(
                enquiry.id,
                admin=admin,
                status=DomainEnquiryStatus.DECLINED.value,
            )

    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_blocks_when_pending_exists():
    listing_id = uuid.uuid4()
    enquirer = _admin_user()
    existing = _enquiry_row(
        domain_listing_id=listing_id,
        enquirer_user_id=enquirer.id,
        status=DomainEnquiryStatus.PENDING.value,
    )
    listing = SimpleNamespace(
        id=listing_id,
        listed_by_user_id=uuid.uuid4(),
        asking_price=600000.0,
        domain_status=DomainListingStatus.AVAILABLE,
    )

    session = MagicMock()
    listings_repo = MagicMock()
    listings_repo.get_by_id = AsyncMock(return_value=listing)

    no_pipeline = MagicMock()
    no_pipeline.scalar_one_or_none.return_value = None
    no_other = MagicMock()
    no_other.scalar_one_or_none.return_value = None
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = existing
    session.execute = AsyncMock(side_effect=[no_pipeline, no_other, existing_result])

    service = DomainEnquiryService(session)
    service._listings = listings_repo

    with patch("app.service.domain.domain_enquiry_service.select"), \
         patch.object(DomainEnquiryService, "_not_deleted_filter", return_value=True):
        with pytest.raises(AppException, match="already submitted"):
            await service.submit(
                listing_id,
                enquirer=enquirer,
                full_name="Buyer",
                email="buyer@example.com",
                phone=None,
                message=None,
            )


@pytest.mark.asyncio
async def test_submit_allows_after_declined():
    listing_id = uuid.uuid4()
    enquirer = _admin_user()
    listing = SimpleNamespace(
        id=listing_id,
        listed_by_user_id=uuid.uuid4(),
        asking_price=600000.0,
        domain_status=DomainListingStatus.AVAILABLE,
    )
    created = SimpleNamespace(
        id=uuid.uuid4(),
        domain_listing_id=listing_id,
        status=DomainEnquiryStatus.PENDING.value,
        full_name="Buyer",
        email="buyer@example.com",
        phone=None,
        message=None,
        created_at=datetime.now(timezone.utc),
    )

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    listings_repo = MagicMock()
    listings_repo.get_by_id = AsyncMock(return_value=listing)
    listings_repo.save = AsyncMock(return_value=listing)

    no_pipeline = MagicMock()
    no_pipeline.scalar_one_or_none.return_value = None
    no_other = MagicMock()
    no_other.scalar_one_or_none.return_value = None
    no_active_result = MagicMock()
    no_active_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(side_effect=[no_pipeline, no_other, no_active_result])

    service = DomainEnquiryService(session)
    service._listings = listings_repo

    with patch("app.service.domain.domain_enquiry_service.select"), \
         patch.object(DomainEnquiryService, "_not_deleted_filter", return_value=True), \
         patch("app.service.domain.domain_enquiry_service.DomainEnquiry", return_value=created):
        result = await service.submit(
            listing_id,
            enquirer=enquirer,
            full_name="Buyer",
            email="buyer@example.com",
            phone=None,
            message=None,
        )

    session.add.assert_called_once()
    session.commit.assert_awaited_once()
    assert listing.domain_status == DomainListingStatus.UNDER_REVIEW
    assert result["status"] == DomainEnquiryStatus.PENDING.value


@pytest.mark.asyncio
async def test_submit_allows_after_completed():
    listing_id = uuid.uuid4()
    enquirer = _admin_user()
    listing = SimpleNamespace(
        id=listing_id,
        listed_by_user_id=uuid.uuid4(),
        asking_price=600000.0,
        domain_status=DomainListingStatus.AVAILABLE,
    )
    created = SimpleNamespace(
        id=uuid.uuid4(),
        domain_listing_id=listing_id,
        status=DomainEnquiryStatus.PENDING.value,
        full_name="Buyer",
        email="buyer@example.com",
        phone=None,
        message=None,
        created_at=datetime.now(timezone.utc),
    )

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    listings_repo = MagicMock()
    listings_repo.get_by_id = AsyncMock(return_value=listing)
    listings_repo.save = AsyncMock(return_value=listing)

    no_pipeline = MagicMock()
    no_pipeline.scalar_one_or_none.return_value = None
    no_other = MagicMock()
    no_other.scalar_one_or_none.return_value = None
    no_active_result = MagicMock()
    no_active_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(side_effect=[no_pipeline, no_other, no_active_result])

    service = DomainEnquiryService(session)
    service._listings = listings_repo

    with patch("app.service.domain.domain_enquiry_service.select"), \
         patch.object(DomainEnquiryService, "_not_deleted_filter", return_value=True), \
         patch("app.service.domain.domain_enquiry_service.DomainEnquiry", return_value=created):
        result = await service.submit(
            listing_id,
            enquirer=enquirer,
            full_name="Buyer",
            email="buyer@example.com",
            phone=None,
            message=None,
        )

    session.add.assert_called_once()
    session.commit.assert_awaited_once()
    assert listing.domain_status == DomainListingStatus.UNDER_REVIEW
    assert result["status"] == DomainEnquiryStatus.PENDING.value
