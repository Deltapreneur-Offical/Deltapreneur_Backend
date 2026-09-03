"""Admin APIs for domain marketplace transfers."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import require_role
from app.core.exceptions import AppException
from app.entity.user.app_user import AppUser
from app.model.marketplace.transfer_request import (
    ForceCompleteRequest,
    ReleasePayoutRequest,
    ResolveAdminReviewRequest,
    ResolveDisputeRequest,
    SellerPayoutReminderRequest,
)
from app.service.domain.domain_marketplace_transaction_service import (
    DomainMarketplaceTransactionService,
)
from app.service.domain.domain_transfer_dispute_service import DomainTransferDisputeService
from app.service.domain.domain_transfer_escrow_service import DomainTransferEscrowService
from app.service.domain.domain_transfer_event_service import DomainTransferEventService
from app.service.domain.domain_transfer_notification_service import DomainTransferNotificationService
from app.service.domain.domain_transfer_payout_service import DomainTransferPayoutService
from app.service.domain.domain_transfer_whois_service import DomainTransferWhoisService
from app.service.payout.seller_payout_profile_service import SellerPayoutProfileService
from app.service.security.auth_code_encryption_service import decrypt_secret
from app.utils.transfer_enums import MarketplaceTransferStatus

router = APIRouter(prefix="/api/v1/admin/domain-transfers", tags=["Admin Domain Transfers"])
seller_payout_admin_router = APIRouter(prefix="/api/admin", tags=["Admin Seller Payouts"])


async def _send_payout_profile_reminder(
    transaction_id: uuid.UUID,
    *,
    admin: AppUser,
    db: AsyncSession,
) -> dict:
    service = DomainMarketplaceTransactionService(db)
    tx = await service.get_for_user(transaction_id, admin, admin=True)
    recipient = await DomainTransferNotificationService(db).on_payout_profile_reminder(
        tx,
        admin=admin,
    )
    await db.commit()
    return {"success": True, "recipient": recipient}


@router.get("/")
async def list_transfers(
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    from app.repository.domain_marketplace_transaction_repository import (
        DomainMarketplaceTransactionRepository,
    )
    from app.repository.software_purchase_repository import SoftwarePurchaseRepository
    from app.service.cocreation.technology_transfer_admin_service import TechnologyTransferAdminService


    repo = DomainMarketplaceTransactionRepository(db)
    transfer_status = None
    if status:
        try:
            transfer_status = MarketplaceTransferStatus(status)
        except ValueError as exc:
            pass

    domain_rows = await repo.list_for_admin(transfer_status=transfer_status, limit=limit, offset=offset)
    service = DomainMarketplaceTransactionService(db)
    items = [await service.serialize(tx, include_payout_profile=True) for tx in domain_rows]
    
    # Sort the items by createdAt desc and slice
    items.sort(key=lambda x: x.get("createdAt") or "", reverse=True)
    items = items[:limit]
    
    return {"items": items}


# IMPORTANT: static routes MUST come before /{transaction_id} to avoid 422.
@router.get("/razorpay-dashboard-url")
async def get_razorpay_dashboard_url(
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict:
    """Return the Razorpay Dashboard base URL for the current environment."""
    from app.integrations.razorpay import client as rzp
    environment = rzp.get_environment()
    base_url = "https://dashboard.razorpay.com"
    return {
        "dashboardUrl": base_url,
        "environment": environment,
    }


@router.get("/{transaction_id}/dashboard-url")
async def get_transaction_dashboard_url(
    transaction_id: uuid.UUID,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Return the Razorpay Dashboard URL for a specific transaction's payment."""
    from app.repository.domain_marketplace_transaction_repository import (
        DomainMarketplaceTransactionRepository,
    )
    from app.integrations.razorpay import client as rzp

    repo = DomainMarketplaceTransactionRepository(db)
    tx = await repo.get_by_id(transaction_id)
    if tx is None:
        raise AppException("Transaction not found.", status_code=404)
    if not tx.razorpay_payment_id:
        raise AppException(
            "No Razorpay payment ID for this transaction.", status_code=400,
        )
    environment = rzp.get_environment() or "TEST"
    base_url = "https://dashboard.razorpay.com"
    dashboard_url = f"{base_url}/app/payments/{tx.razorpay_payment_id}"

    buyer_paid = round(float(tx.gross_amount_inr or 0) * 1.18, 2)

    return {
        "dashboardUrl": dashboard_url,
        "paymentId": tx.razorpay_payment_id,
        "environment": environment,
        "buyerPaidAmountInr": buyer_paid,
        "grossAmountInr": float(tx.gross_amount_inr or 0),
        "domain": tx.domain_fqdn,
    }


