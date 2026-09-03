"""Public venture catalog is gated on admin listing approval."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import AppException
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.service.venture.venture_service import VentureService
from app.utils.venture_enums import VentureListingApprovalStatus


def _venture(
    *,
    listing_approval_status: VentureListingApprovalStatus,
    lister_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        taken_down=False,
        status=True,
        listing_approval_status=listing_approval_status,
        gstin_verified=listing_approval_status == VentureListingApprovalStatus.APPROVED,
        listed_by_user_id=lister_id,
        is_deleted=False,
    )


@pytest.mark.asyncio
async def test_list_all_returns_only_gstin_verified() -> None:
    verified = _venture(listing_approval_status=VentureListingApprovalStatus.APPROVED)
    pending = _venture(listing_approval_status=VentureListingApprovalStatus.PENDING_APPROVAL)

    class _Repo:
        async def list_all(self):
            return [verified]

    service = VentureService(MagicMock())
    service._repo = _Repo()
    rows = await service.list_all()
    assert rows == [verified]
    assert pending not in rows


@pytest.mark.asyncio
async def test_get_venture_for_viewer_hides_unverified_from_anonymous() -> None:
    venture = _venture(listing_approval_status=VentureListingApprovalStatus.PENDING_APPROVAL)

    class _Repo:
        async def get_by_id(self, venture_id, *, load_roles=True):  # noqa: ANN001, ARG002
            return venture

    class _Acquisitions:
        async def get_active_applicant_user_id(self, venture_id):  # noqa: ANN001, ARG002
            return None

    service = VentureService(MagicMock())
    service._repo = _Repo()
    service._pitches = _Acquisitions()

    with pytest.raises(AppException) as exc:
        await service.get_venture_for_viewer(venture.id, None)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_venture_for_viewer_allows_owner_on_unverified() -> None:
    owner_id = uuid.uuid4()
    venture = _venture(
        listing_approval_status=VentureListingApprovalStatus.PENDING_APPROVAL,
        lister_id=owner_id,
    )
    owner = AppUser(email="owner@example.com", role=UserRole.USER)
    owner.id = owner_id

    class _Repo:
        async def get_by_id(self, venture_id, *, load_roles=True):  # noqa: ANN001, ARG002
            return venture

    class _Acquisitions:
        async def get_active_applicant_user_id(self, venture_id):  # noqa: ANN001, ARG002
            return None

    service = VentureService(MagicMock())
    service._repo = _Repo()
    service._pitches = _Acquisitions()

    result = await service.get_venture_for_viewer(venture.id, owner)
    assert result is venture


@pytest.mark.asyncio
async def test_get_venture_for_viewer_allows_any_user_on_approved_with_active_bid() -> None:
    active_bidder_id = uuid.uuid4()
    venture = _venture(listing_approval_status=VentureListingApprovalStatus.APPROVED)
    viewer = AppUser(email="viewer@example.com", role=UserRole.USER)
    viewer.id = uuid.uuid4()

    class _Repo:
        async def get_by_id(self, venture_id, *, load_roles=True):  # noqa: ANN001, ARG002
            return venture

    class _Acquisitions:
        async def get_active_applicant_user_id(self, venture_id):  # noqa: ANN001, ARG002
            return active_bidder_id

    service = VentureService(MagicMock())
    service._repo = _Repo()
    service._pitches = _Acquisitions()

    result = await service.get_venture_for_viewer(venture.id, viewer)
    assert result is venture


@pytest.mark.asyncio
async def test_get_venture_for_viewer_allows_admin_on_pending() -> None:
    owner_id = uuid.uuid4()
    venture = _venture(
        listing_approval_status=VentureListingApprovalStatus.PENDING_APPROVAL,
        lister_id=owner_id,
    )
    admin = AppUser(email="admin@example.com", role=UserRole.ADMIN)
    admin.id = uuid.uuid4()

    class _Repo:
        async def get_by_id(self, venture_id, *, load_roles=True):  # noqa: ANN001, ARG002
            return venture

    class _Acquisitions:
        async def get_active_applicant_user_id(self, venture_id):  # noqa: ANN001, ARG002
            return None

    service = VentureService(MagicMock())
    service._repo = _Repo()
    service._pitches = _Acquisitions()

    result = await service.get_venture_for_viewer(venture.id, admin)
    assert result is venture
