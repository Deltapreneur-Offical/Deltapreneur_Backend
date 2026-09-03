"""Technology listing verification gate before purchase."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AppException
from app.service.cocreation.cocreation_payment_service import CocreationPaymentService
from app.utils.cocreation_enums import SoftwarePurchaseType, SoftwareStatus


@pytest.mark.asyncio
async def test_create_purchase_order_blocks_unverified_listing(monkeypatch):
    software = MagicMock()
    software.id = uuid.uuid4()
    software.listed_by_user_id = uuid.uuid4()
    software.verified = False
    software.software_status = SoftwareStatus.AVAILABLE
    software.purchase_type = SoftwarePurchaseType.ONE_TIME
    software.price = 100.0

    session = AsyncMock()
    service = CocreationPaymentService(session)
    service._software_repo = AsyncMock()
    service._software_repo.get_by_id = AsyncMock(return_value=software)
    service._purchase_repo = AsyncMock()
    service._purchase_repo.has_completed_purchase = AsyncMock(return_value=False)

    buyer = MagicMock()
    buyer.id = uuid.uuid4()

    monkeypatch.setattr(
        "app.service.cocreation.cocreation_payment_service.settings.REQUIRE_TECHNOLOGY_VERIFICATION_BEFORE_PURCHASE",
        True,
    )

    with pytest.raises(AppException, match="not verified"):
        await service.create_purchase_order(software.id, buyer=buyer)