@router.get("/{transaction_id}")
async def get_transfer_admin_detail(
    transaction_id: uuid.UUID,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    from app.repository.domain_marketplace_transaction_repository import DomainMarketplaceTransactionRepository
    from app.repository.software_purchase_repository import SoftwarePurchaseRepository
    
    if await DomainMarketplaceTransactionRepository(db).get_by_id(transaction_id):
        service = DomainMarketplaceTransactionService(db)
        tx = await service.get_for_user(transaction_id, _admin, admin=True)
        auth_plain = None
        if tx.auth_code_ciphertext:
            try:
                auth_plain = decrypt_secret(tx.auth_code_ciphertext, version=tx.auth_code_key_version)
            except ValueError:
                auth_plain = None
        events = DomainTransferEventService(db)
        payload = await service.serialize(
            tx,
            include_auth_code=True,
            auth_code_plain=auth_plain,
            include_payout_profile=True,
        )
        payload["timeline"] = await events.list_timeline(transaction_id)
        return payload
    else:
        # Check software purchases
        tx = await SoftwarePurchaseRepository(db).get_by_id(transaction_id)
        if not tx:
            raise AppException("Transfer transaction not found.", status_code=404)
        from app.service.cocreation.technology_transfer_admin_service import TechnologyTransferAdminService
        payload = await TechnologyTransferAdminService(db).serialize(tx, include_payout_profile=True)
        payload["timeline"] = []
        return payload


@router.post("/{transaction_id}/approve-payout")
async def approve_payout(
    transaction_id: uuid.UUID,
    admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    from app.repository.domain_marketplace_transaction_repository import DomainMarketplaceTransactionRepository
    from app.service.cocreation.technology_transfer_payout_service import TechnologyTransferPayoutService
    
    if await DomainMarketplaceTransactionRepository(db).get_by_id(transaction_id):
        return await DomainTransferPayoutService(db).approve_payout(transaction_id, admin=admin)
    else:
        return await TechnologyTransferPayoutService(db).approve_payout(transaction_id, admin=admin)


@router.post("/{transaction_id}/release-payout")
async def release_payout(
    transaction_id: uuid.UUID,
    body: ReleasePayoutRequest,
    admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    from app.repository.domain_marketplace_transaction_repository import DomainMarketplaceTransactionRepository
    from app.service.cocreation.technology_transfer_payout_service import TechnologyTransferPayoutService
    
    if await DomainMarketplaceTransactionRepository(db).get_by_id(transaction_id):
        return await DomainTransferPayoutService(db).release_payout(
            transaction_id,
            admin=admin,
            payout_method_used=body.payout_method_used,
            transaction_reference_number=body.transaction_reference_number,
            notes=body.notes,
        )
    else:
        return await TechnologyTransferPayoutService(db).release_payout(
            transaction_id,
            admin=admin,
            payout_method_used=body.payout_method_used,
            transaction_reference_number=body.transaction_reference_number,
            notes=body.notes,
        )


@router.post("/{transaction_id}/process-refund")
async def process_refund(
    transaction_id: uuid.UUID,
    admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Process a refund through the Razorpay API.

    This calls the real Razorpay Refund API to refund the buyer.
    The refund amount is the full GST-inclusive buyer-paid amount.
    """
    return await DomainTransferEscrowService(db).refund(
        transaction_id, admin=admin, note="admin_process_refund"
    )


@router.post("/{transaction_id}/sync-refund")
async def sync_refund(
    transaction_id: uuid.UUID,
    admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Sync refund status from Razorpay. Does NOT create a new refund.

    This endpoint checks Razorpay for existing refunds on the payment
    associated with this transaction. If a refund exists, it synchronizes
    the CoBrother database with the real Razorpay refund data.
    The admin must manually refund in the Razorpay Dashboard first.
    """
    return await DomainTransferEscrowService(db).sync_refund_from_razorpay(
        transaction_id, admin=admin
    )


@router.post("/{transaction_id}/resolve-admin-review")
async def resolve_admin_review(
    transaction_id: uuid.UUID,
    body: ResolveAdminReviewRequest,
    admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    return await DomainTransferEscrowService(db).resolve_admin_review(
        transaction_id,
        admin=admin,
        action=body.action,
        extension_hours=body.extension_hours,
    )


@router.post("/{transaction_id}/force-complete")
async def force_complete(
    transaction_id: uuid.UUID,
    body: ForceCompleteRequest,
    admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    return await DomainTransferEscrowService(db).force_complete(
        transaction_id, admin=admin, reason=body.reason
    )


@router.post("/{transaction_id}/disputes/{dispute_id}/resolve")
async def resolve_dispute(
    transaction_id: uuid.UUID,
    dispute_id: uuid.UUID,
    body: ResolveDisputeRequest,
    admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    return await DomainTransferDisputeService(db).resolve(
        transaction_id,
        dispute_id,
        admin=admin,
        resolution=body.resolution,
        note=body.note,
    )


@router.post("/{transaction_id}/sync-whois")
async def sync_whois(
    transaction_id: uuid.UUID,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    return await DomainTransferWhoisService(db).sync_transaction(transaction_id)


@router.post("/{transaction_id}/payout-profile-reminder")
async def send_payout_profile_reminder(
    transaction_id: uuid.UUID,
    admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    return await _send_payout_profile_reminder(transaction_id, admin=admin, db=db)


@seller_payout_admin_router.post("/seller-payout-reminder")
async def send_seller_payout_reminder(
    body: SellerPayoutReminderRequest,
    admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    return await _send_payout_profile_reminder(body.transaction_id, admin=admin, db=db)


@router.post("/payout-profiles/{user_id}/verify")
async def verify_payout_profile(
    user_id: uuid.UUID,
    admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    return await SellerPayoutProfileService(db).admin_verify(user_id, admin=admin)
