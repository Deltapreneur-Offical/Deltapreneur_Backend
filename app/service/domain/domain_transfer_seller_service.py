"""Seller-side transfer workflow."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.entity.user.app_user import AppUser
from app.integrations.s3.upload_service import upload_image
from app.repository.domain_marketplace_transaction_repository import (
    DomainMarketplaceTransactionRepository,
)
from app.service.domain.domain_transfer_event_service import DomainTransferEventService
from app.service.domain.domain_transfer_notification_service import (
    DomainTransferNotificationService,
)
from app.service.security.auth_code_encryption_service import encrypt_secret
from app.utils.transfer_enums import MarketplaceTransferStatus, TransferEventType


class DomainTransferSellerService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DomainMarketplaceTransactionRepository(session)
        self._events = DomainTransferEventService(session)
        self._notify = DomainTransferNotificationService(session)

    async def submit_auth_code(
        self,
        tx_id: uuid.UUID,
        *,
        seller: AppUser,
        registrar_name: str,
        auth_code: str,
        proof_file: UploadFile | None = None,
    ) -> None:
        tx = await self._repo.get_by_id_for_update(tx_id)
        if tx is None:
            raise AppException("Transfer transaction not found.", status_code=404)
        if tx.seller_id != seller.id:
            raise AppException("Forbidden.", status_code=403)
        if tx.transfer_status not in (
            MarketplaceTransferStatus.AWAITING_AUTH_CODE,
            MarketplaceTransferStatus.ADMIN_REVIEW_REQUIRED,
        ):
            raise AppException("Auth code cannot be submitted in the current state.", status_code=400)

        code = (auth_code or "").strip()
        if len(code) < 4:
            raise AppException("Auth code is too short.", status_code=400)

        tx.seller_registrar_name = (registrar_name or "").strip() or None
        tx.auth_code_ciphertext = encrypt_secret(code)
        tx.auth_code_submitted_at = datetime.now(timezone.utc)
        tx.transfer_status = MarketplaceTransferStatus.AUTH_CODE_AVAILABLE
        tx.buyer_deadline_at = datetime.now(timezone.utc) + timedelta(
            days=settings.DOMAIN_TRANSFER_BUYER_DEADLINE_DAYS,
        )

        if proof_file is not None:
            url = await upload_image(file=proof_file, folder=f"domain-transfer-proofs/{tx_id}")
            tx.proof_storage_key = url

        await self._repo.save(tx)
        await self._events.log(
            tx.id,
            TransferEventType.AUTH_SUBMITTED,
            actor_user_id=seller.id,
            actor_role="SELLER",
            payload={"registrar": tx.seller_registrar_name},
        )
        await self._notify.on_auth_code_available(tx)
        await self._session.commit()

    async def upload_proof(
        self,
        tx_id: uuid.UUID,
        *,
        seller: AppUser,
        proof_file: UploadFile,
    ) -> None:
        tx = await self._repo.get_by_id_for_update(tx_id)
        if tx is None:
            raise AppException("Transfer transaction not found.", status_code=404)
        if tx.seller_id != seller.id:
            raise AppException("Forbidden.", status_code=403)
        url = await upload_image(file=proof_file, folder=f"domain-transfer-proofs/{tx_id}")
        tx.proof_storage_key = url
        await self._repo.save(tx)
        await self._session.commit()
