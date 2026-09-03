"""DB-backed integration tests for domain marketplace transfer & escrow."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.controller.domain.domain_controller import router as domain_router
from app.controller.domain.domain_transfer_admin_controller import (
    router as transfer_admin_router,
)
from app.controller.domain.domain_transfer_controller import router as transfer_router
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.domain.domain_marketplace_transaction_entity import DomainMarketplaceTransaction
from app.entity.payout.seller_payout_profile_entity import SellerPayoutProfile
from app.repository.domain_marketplace_transaction_repository import (
    DomainMarketplaceTransactionRepository,
)
from app.service.domain.domain_transfer_buyer_service import DomainTransferBuyerService
from app.service.domain.domain_transfer_ops_service import DomainTransferOpsService
from app.service.domain.domain_transfer_payout_service import DomainTransferPayoutService
from app.service.domain.domain_transfer_seller_service import DomainTransferSellerService
from app.service.domain.marketplace_payment_service import MarketplacePaymentService
from app.service.security.auth_code_encryption_service import encrypt_secret
from app.utils.marketplace_enums import DomainListingStatus, MarketplacePaymentStatus
from app.utils.transfer_enums import (
    MarketplaceEscrowStatus,
    MarketplaceTransferStatus,
    PayoutMethod,
    SellerKycStatus,
)
from app.entity.user.user_role import UserRole


async def _seed_listing(
    session,
    *,
    seller_id: uuid.UUID,
    buyer_id: uuid.UUID | None = None,
    status: DomainListingStatus = DomainListingStatus.PENDING,
) -> DomainListing:
    listing = DomainListing(
        domain_name=f"tx{uuid.uuid4().hex[:8]}",
        domain_extension=".com",
        asking_price=10000.0,
        seller_price=8500.0,
        domain_status=status,
        listed_by_user_id=seller_id,
        purchased_by_user_id=buyer_id,
        payment_status=MarketplacePaymentStatus.CREATED,
        verified=True,
        razorpay_order_id=f"order_{uuid.uuid4().hex[:12]}",
    )
    session.add(listing)
    await session.commit()
    await session.refresh(listing)
    return listing


async def _seed_payout_profile(session, seller_id: uuid.UUID) -> SellerPayoutProfile:
    profile = SellerPayoutProfile(
        user_id=seller_id,
        payout_method=PayoutMethod.UPI,
        account_holder_name="Seller Test",
        upi_id_encrypted=encrypt_secret("seller@upi"),
        kyc_status=SellerKycStatus.VERIFIED,
        beneficiary_validated_at=datetime.now(timezone.utc),
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


@pytest.mark.asyncio
async def test_verify_payment_creates_held_transaction(
    integration_db,
    integration_user_factory,
):
    seller = await integration_user_factory(email="seller-transfer@test.local")
    buyer = await integration_user_factory(email="buyer-transfer@test.local")
    listing = await _seed_listing(
        integration_db,
        seller_id=seller.id,
        buyer_id=buyer.id,
    )
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"

    service = MarketplacePaymentService(integration_db)
    with (
        patch(
            "app.service.domain.marketplace_payment_service.rzp.verify_payment_signature",
            return_value=True,
        ),
        patch(
            "app.service.domain.domain_transfer_notification_service.DomainTransferNotificationService.on_payment_completed",
            new_callable=AsyncMock,
        ),
    ):
        result = await service.verify_payment(
            listing.id,
            razorpay_payment_id=payment_id,
            razorpay_order_id=listing.razorpay_order_id,
            razorpay_signature="sig_test",
            buyer=buyer,
        )

    assert result["success"] is True
    assert result["transactionId"]
    assert result["transferStatus"] == MarketplaceTransferStatus.AWAITING_AUTH_CODE.value

    tx_repo = DomainMarketplaceTransactionRepository(integration_db)
    tx = await tx_repo.get_by_razorpay_payment_id(payment_id)
    assert tx is not None
    assert tx.escrow_status == MarketplaceEscrowStatus.HELD
    assert tx.buyer_id == buyer.id
    assert tx.seller_id == seller.id

    # Idempotent replay
    with patch(
        "app.service.domain.marketplace_payment_service.rzp.verify_payment_signature",
        return_value=True,
    ):
        replay = await service.verify_payment(
            listing.id,
            razorpay_payment_id=payment_id,
            razorpay_order_id=listing.razorpay_order_id,
            razorpay_signature="sig_test",
            buyer=buyer,
        )
    assert replay["transactionId"] == result["transactionId"]


@pytest.mark.asyncio
async def test_full_transfer_flow_to_payout_pending(
    integration_db,
    integration_user_factory,
):
    seller = await integration_user_factory(email="seller-flow@test.local")
    buyer = await integration_user_factory(email="buyer-flow@test.local")
    listing = await _seed_listing(integration_db, seller_id=seller.id, buyer_id=buyer.id)

    pay_service = MarketplacePaymentService(integration_db)
    with (
        patch(
            "app.service.domain.marketplace_payment_service.rzp.verify_payment_signature",
            return_value=True,
        ),
        patch(
            "app.service.domain.domain_transfer_notification_service.DomainTransferNotificationService.on_payment_completed",
            new_callable=AsyncMock,
        ),
    ):
        pay_result = await pay_service.verify_payment(
            listing.id,
            razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
            razorpay_order_id=listing.razorpay_order_id,
            razorpay_signature="sig",
            buyer=buyer,
        )
    tx_id = uuid.UUID(pay_result["transactionId"])

    seller_service = DomainTransferSellerService(integration_db)
    with patch(
        "app.service.domain.domain_transfer_notification_service.DomainTransferNotificationService.on_auth_code_available",
        new_callable=AsyncMock,
    ):
        await seller_service.submit_auth_code(
            tx_id,
            seller=seller,
            registrar_name="GoDaddy",
            auth_code="SECRET-CODE-99",
        )

    buyer_service = DomainTransferBuyerService(integration_db)
    await buyer_service.choose_self_transfer(
        tx_id,
        buyer=buyer,
        buyer_target_registrar="Namecheap",
    )

    otp_service = buyer_service._otp
    with patch.object(otp_service, "verify_otp", new_callable=AsyncMock):
        plain = await buyer_service.verify_reveal_otp(tx_id, buyer=buyer, otp="123456")
    assert plain == "SECRET-CODE-99"

    await buyer_service.mark_transfer_started(tx_id, buyer=buyer)
    await buyer_service.confirm_transfer(tx_id, buyer=buyer)

    tx_repo = DomainMarketplaceTransactionRepository(integration_db)
    tx = await tx_repo.get_by_id(tx_id)
    assert tx.transfer_status == MarketplaceTransferStatus.PAYOUT_PENDING
    assert tx.buyer_target_registrar == "Namecheap"


@pytest.mark.asyncio
async def test_ops_seller_deadline_moves_to_admin_review(
    integration_db,
    integration_user_factory,
):
    seller = await integration_user_factory()
    buyer = await integration_user_factory()
    now = datetime.now(timezone.utc)
    tx = DomainMarketplaceTransaction(
        domain_listing_id=(await _seed_listing(integration_db, seller_id=seller.id, buyer_id=buyer.id)).id,
        buyer_id=buyer.id,
        seller_id=seller.id,
        domain_fqdn="deadline.com",
        gross_amount_inr=5000.0,
        platform_fee_inr=750.0,
        seller_payout_inr=4250.0,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        escrow_status=MarketplaceEscrowStatus.HELD,
        transfer_status=MarketplaceTransferStatus.AWAITING_AUTH_CODE,
        seller_deadline_at=now - timedelta(hours=1),
    )
    integration_db.add(tx)
    await integration_db.commit()

    ops = DomainTransferOpsService(integration_db)
    with patch(
        "app.service.domain.domain_transfer_notification_service.DomainTransferNotificationService.on_admin_review_required",
        new_callable=AsyncMock,
    ):
        stats = await ops.run_tick()

    assert stats["timeouts"] >= 1
    refreshed = await DomainMarketplaceTransactionRepository(integration_db).get_by_id(tx.id)
    assert refreshed.transfer_status == MarketplaceTransferStatus.ADMIN_REVIEW_REQUIRED


@pytest.mark.asyncio
async def test_admin_payout_release_after_profile_verified(
    integration_db,
    integration_user_factory,
):
    admin = await integration_user_factory(role=UserRole.ADMIN)
    seller = await integration_user_factory(email="seller-payout@test.local")
    buyer = await integration_user_factory()
    listing = await _seed_listing(integration_db, seller_id=seller.id, buyer_id=buyer.id)
    await _seed_payout_profile(integration_db, seller.id)

    tx = DomainMarketplaceTransaction(
        domain_listing_id=listing.id,
        buyer_id=buyer.id,
        seller_id=seller.id,
        domain_fqdn="payout.com",
        gross_amount_inr=10000.0,
        platform_fee_inr=1500.0,
        seller_payout_inr=8500.0,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        escrow_status=MarketplaceEscrowStatus.HELD,
        transfer_status=MarketplaceTransferStatus.PAYOUT_PENDING,
        seller_deadline_at=datetime.now(timezone.utc) + timedelta(hours=36),
    )
    integration_db.add(tx)
    await integration_db.commit()
    await integration_db.refresh(tx)

    payout = DomainTransferPayoutService(integration_db)
    with patch(
        "app.service.domain.domain_transfer_notification_service.DomainTransferNotificationService.on_payout_released",
        new_callable=AsyncMock,
    ):
        await payout.approve_payout(tx.id, admin=admin)
        result = await payout.release_payout(tx.id, admin=admin)

    assert result["success"] is True
    final = await DomainMarketplaceTransactionRepository(integration_db).get_by_id(tx.id)
    assert final.transfer_status == MarketplaceTransferStatus.COMPLETED
    assert final.escrow_status == MarketplaceEscrowStatus.RELEASED


@pytest.mark.asyncio
async def test_transfer_api_routes_seller_and_buyer_lists(
    integration_user_factory,
    integration_app_factory,
):
    user = await integration_user_factory()
    app = integration_app_factory(routers=[transfer_router], current_user=user)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        seller_res = await client.get("/api/v1/domain/transfers/seller")
        buyer_res = await client.get("/api/v1/domain/transfers/buyer")

    assert seller_res.status_code == 200
    assert buyer_res.status_code == 200
    assert "items" in seller_res.json()
    assert "items" in buyer_res.json()


@pytest.mark.asyncio
async def test_admin_transfer_queue_route(
    integration_user_factory,
    integration_app_factory,
):
    admin = await integration_user_factory(role=UserRole.ADMIN)
    app = integration_app_factory(routers=[transfer_admin_router], current_user=admin)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get("/api/v1/admin/domain-transfers/")

    assert res.status_code == 200
    assert "items" in res.json()


@pytest.mark.asyncio
async def test_payment_verify_api_returns_transaction_id(
    integration_db,
    integration_user_factory,
    integration_app_factory,
):
    seller = await integration_user_factory(email="api-seller@test.local")
    buyer = await integration_user_factory(email="api-buyer@test.local")
    listing = await _seed_listing(integration_db, seller_id=seller.id, buyer_id=buyer.id)

    app = integration_app_factory(routers=[domain_router], current_user=buyer)
    transport = ASGITransport(app=app)

    with (
        patch(
            "app.service.domain.marketplace_payment_service.rzp.verify_payment_signature",
            return_value=True,
        ),
        patch(
            "app.service.domain.domain_transfer_notification_service.DomainTransferNotificationService.on_payment_completed",
            new_callable=AsyncMock,
        ),
    ):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/domain/listings/{listing.id}/purchase/verify",
                json={
                    "razorpayPaymentId": f"pay_{uuid.uuid4().hex[:12]}",
                    "razorpayOrderId": listing.razorpay_order_id,
                    "razorpaySignature": "sig_api",
                },
            )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("transactionId")
    assert body.get("transferStatus") == MarketplaceTransferStatus.AWAITING_AUTH_CODE.value
