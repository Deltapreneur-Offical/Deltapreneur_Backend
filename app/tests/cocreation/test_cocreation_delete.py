from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import AppException
from app.entity.user.user_role import UserRole
from app.service.cocreation.cocreation_service import CocreationService


class FakeSession:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True


class FakeSoftwareRepo:
    def __init__(self, software):
        self.software = software
        self.saved = None

    async def get_by_id(self, _software_id):
        return self.software

    async def save(self, software):
        self.saved = software
        return software


class FakeAuctionRepo:
    def __init__(self):
        self.deleted_software_ids = []

    async def delete_by_software_id(self, software_id):
        self.deleted_software_ids.append(software_id)
        return 1


def _service(software):
    service = CocreationService.__new__(CocreationService)
    service._session = FakeSession()
    service._repo = FakeSoftwareRepo(software)
    service._auction_repo = FakeAuctionRepo()
    return service


@pytest.mark.asyncio
async def test_delete_software_removes_related_auction_first():
    owner_id = uuid4()
    software = SimpleNamespace(
        id=uuid4(),
        listed_by_user_id=owner_id,
        is_deleted=False,
        deleted_at=None,
        deleted_by=None,
        updated_at=None,
    )
    actor = SimpleNamespace(id=owner_id)
    service = _service(software)

    await service.delete_software(software.id, actor=actor)

    assert service._auction_repo.deleted_software_ids == [software.id]
    assert software.is_deleted is True
    assert software.deleted_by == actor.id
    assert service._repo.saved is software
    assert service._session.committed is True


@pytest.mark.asyncio
async def test_delete_software_allows_admin_to_delete_any_listing():
    owner_id = uuid4()
    admin_id = uuid4()
    software = SimpleNamespace(
        id=uuid4(),
        listed_by_user_id=owner_id,
        is_deleted=False,
        deleted_at=None,
        deleted_by=None,
        updated_at=None,
    )
    actor = SimpleNamespace(id=admin_id, role=UserRole.ADMIN)
    service = _service(software)

    await service.delete_software(software.id, actor=actor)

    assert service._auction_repo.deleted_software_ids == [software.id]
    assert software.is_deleted is True
    assert software.deleted_by == admin_id
    assert service._session.committed is True


@pytest.mark.asyncio
async def test_delete_software_rejects_non_owner_non_admin():
    software = SimpleNamespace(
        id=uuid4(),
        listed_by_user_id=uuid4(),
    )
    actor = SimpleNamespace(id=uuid4(), role=UserRole.USER)
    service = _service(software)

    with pytest.raises(AppException) as exc:
        await service.delete_software(software.id, actor=actor)

    assert exc.value.status_code == 403
    assert service._auction_repo.deleted_software_ids == []
    assert service._session.committed is False
