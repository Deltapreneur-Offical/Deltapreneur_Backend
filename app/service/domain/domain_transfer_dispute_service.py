"""Dispute resolution for domain transfers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.user.app_user import AppUser
from app.repository.domain_dispute_repository import DomainDisputeRepository
from app.repository.domain_marketplace_transaction_repository import (
    DomainMarketplaceTransactionRepository,
)
from app.service.domain.domain_transfer_escrow_service import DomainTransferEscrowService
from app.service.domain.domain_transfer_event_service import DomainTransferEventService
from app.service.domain.domain_transfer_payout_service import DomainTransferPayoutService
from app.utils.transfer_enums import (
    MarketplaceTransferStatus,
    TransferDisputeStatus,
    TransferEventType,
)


class DomainTransferDisputeService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DomainMarketplaceTransactionRepository(session)
        self._disputes = DomainDisputeRepository(session)
        self._events = DomainTransferEventService(session)
        self._escrow = DomainTransferEscrowService(session)
        self._payout = DomainTransferPayoutService(session)

    async def resolve(
        self,
        tx_id: uuid.UUID,
        dispute_id: uuid.UUID,
        *,
        admin: AppUser,
        resolution: Literal["refund", "payout"],
        note: str | None = None,
    ) -> dict:
        tx = await self._repo.get_by_id(tx_id)
        if tx is None:
            raise AppException("Transfer transaction not found.", status_code=404)
        dispute = await self._disputes.get_by_id(dispute_id)
        if dispute is None or dispute.transaction_id != tx_id:
            raise AppException("Dispute not found.", status_code=404)
        if dispute.status not in ("OPEN", "UNDER_REVIEW"):
            raise AppException("Dispute is already resolved.", status_code=400)

        now = datetime.now(timezone.utc)
        dispute.status = "RESOLVED_REFUND" if resolution == "refund" else "RESOLVED_PAYOUT"
        dispute.resolution_note = (note or "").strip() or None
        dispute.resolved_by_user_id = admin.id
        dispute.resolved_at = now
        await self._disputes.save(dispute)
        tx.dispute_status = (
            TransferDisputeStatus.RESOLVED_REFUND
            if resolution == "refund"
            else TransferDisputeStatus.RESOLVED_PAYOUT
        )
        await self._repo.save(tx)
        await self._events.log(
            tx.id,
            TransferEventType.DISPUTE_RESOLVED,
            actor_user_id=admin.id,
            actor_role="ADMIN",
            payload={"resolution": resolution},
        )
        await self._session.commit()

        if resolution == "refund":
            return await self._escrow.refund(tx_id, admin=admin, note=note)
        if tx.transfer_status not in (
            MarketplaceTransferStatus.TRANSFER_COMPLETED,
            MarketplaceTransferStatus.PAYOUT_PENDING,
            MarketplaceTransferStatus.PAYOUT_APPROVED,
        ):
            locked = await self._repo.get_by_id_for_update(tx_id)
            if locked:
                locked.transfer_status = MarketplaceTransferStatus.TRANSFER_COMPLETED
                await self._repo.save(locked)
                await self._session.commit()
        await self._payout.approve_payout(tx_id, admin=admin)
        return await self._payout.release_payout(tx_id, admin=admin)
