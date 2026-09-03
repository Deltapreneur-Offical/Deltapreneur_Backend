"""Domain marketplace transfer APIs (seller + buyer)."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.core.exceptions import AppException
from app.entity.user.app_user import AppUser
from app.model.marketplace.transfer_request import (
    ChooseSelfTransferRequest,
    OpenDisputeRequest,
    RevealOtpVerifyRequest,
    SubmitAuthCodeRequest,
)
from app.service.domain.domain_marketplace_transaction_service import (
    DomainMarketplaceTransactionService,
)
from app.service.domain.domain_transfer_buyer_service import DomainTransferBuyerService
from app.service.domain.domain_transfer_event_service import DomainTransferEventService
from app.service.domain.domain_transfer_seller_service import DomainTransferSellerService

router = APIRouter(prefix="/api/v1/domain/transfers", tags=["Domain Transfers"])
logger = logging.getLogger(__name__)


def _tx_service(db: AsyncSession = Depends(get_async_db)) -> DomainMarketplaceTransactionService:
    return DomainMarketplaceTransactionService(db)


def _seller_service(db: AsyncSession = Depends(get_async_db)) -> DomainTransferSellerService:
    return DomainTransferSellerService(db)


def _buyer_service(db: AsyncSession = Depends(get_async_db)) -> DomainTransferBuyerService:
    return DomainTransferBuyerService(db)


def _event_service(db: AsyncSession = Depends(get_async_db)) -> DomainTransferEventService:
    return DomainTransferEventService(db)


@router.get("/seller")
async def list_seller_transfers(
    user: AppUser = Depends(get_current_user),
    service: DomainMarketplaceTransactionService = Depends(_tx_service),
) -> dict:
    from app.repository.domain_marketplace_transaction_repository import (
        DomainMarketplaceTransactionRepository,
    )

    repo = DomainMarketplaceTransactionRepository(service._session)
    rows = await repo.list_by_seller(user.id)
    items = [await service.serialize(tx) for tx in rows]
    return {"items": items}


@router.get("/buyer")
async def list_buyer_transfers(
    user: AppUser = Depends(get_current_user),
    service: DomainMarketplaceTransactionService = Depends(_tx_service),
) -> dict:
    from app.repository.domain_marketplace_transaction_repository import (
        DomainMarketplaceTransactionRepository,
    )

    repo = DomainMarketplaceTransactionRepository(service._session)
    rows = await repo.list_by_buyer(user.id)
    items = [await service.serialize(tx) for tx in rows]
    logger.info(
        "purchases.summary.domain_transfers user=%s count=%s items=%s",
        user.id,
        len(items),
        [{"id": str(x.get("id")), "domainFqdn": x.get("domainFqdn"), "transferStatus": x.get("transferStatus")} for x in items],
    )
    return {"items": items}


@router.get("/{transaction_id}")
async def get_transfer_detail(
    transaction_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    service: DomainMarketplaceTransactionService = Depends(_tx_service),
) -> dict:
    tx = await service.get_for_user(transaction_id, user)
    return await service.serialize(tx)


@router.get("/{transaction_id}/timeline")
async def get_transfer_timeline(
    transaction_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    service: DomainMarketplaceTransactionService = Depends(_tx_service),
    events: DomainTransferEventService = Depends(_event_service),
) -> dict:
    await service.get_for_user(transaction_id, user)
    return {"events": await events.list_timeline(transaction_id)}


@router.post("/{transaction_id}/auth-code")
async def submit_auth_code(
    transaction_id: uuid.UUID,
    body: SubmitAuthCodeRequest,
    user: AppUser = Depends(get_current_user),
    seller: DomainTransferSellerService = Depends(_seller_service),
) -> dict:
    await seller.submit_auth_code(
        transaction_id,
        seller=user,
        registrar_name=body.registrar_name,
        auth_code=body.auth_code,
    )
    return {"success": True}


@router.post("/{transaction_id}/proof")
async def upload_proof(
    transaction_id: uuid.UUID,
    file: UploadFile = File(...),
    user: AppUser = Depends(get_current_user),
    seller: DomainTransferSellerService = Depends(_seller_service),
) -> dict:
    await seller.upload_proof(transaction_id, seller=user, proof_file=file)
    return {"success": True}


@router.post("/{transaction_id}/choose-self-transfer")
async def choose_self_transfer(
    transaction_id: uuid.UUID,
    body: ChooseSelfTransferRequest,
    user: AppUser = Depends(get_current_user),
    buyer: DomainTransferBuyerService = Depends(_buyer_service),
) -> dict:
    await buyer.choose_self_transfer(
        transaction_id,
        buyer=user,
        buyer_target_registrar=body.buyer_target_registrar,
    )
    return {"success": True}


@router.post("/{transaction_id}/request-assistance")
async def request_assistance(
    transaction_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    buyer: DomainTransferBuyerService = Depends(_buyer_service),
) -> dict:
    await buyer.request_assistance(transaction_id, buyer=user)
    return {"success": True}


@router.get("/{transaction_id}/instructions")
async def get_instructions(
    transaction_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    buyer: DomainTransferBuyerService = Depends(_buyer_service),
) -> dict:
    return await buyer.get_instructions(transaction_id, buyer=user)


@router.post("/{transaction_id}/reveal-otp/send")
async def send_reveal_otp(
    transaction_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    buyer: DomainTransferBuyerService = Depends(_buyer_service),
) -> dict:
    await buyer.send_reveal_otp(transaction_id, buyer=user)
    return {"success": True}


@router.post("/{transaction_id}/reveal-otp/verify")
async def verify_reveal_otp(
    transaction_id: uuid.UUID,
    body: RevealOtpVerifyRequest,
    user: AppUser = Depends(get_current_user),
    buyer: DomainTransferBuyerService = Depends(_buyer_service),
    service: DomainMarketplaceTransactionService = Depends(_tx_service),
) -> dict:
    auth_code = await buyer.verify_reveal_otp(transaction_id, buyer=user, otp=body.otp)
    tx = await service.get_for_user(transaction_id, user)
    payload = await service.serialize(tx, include_auth_code=True, auth_code_plain=auth_code)
    return payload


@router.post("/{transaction_id}/transfer-started")
async def mark_transfer_started(
    transaction_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    buyer: DomainTransferBuyerService = Depends(_buyer_service),
) -> dict:
    await buyer.mark_transfer_started(transaction_id, buyer=user)
    return {"success": True}


@router.post("/{transaction_id}/confirm")
async def confirm_transfer(
    transaction_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    buyer: DomainTransferBuyerService = Depends(_buyer_service),
) -> dict:
    await buyer.confirm_transfer(transaction_id, buyer=user)
    return {"success": True}


@router.post("/{transaction_id}/disputes")
async def open_dispute(
    transaction_id: uuid.UUID,
    reason: str = Form(...),
    description: str | None = Form(None),
    file: UploadFile | None = File(None),
    user: AppUser = Depends(get_current_user),
    buyer: DomainTransferBuyerService = Depends(_buyer_service),
) -> dict:
    from app.utils.transfer_enums import DisputeReason

    try:
        dispute_reason = DisputeReason(reason)
    except ValueError as exc:
        raise AppException("Invalid dispute reason.", status_code=400) from exc

    await buyer.open_dispute(
        transaction_id,
        buyer=user,
        reason=dispute_reason,
        description=description,
        evidence_file=file,
    )
    return {"success": True}
