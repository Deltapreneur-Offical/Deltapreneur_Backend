"""Buyer-side domain transfer workflow (Path A / Path B)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.user.app_user import AppUser
from app.integrations.s3.upload_service import upload_image
from app.repository.domain_dispute_repository import DomainDisputeRepository
from app.repository.domain_marketplace_transaction_repository import (
    DomainMarketplaceTransactionRepository,
)
from app.service.auth.transfer_auth_reveal_otp_service import TransferAuthRevealOtpService
from app.service.domain.domain_transfer_event_service import DomainTransferEventService
from app.service.domain.domain_transfer_instruction_service import get_transfer_instructions
from app.service.domain.domain_transfer_notification_service import (
    DomainTransferNotificationService,
)
from app.service.security.auth_code_encryption_service import decrypt_secret
from app.utils.transfer_enums import (
    DisputeReason,
    MarketplaceTransferStatus,
    TransferDisputeStatus,
    TransferEventType,
    TransferMethod,
    TransferVerifiedBy,
)
from app.entity.domain.domain_dispute_entity import DomainDispute, DomainDisputeEvidence


class DomainTransferBuyerService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DomainMarketplaceTransactionRepository(session)
        self._disputes = DomainDisputeRepository(session)
        self._events = DomainTransferEventService(session)
        self._otp = TransferAuthRevealOtpService()
        self._notify = DomainTransferNotificationService(session)

    async def choose_self_transfer(
        self,
        tx_id: uuid.UUID,
        *,
        buyer: AppUser,
        buyer_target_registrar: str,
    ) -> None:
        tx = await self._repo.get_by_id_for_update(tx_id)
        if tx is None:
            raise AppException("Transfer transaction not found.", status_code=404)
        if tx.buyer_id != buyer.id:
            raise AppException("Forbidden.", status_code=403)
        if tx.transfer_status not in (
            MarketplaceTransferStatus.AUTH_CODE_AVAILABLE,
            MarketplaceTransferStatus.AUTH_CODE_RECEIVED,
            MarketplaceTransferStatus.AUTH_CODE_VIEWED,
        ):
            raise AppException("Cannot choose transfer path in the current state.", status_code=400)
        tx.transfer_method = TransferMethod.SELF
        tx.buyer_target_registrar = (buyer_target_registrar or "").strip() or None
        await self._repo.save(tx)
        await self._events.log(
            tx.id,
            TransferEventType.TRANSFER_STARTED,
            actor_user_id=buyer.id,
            actor_role="BUYER",
            payload={"transferMethod": TransferMethod.SELF.value},
        )
        await self._session.commit()

    async def request_assistance(self, tx_id: uuid.UUID, *, buyer: AppUser) -> None:
        tx = await self._repo.get_by_id_for_update(tx_id)
        if tx is None:
            raise AppException("Transfer transaction not found.", status_code=404)
        if tx.buyer_id != buyer.id:
            raise AppException("Forbidden.", status_code=403)
        if tx.transfer_status not in (
            MarketplaceTransferStatus.AUTH_CODE_AVAILABLE,
            MarketplaceTransferStatus.AUTH_CODE_RECEIVED,
            MarketplaceTransferStatus.AUTH_CODE_VIEWED,
            MarketplaceTransferStatus.TRANSFER_IN_PROGRESS,
        ):
            raise AppException("Cannot request assistance in the current state.", status_code=400)
        tx.transfer_method = TransferMethod.COBROTHER_ASSISTED
        tx.assistance_requested_at = datetime.now(timezone.utc)
        await self._repo.save(tx)
        await self._events.log(
            tx.id,
            TransferEventType.ASSISTANCE_REQUESTED,
            actor_user_id=buyer.id,
            actor_role="BUYER",
        )
        await self._session.commit()

    async def get_instructions(self, tx_id: uuid.UUID, *, buyer: AppUser) -> dict:
        tx = await self._repo.get_by_id(tx_id)
        if tx is None:
            raise AppException("Transfer transaction not found.", status_code=404)
        if tx.buyer_id != buyer.id:
            raise AppException("Forbidden.", status_code=403)
        registrar = tx.buyer_target_registrar or tx.seller_registrar_name or ""
        return get_transfer_instructions(registrar)

    async def send_reveal_otp(self, tx_id: uuid.UUID, *, buyer: AppUser) -> None:
        tx = await self._repo.get_by_id(tx_id)
        if tx is None:
            raise AppException("Transfer transaction not found.", status_code=404)
        if tx.buyer_id != buyer.id:
            raise AppException("Forbidden.", status_code=403)
        if not tx.auth_code_ciphertext:
            raise AppException("Auth code is not available yet.", status_code=400)
        if tx.transfer_status not in (
            MarketplaceTransferStatus.AUTH_CODE_AVAILABLE,
            MarketplaceTransferStatus.AUTH_CODE_RECEIVED,
            MarketplaceTransferStatus.AUTH_CODE_VIEWED,
            MarketplaceTransferStatus.TRANSFER_IN_PROGRESS,
        ):
            raise AppException("Auth code cannot be revealed in the current state.", status_code=400)
        await self._otp.send_otp(tx_id, buyer)

    async def verify_reveal_otp(
        self,
        tx_id: uuid.UUID,
        *,
        buyer: AppUser,
        otp: str,
    ) -> str:
        tx = await self._repo.get_by_id_for_update(tx_id)
        if tx is None:
            raise AppException("Transfer transaction not found.", status_code=404)
        if tx.buyer_id != buyer.id:
            raise AppException("Forbidden.", status_code=403)
        if not tx.auth_code_ciphertext:
            raise AppException("Auth code is not available yet.", status_code=400)
        await self._otp.verify_otp(tx_id, buyer, otp)
        try:
            plain = decrypt_secret(tx.auth_code_ciphertext, version=tx.auth_code_key_version)
        except ValueError as exc:
            raise AppException(
                "Unable to decrypt auth code. Please contact support.",
                status_code=503,
            ) from exc
        now = datetime.now(timezone.utc)
        if tx.auth_code_viewed_at is None:
            tx.auth_code_viewed_at = now
        if tx.transfer_status in (
            MarketplaceTransferStatus.AUTH_CODE_AVAILABLE,
            MarketplaceTransferStatus.AUTH_CODE_RECEIVED,
        ):
            tx.transfer_status = MarketplaceTransferStatus.AUTH_CODE_VIEWED
        await self._repo.save(tx)
        await self._events.log(
            tx.id,
            TransferEventType.OTP_REVEAL,
            actor_user_id=buyer.id,
            actor_role="BUYER",
        )
        await self._session.commit()
        return plain

    async def mark_transfer_started(self, tx_id: uuid.UUID, *, buyer: AppUser) -> None:
        tx = await self._repo.get_by_id_for_update(tx_id)
        if tx is None:
            raise AppException("Transfer transaction not found.", status_code=404)
        if tx.buyer_id != buyer.id:
            raise AppException("Forbidden.", status_code=403)
        if tx.transfer_status not in (
            MarketplaceTransferStatus.AUTH_CODE_VIEWED,
            MarketplaceTransferStatus.AUTH_CODE_AVAILABLE,
            MarketplaceTransferStatus.AUTH_CODE_RECEIVED,
        ):
            raise AppException("Cannot start transfer in the current state.", status_code=400)
        tx.transfer_status = MarketplaceTransferStatus.TRANSFER_IN_PROGRESS
        tx.transfer_started_at = datetime.now(timezone.utc)
        await self._repo.save(tx)
        await self._events.log(
            tx.id,
            TransferEventType.TRANSFER_STARTED,
            actor_user_id=buyer.id,
            actor_role="BUYER",
        )
        await self._session.commit()

    async def confirm_transfer(self, tx_id: uuid.UUID, *, buyer: AppUser) -> None:
        tx = await self._repo.get_by_id_for_update(tx_id)
        if tx is None:
            raise AppException("Transfer transaction not found.", status_code=404)
        if tx.buyer_id != buyer.id:
            raise AppException("Forbidden.", status_code=403)
        if tx.transfer_status not in (
            MarketplaceTransferStatus.TRANSFER_IN_PROGRESS,
            MarketplaceTransferStatus.AUTH_CODE_VIEWED,
        ):
            raise AppException("Cannot confirm transfer in the current state.", status_code=400)
        now = datetime.now(timezone.utc)
        tx.transfer_confirmed_at = now
        tx.transfer_verified_at = now
        tx.transfer_verified_by = TransferVerifiedBy.BUYER
        tx.transfer_status = MarketplaceTransferStatus.PAYOUT_PENDING
        await self._repo.save(tx)
        await self._events.log(
            tx.id,
            TransferEventType.TRANSFER_CONFIRMED,
            actor_user_id=buyer.id,
            actor_role="BUYER",
        )
        await self._events.log(
            tx.id,
            TransferEventType.PAYOUT_PENDING,
            actor_role="SYSTEM",
            payload={"reason": "Transfer confirmed; seller payout is ready for admin review."},
        )
        await self._session.commit()

    async def open_dispute(
        self,
        tx_id: uuid.UUID,
        *,
        buyer: AppUser,
        reason: DisputeReason,
        description: str | None,
        evidence_file: UploadFile | None = None,
    ) -> None:
        tx = await self._repo.get_by_id_for_update(tx_id)
        if tx is None:
            raise AppException("Transfer transaction not found.", status_code=404)
        if tx.buyer_id != buyer.id:
            raise AppException("Forbidden.", status_code=403)
        if tx.transfer_status in (
            MarketplaceTransferStatus.SELLER_PAID,
            MarketplaceTransferStatus.PAYOUT_RELEASED,
            MarketplaceTransferStatus.COMPLETED,
            MarketplaceTransferStatus.REFUNDED,
            MarketplaceTransferStatus.CANCELLED,
        ):
            raise AppException("Cannot open a dispute for a closed transaction.", status_code=400)
        existing = await self._disputes.get_open_by_transaction(tx_id)
        if existing is not None:
            raise AppException("A dispute is already open for this transaction.", status_code=409)
        dispute = DomainDispute(
            transaction_id=tx_id,
            opened_by_user_id=buyer.id,
            reason=reason,
            description=(description or "").strip() or None,
            status="OPEN",
        )
        dispute = await self._disputes.create(dispute)
        if evidence_file is not None:
            url = await upload_image(file=evidence_file, folder=f"domain-disputes/{dispute.id}")
            await self._disputes.add_evidence(
                DomainDisputeEvidence(
                    dispute_id=dispute.id,
                    uploaded_by_user_id=buyer.id,
                    storage_key=url,
                    mime_type=evidence_file.content_type,
                ),
            )
        tx.dispute_status = TransferDisputeStatus.OPEN
        tx.transfer_status = MarketplaceTransferStatus.DISPUTED
        await self._repo.save(tx)
        await self._events.log(
            tx.id,
            TransferEventType.DISPUTE_OPENED,
            actor_user_id=buyer.id,
            actor_role="BUYER",
            payload={"reason": reason.value},
        )
        await self._session.commit()
