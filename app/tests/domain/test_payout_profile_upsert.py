"""Payout profile upsert edge cases."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.exceptions import AppException
from app.entity.payout.seller_payout_profile_entity import SellerPayoutProfile
from app.service.payout.seller_payout_profile_service import SellerPayoutProfileService
from app.utils.transfer_enums import PayoutMethod


class _CaptureSession:
    def __init__(self) -> None:
        self.added = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        return None


class _EmptyProfileRepo:
    def __init__(self) -> None:
        self.saved: SellerPayoutProfile | None = None

    async def get_by_user_id(self, _user_id):
        return None

    async def save(self, profile: SellerPayoutProfile) -> SellerPayoutProfile:
        self.saved = profile
        return profile


@pytest.mark.asyncio
async def test_upsert_profile_creates_new_profile_when_none_exists():
    session = _CaptureSession()
    repo = _EmptyProfileRepo()
    service = SellerPayoutProfileService(session)  # type: ignore[arg-type]
    service._repo = repo  # type: ignore[method-assign]

    user = SimpleNamespace(id=uuid.uuid4())
    result = await service.upsert_profile(
        user,
        payout_method=PayoutMethod.UPI.value,
        upi_id="seller@upi",
    )

    assert repo.saved is not None
    assert result["payoutMethod"] == PayoutMethod.UPI.value
    assert result["isComplete"] is True


@pytest.mark.asyncio
async def test_upsert_profile_normalizes_bank_account_alias():
    session = _CaptureSession()
    repo = _EmptyProfileRepo()
    service = SellerPayoutProfileService(session)  # type: ignore[arg-type]
    service._repo = repo  # type: ignore[method-assign]

    user = SimpleNamespace(id=uuid.uuid4())
    result = await service.upsert_profile(
        user,
        payout_method="bank_account",
        account_holder_name="Rohit Seller",
        bank_name="HDFC Bank",
        bank_account_number="1234567890",
        confirm_bank_account_number="1234567890",
        bank_ifsc="HDFC0001234",
    )

    assert repo.saved is not None
    assert result["payoutMethod"] == PayoutMethod.BANK_ACCOUNT.value
    assert result["isComplete"] is True


@pytest.mark.asyncio
async def test_upsert_profile_rejects_invalid_payout_method():
    session = _CaptureSession()
    repo = _EmptyProfileRepo()
    service = SellerPayoutProfileService(session)  # type: ignore[arg-type]
    service._repo = repo  # type: ignore[method-assign]

    user = SimpleNamespace(id=uuid.uuid4())
    with pytest.raises(AppException) as exc:
        await service.upsert_profile(user, payout_method="cash", upi_id="seller@upi")
    assert exc.value.status_code == 400
