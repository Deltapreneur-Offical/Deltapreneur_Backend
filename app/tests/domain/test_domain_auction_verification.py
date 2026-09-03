"""Domain auction admin verification workflow tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.entity.auction.auction_entity import Auction
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.service.domain.domain_auction_verification_service import (
    DomainAuctionVerificationService,
    is_auction_publicly_visible,
)
from app.utils.enums import AuctionDuration, AuctionStatus
from app.utils.marketplace_enums import (
    DomainListingVerificationStatus,
    SaleType,
)


def _listing(*, sale_type=SaleType.AUCTION, verification_status=DomainListingVerificationStatus.PENDING, verified=False):
    listing = MagicMock(spec=DomainListing)
    listing.id = uuid.uuid4()
    listing.is_deleted = False
    listing.sale_type = sale_type
    listing.verification_status = verification_status
    listing.verified = verified
    listing.verification_method = None
    listing.verified_at = None
    listing.whois_email = None
    listing.verification_rejection_reason = None
    listing.verification_admin_note = None
    listing.domain_name = "example"
    listing.domain_extension = ".com"
    listing.listed_by = None
    listing.verified_by = None
    listing.listed_by_user_id = None
    return listing


def test_is_auction_publicly_visible_pending_auction_hidden():
    listing = _listing(verification_status=DomainListingVerificationStatus.PENDING)
    assert is_auction_publicly_visible(listing) is False


def test_is_auction_publicly_visible_verified_auction_shown():
    listing = _listing(verification_status=DomainListingVerificationStatus.VERIFIED)
    assert is_auction_publicly_visible(listing) is True


def test_is_auction_publicly_visible_no_listing():
    assert is_auction_publicly_visible(None) is True


@pytest.mark.asyncio
async def test_approve_and_go_live_activates_draft_auction():
    listing_id = uuid.uuid4()
    admin = MagicMock(spec=AppUser)
    admin.id = uuid.uuid4()
    listing = _listing()
    listing.id = listing_id

    now = datetime.now(timezone.utc)
    auction = MagicMock(spec=Auction)
    auction.id = uuid.uuid4()
    auction.status = AuctionStatus.DRAFT
    auction.duration = AuctionDuration.ONE_DAY
    auction.min_bid_price = 500
    auction.total_bids = 0
    auction.current_highest_bid = None
    auction.start_time = now
    auction.end_time = now + timedelta(hours=1)
    auction.original_end_time = auction.end_time

    session = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    service = DomainAuctionVerificationService(session)
    service._listings = AsyncMock()
    service._listings.get_by_id = AsyncMock(return_value=listing)
    service._listings.save = AsyncMock(return_value=listing)
    service._auctions = AsyncMock()
    service._auctions.get_auction_by_domain = AsyncMock(return_value=auction)
    service._domains = AsyncMock()
    service._domains.get_by_id_alive = AsyncMock(return_value=None)
    service._notify_seller = AsyncMock()

    result = await service.approve_and_go_live(listing_id, admin=admin)

    assert auction.status == AuctionStatus.ACTIVE
    assert listing.verification_status == DomainListingVerificationStatus.VERIFIED
    assert listing.verified is True
    assert listing.verified_by_user_id == admin.id
    session.commit.assert_awaited()
    assert result["listingType"] == "domain_auction"


@pytest.mark.asyncio
async def test_reject_verification_cancels_auction():
    listing_id = uuid.uuid4()
    admin = MagicMock(spec=AppUser)
    admin.id = uuid.uuid4()
    listing = _listing()
    listing.id = listing_id

    auction = MagicMock(spec=Auction)
    auction.status = AuctionStatus.DRAFT

    session = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    service = DomainAuctionVerificationService(session)
    service._listings = AsyncMock()
    service._listings.get_by_id = AsyncMock(return_value=listing)
    service._listings.save = AsyncMock(return_value=listing)
    service._auctions = AsyncMock()
    service._auctions.get_auction_by_domain = AsyncMock(return_value=auction)
    service._notify_seller = AsyncMock()

    await service.reject_verification(listing_id, admin=admin, reason="Invalid proof")

    assert listing.verification_status == DomainListingVerificationStatus.REJECTED
    assert listing.verification_rejection_reason == "Invalid proof"
    assert auction.status == AuctionStatus.CANCELLED


@pytest.mark.asyncio
async def test_request_more_information_sets_status():
    listing_id = uuid.uuid4()
    admin = MagicMock(spec=AppUser)
    admin.id = uuid.uuid4()
    listing = _listing()
    listing.id = listing_id

    session = AsyncMock()
    session.commit = AsyncMock()

    service = DomainAuctionVerificationService(session)
    service._listings = AsyncMock()
    service._listings.get_by_id = AsyncMock(return_value=listing)
    service._listings.save = AsyncMock(return_value=listing)
    service._auctions = AsyncMock()
    service._auctions.get_auction_by_domain = AsyncMock(return_value=None)
    service._notify_seller = AsyncMock()

    await service.request_more_information(
        listing_id, admin=admin, message="Please upload registrar screenshot"
    )

    assert listing.verification_status == DomainListingVerificationStatus.MORE_INFO_REQUESTED
    assert listing.verification_admin_note == "Please upload registrar screenshot"
