"""Venture deal escrow state machine — post-audit regression tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.entity.coventure.brand_details_entity import BrandDetails
from app.entity.coventure.venture_deal_transaction_entity import VentureDealTransaction
from app.entity.coventure.venture_entity import Venture
from app.entity.payout.seller_payout_profile_entity import SellerPayoutProfile
from app.entity.user.user_role import UserRole
from app.service.security.auth_code_encryption_service import encrypt_secret
from app.service.venture.venture_deal_service import VentureDealService
from app.utils.transfer_enums import MarketplaceEscrowStatus, PayoutMethod, SellerKycStatus
from app.utils.venture_enums import (
    VentureDealKind,
    VentureDealStatus,
    VentureListingApprovalStatus,
    VentureListingMode,
    VentureListingStatus,
    VentureSaleType,
    VentureStage,
)


async def _seed_venture_deal(
    session,
    *,
    seller_id: uuid.UUID,
    buyer_id: uuid.UUID,
    deal_status: VentureDealStatus = VentureDealStatus.PENDING_PAYMENT,
    listing_status: VentureListingStatus = VentureListingStatus.DEAL_FINALIZED,
    razorpay_order_id: str | None = "order_test_123",
    razorpay_payment_id: str | None = None,
) -> tuple[Venture, VentureDealTransaction]:
    brand = BrandDetails(brand_name="Escrow Test Co", description="Test")
    session.add(brand)
    await session.flush()

    venture = Venture(
        brand_details_id=brand.id,
        listed_by_user_id=seller_id,
        listing_mode=VentureListingMode.VENTURE,
        venture_listing_status=listing_status,
        listing_approval_status=VentureListingApprovalStatus.APPROVED,
        sale_type=VentureSaleType.REGULAR,
        stage=VentureStage.MVP,
        status=True,
    )
    session.add(venture)
    await session.flush()

    txn = VentureDealTransaction(
        venture_id=venture.id,
        buyer_id=buyer_id,
        seller_id=seller_id,
        deal_kind=VentureDealKind.VENTURE_SALE,
        deal_status=deal_status,
        escrow_status=MarketplaceEscrowStatus.HELD,
        gross_amount_inr=100000.0,
        platform_fee_inr=3000.0,
        seller_payout_inr=97000.0,
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
        finalized_at=datetime.now(timezone.utc),
    )
    session.add(txn)
    await session.commit()
    await session.refresh(venture)
    await session.refresh(txn)
    return venture, txn


async def _seed_seller_payout_profile(session, seller_id: uuid.UUID) -> SellerPayoutProfile:
    profile = SellerPayoutProfile(
        user_id=seller_id,
        payout_method=PayoutMethod.UPI,
        account_holder_name="Escrow Seller",
        upi_id_encrypted=encrypt_secret("seller@upi"),
        kyc_status=SellerKycStatus.VERIFIED,
        beneficiary_validated_at=datetime.now(timezone.utc),
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


@pytest.mark.asyncio
async def test_verify_payment_holds_escrow_without_completing_listing(
    integration_db,
    integration_user_factory,
):
    seller = await integration_user_factory()
    buyer = await integration_user_factory()
    venture, txn = await _seed_venture_deal(
        integration_db,
        seller_id=seller.id,
        buyer_id=buyer.id,
    )
    service = VentureDealService(integration_db)

    with patch(
        "app.service.venture.venture_deal_service.rzp.verify_payment_signature",
        return_value=True,
    ):
        result = await service.verify_payment(
            txn.id,
            buyer=buyer,
            razorpay_payment_id="pay_test_abc",
            razorpay_order_id="order_test_123",
            razorpay_signature="sig",
        )

    await integration_db.refresh(venture)
    assert result["dealStatus"] == VentureDealStatus.PAYMENT_HELD.value
    assert venture.venture_listing_status == VentureListingStatus.DEAL_FINALIZED
    assert venture.purchased_by_user_id == buyer.id


@pytest.mark.asyncio
async def test_admin_release_completes_listing_after_payment_held(
    integration_db,
    integration_user_factory,
):
    seller = await integration_user_factory()
    buyer = await integration_user_factory()
    admin = await integration_user_factory(role=UserRole.ADMIN)
    venture, txn = await _seed_venture_deal(
        integration_db,
        seller_id=seller.id,
        buyer_id=buyer.id,
        deal_status=VentureDealStatus.PAYMENT_HELD,
        razorpay_payment_id="pay_held_123",
    )
    await _seed_seller_payout_profile(integration_db, seller.id)
    service = VentureDealService(integration_db)

    result = await service.admin_release_escrow(txn.id, admin=admin)
    await integration_db.refresh(venture)

    assert result["dealStatus"] == VentureDealStatus.COMPLETED.value
    assert result["escrowStatus"] == MarketplaceEscrowStatus.RELEASED.value
    assert venture.venture_listing_status == VentureListingStatus.COMPLETED


@pytest.mark.asyncio
async def test_admin_release_rejects_deal_without_payment(
    integration_db,
    integration_user_factory,
):
    from app.core.exceptions import AppException

    seller = await integration_user_factory()
    buyer = await integration_user_factory()
    admin = await integration_user_factory(role=UserRole.ADMIN)
    _, txn = await _seed_venture_deal(
        integration_db,
        seller_id=seller.id,
        buyer_id=buyer.id,
        deal_status=VentureDealStatus.PENDING_PAYMENT,
        razorpay_payment_id=None,
    )
    service = VentureDealService(integration_db)

    with pytest.raises(AppException) as exc_info:
        await service.admin_release_escrow(txn.id, admin=admin)

    assert exc_info.value.status_code == 400
