from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AppException
from app.service.cocreation.cocreation_payment_service import CocreationPaymentService
from app.service.cocreation.cocreation_service import CocreationService
from app.service.cocreation.software_auction_service import SoftwareAuctionService
from app.utils.cocreation_enums import (
    SoftwareAuctionApprovalStatus,
    SoftwareAuctionDuration,
    SoftwarePurchaseType,
    SoftwareStatus,
)
from app.entity.user.user_role import UserRole
from app.utils.enums import AuctionStatus


@pytest.mark.asyncio
async def test_create_auction_sets_software_pending() -> None:
    lister_id = uuid.uuid4()
    software_id = uuid.uuid4()
    software = SimpleNamespace(
        id=software_id,
        listed_by_user_id=lister_id,
        purchase_type=SoftwarePurchaseType.ONE_TIME,
        software_status=SoftwareStatus.AVAILABLE,
    )
    lister = SimpleNamespace(id=lister_id, role=UserRole.USER)

    class _SoftwareRepo:
        async def get_by_id(self, sid):
            return software if sid == software_id else None

        async def save(self, row):
            return row

    class _AuctionRepo:
        def __init__(self):
            self.created = None

        async def get_by_software_id(self, _sid):
            return None

        async def create(self, auction):
            self.created = auction
            auction.id = uuid.uuid4()
            return auction

        async def get_by_software_id_after(self, _sid):
            return self.created

    auction_repo = _AuctionRepo()
    session = MagicMock()
    session.commit = AsyncMock()

    service = SoftwareAuctionService(session)
    service._software = _SoftwareRepo()
    service._auctions = auction_repo
    service._session = session

    service._fee_service = SimpleNamespace(
        consume_creation_fee=AsyncMock(),
    )

    await service.create_auction(
        software_id,
        min_bid_price=1000.0,
        duration=SoftwareAuctionDuration.SEVEN_DAYS,
        auction_rationale="Test rationale for admin review.",
        lister=lister,
        creation_fee_order_id="order_test_creation_fee",
    )

    assert software.software_status == SoftwareStatus.PENDING
    assert software.purchase_type == SoftwarePurchaseType.AUCTION
    assert auction_repo.created.approval_status == SoftwareAuctionApprovalStatus.PENDING_APPROVAL


@pytest.mark.asyncio
async def test_list_all_excludes_pending_software() -> None:
    pending = SimpleNamespace(
        id=uuid.uuid4(),
        software_status=SoftwareStatus.PENDING,
        purchase_type=SoftwarePurchaseType.ONE_TIME,
    )
    available = SimpleNamespace(
        id=uuid.uuid4(),
        software_status=SoftwareStatus.AVAILABLE,
        purchase_type=SoftwarePurchaseType.ONE_TIME,
    )
    legacy_auction = SimpleNamespace(
        id=uuid.uuid4(),
        software_status=SoftwareStatus.AVAILABLE,
        purchase_type=SoftwarePurchaseType.AUCTION,
    )
    live_auction = SimpleNamespace(
        id=uuid.uuid4(),
        software_status=SoftwareStatus.AVAILABLE,
        purchase_type=SoftwarePurchaseType.AUCTION,
    )

    class _Repo:
        async def list_all_active(self):
            return [pending, available, legacy_auction, live_auction]

    class _AuctionRepo:
        async def map_by_software_ids(self, software_ids):
            return {
                legacy_auction.id: SimpleNamespace(
                    approval_status=SoftwareAuctionApprovalStatus.PENDING_APPROVAL,
                ),
                live_auction.id: SimpleNamespace(
                    approval_status=SoftwareAuctionApprovalStatus.APPROVED,
                ),
            }

    service = CocreationService(MagicMock())
    service._repo = _Repo()
    service._auction_repo = _AuctionRepo()
    rows = await service.list_all()
    assert rows == [available, live_auction]


@pytest.mark.asyncio
async def test_create_purchase_order_rejects_auction_listing() -> None:
    buyer_id = uuid.uuid4()
    software = SimpleNamespace(
        id=uuid.uuid4(),
        listed_by_user_id=uuid.uuid4(),
        software_status=SoftwareStatus.AVAILABLE,
        purchase_type=SoftwarePurchaseType.AUCTION,
        price=5000.0,
        verified=True,
    )
    buyer = SimpleNamespace(id=buyer_id)

    class _SoftwareRepo:
        async def get_by_id(self, _sid):
            return software

    class _PurchaseRepo:
        async def has_completed_purchase(self, *_args):
            return False

    service = CocreationPaymentService(MagicMock())
    service._software_repo = _SoftwareRepo()
    service._purchase_repo = _PurchaseRepo()

    with pytest.raises(AppException) as exc:
        await service.create_purchase_order(software.id, buyer=buyer)
    assert exc.value.status_code == 400
    assert "auction" in exc.value.message.lower()
