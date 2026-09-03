

"""
AuctionService — orchestration for auction lifecycle operations.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.auction.auction_entity import Auction
from app.entity.auction.domain_entity import Domain
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.model.auction.auction_request import (
    CreateAuctionRequest,
    ReAuctionRequest,
)
from app.repository.auction_repository import AuctionRepository
from app.repository.domain_repository import DomainRepository
from app.repository.domain_listing_repository import DomainListingRepository
from app.entity.auction.auction_fee_payment_entity import AuctionFeeAuctionType
from app.service.auction.auction_fee_service import AuctionFeeService
from app.utils.enums import AuctionStatus
from app.utils.marketplace_enums import DomainListingVerificationStatus, SaleType

logger = logging.getLogger(__name__)


class AuctionService:
    """High-level auction operations (non-bid)."""

    RE_AUCTIONABLE = {
        AuctionStatus.UNSOLD,
        AuctionStatus.CANCELLED,
        AuctionStatus.ENDED,
    }

    LIVE = {AuctionStatus.ACTIVE, AuctionStatus.EXTENDED, AuctionStatus.DRAFT}

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = AuctionRepository(session)
        self._domain_repo = DomainRepository(session)
        self._listing_repo = DomainListingRepository(session)
        self._fee_service = AuctionFeeService(session)

    @staticmethod
    def _is_admin(actor: AppUser) -> bool:
        from app.utils.admin_fee_roles import role_waives_auction_platform_fees
        # Treat SUPER_ADMIN like ADMIN for ownership/fee shortcuts on auctions.
        return role_waives_auction_platform_fees(getattr(actor, "role", None))

    async def _require_usable_domain_for_auction(
        self, domain_id: uuid.UUID, actor: AppUser
    ) -> None:
        domain = await self._domain_repo.get_by_id_alive(domain_id)
        if domain is None:
            listing = await self._listing_repo.get_by_id(domain_id)
            if listing is not None:
                if not self._is_admin(actor) and listing.listed_by_user_id != actor.id:
                    raise AppException(
                        "You do not have access to this domain.",
                        status_code=403,
                    )
                domain_name = f"{listing.domain_name}{listing.domain_extension}".strip().lower()
                domain = Domain(
                    id=listing.id,
                    owner_id=listing.listed_by_user_id,
                    domain_name=domain_name,
                    description=str(listing.pricing_demand.value if listing.pricing_demand else ""),
                    is_verified=bool(listing.verified),
                )
                await self._domain_repo.create(domain)
                await self._session.flush()
        if domain is None:
            raise AppException("Domain not found.", status_code=404)
        if self._is_admin(actor):
            return
        if domain.owner_id != actor.id:
            raise AppException(
                "You do not have access to this domain.",
                status_code=403,
            )

    async def _require_domain_owner(
        self, domain_id: uuid.UUID, actor: AppUser
    ) -> None:
        await self._require_usable_domain_for_auction(domain_id, actor)

    async def _require_auction_actor(
        self, auction: Auction, actor: AppUser
    ) -> None:
        if self._is_admin(actor):
            return
        if auction.created_by != actor.id:
            raise AppException(
                "You do not have permission to modify this auction.",
                status_code=403,
            )

    async def create_auction(
        self,
        payload: CreateAuctionRequest,
        *,
        actor: AppUser,
    ) -> Auction:
        await self._require_domain_owner(payload.domain_id, actor)
        is_admin = self._is_admin(actor)
        if not is_admin and not payload.creation_fee_order_id:
            raise AppException(
                "Auction creation fee payment is required.",
                status_code=402,
            )

        existing = await self._repo.get_blocking_auction_by_domain(payload.domain_id)
        if existing is not None:
            raise AppException(
                "Domain already has an active or pending auction.",
                status_code=409,
            )

        now = datetime.now(timezone.utc)
        end_time = now + timedelta(seconds=payload.duration.to_seconds())

        auction = Auction(
            domain_id=payload.domain_id,
            status=AuctionStatus.DRAFT,
            duration=payload.duration,
            min_bid_price=payload.min_bid_price,
            current_highest_bid=None,
            total_bids=0,
            current_winner_id=None,
            start_time=now,
            end_time=end_time,
            original_end_time=end_time,
            created_by=actor.id,
        )
        auction = await self._repo.create_auction(auction)
        
        # Ensure the domain listing is updated so the auction goes to the admin queue
        listing = await self._listing_repo.get_by_id(payload.domain_id)
        if listing:
            if listing.sale_type != SaleType.AUCTION:
                listing.sale_type = SaleType.AUCTION
            listing.verification_status = DomainListingVerificationStatus.PENDING
            listing.verified = False
            await self._listing_repo.save(listing)
            
        if not is_admin:
            await self._fee_service.consume_creation_fee(
                user=actor,
                auction_type=AuctionFeeAuctionType.DOMAIN,
                creation_fee_order_id=payload.creation_fee_order_id,
                auction_id=auction.id,
            )
        await self._session.commit()

        logger.info(
            "auction.created id=%s domain=%s by=%s end_time=%s",
            auction.id, auction.domain_id, actor.id, auction.end_time,
        )
        return auction

    async def get_auction(self, auction_id: uuid.UUID) -> Auction:
        auction = await self._repo.get_auction_by_id(auction_id, load_bids=True)
        if auction is None:
            raise AppException("Auction not found.", status_code=404)
        return auction

    async def get_auction_detail(self, auction_id: uuid.UUID) -> dict:
        from app.model.auction.auction_mapper import build_public_auction_detail
        from app.repository.payment_repository import PaymentRepository
        from app.service.domain.domain_auction_verification_service import (
            is_auction_publicly_visible,
        )
        from app.utils.enums import AuctionStatus

        auction = await self._repo.get_auction_by_id(auction_id, load_bids=True)
        if auction is None:
            raise AppException("Auction not found.", status_code=404)
        listing = await self._listing_repo.get_by_id(auction.domain_id)
        if not is_auction_publicly_visible(listing):
            raise AppException("Auction not found.", status_code=404)

        success_payment = await PaymentRepository(self._session).get_success_for_auction(
            auction_id,
        )
        transfer_tx_id = None
        if listing is not None and listing.active_transaction_id:
            transfer_tx_id = str(listing.active_transaction_id)

        return build_public_auction_detail(
            auction,
            listing=listing,
            winner_payment_paid=(
                success_payment is not None
                or auction.status == AuctionStatus.COMPLETED
            ),
            transfer_transaction_id=transfer_tx_id,
        )

    async def list_active_enriched(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        from app.model.auction.auction_mapper import build_public_auction_item

        offset = max(0, (page - 1) * page_size)
        auctions = list(
            await self._repo.get_active_auctions_with_details(
                limit=page_size,
                offset=offset,
            )
        )
        listing_ids = list({a.domain_id for a in auctions})
        listings = await self._listing_repo.get_by_ids(listing_ids)
        listing_by_id = {listing.id: listing for listing in listings}
        return [
            build_public_auction_item(
                auction,
                listing=listing_by_id.get(auction.domain_id),
            )
            for auction in auctions
        ]

    async def search_active_enriched(
        self,
        query: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        if not query.strip():
            return []

        from app.model.auction.auction_mapper import build_public_auction_item

        offset = max(0, (page - 1) * page_size)
        auctions = list(
            await self._repo.search_active_auctions_with_details(
                query,
                limit=page_size,
                offset=offset,
            )
        )
        listing_ids = list({a.domain_id for a in auctions})
        listings = await self._listing_repo.get_by_ids(listing_ids)
        listing_by_id = {listing.id: listing for listing in listings}
        return [
            build_public_auction_item(
                auction,
                listing=listing_by_id.get(auction.domain_id),
            )
            for auction in auctions
        ]

    async def get_auction_by_domain(self, domain_id: uuid.UUID) -> Auction:
        auction = await self._repo.get_auction_by_domain(domain_id)
        if auction is None:
            raise AppException(
                "No auction found for this domain.", status_code=404
            )
        return auction

    async def get_active_auctions(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> Sequence[Auction]:
        offset = max(0, (page - 1) * page_size)
        return await self._repo.get_active_auctions(
            limit=page_size, offset=offset
        )

    async def count_active_auctions(self) -> int:
        return await self._repo.count_active_auctions()

    async def list_my_auctions(self, user: AppUser) -> list[dict]:
        """Domain auctions created by the current user (Your Auctions)."""
        from app.model.auction.auction_mapper import build_public_auction_item
        from app.utils.auction_tracking import seller_tracking_fields

        auctions = list(await self._repo.list_by_created_by(user.id))
        listing_ids = list({a.domain_id for a in auctions})
        listings = await self._listing_repo.get_by_ids(listing_ids)
        listing_by_id = {listing.id: listing for listing in listings}
        seller = seller_tracking_fields()
        items: list[dict] = []
        for auction in auctions:
            item = build_public_auction_item(
                auction,
                listing=listing_by_id.get(auction.domain_id),
            )
            item.update(seller)
            item["auctionType"] = "DOMAIN"
            items.append(item)
        return items

    async def list_my_bids(self, user: AppUser) -> list[dict]:
        """Domain auctions the current user has bid on (Your Bids)."""
        from app.model.auction.auction_mapper import build_public_auction_item
        from app.repository.bid_repository import BidRepository
        from app.utils.auction_tracking import bidder_tracking_fields

        bid_repo = BidRepository(self._session)
        bids = list(await bid_repo.list_by_bidder_id(user.id))
        best_by_auction: dict[uuid.UUID, float] = {}
        for bid in bids:
            amount = float(bid.amount or 0)
            prev = best_by_auction.get(bid.auction_id)
            if prev is None or amount > prev:
                best_by_auction[bid.auction_id] = amount

        if not best_by_auction:
            return []

        auctions = list(await self._repo.list_by_ids(list(best_by_auction.keys())))
        listing_ids = list({a.domain_id for a in auctions})
        listings = await self._listing_repo.get_by_ids(listing_ids)
        listing_by_id = {listing.id: listing for listing in listings}

        items: list[dict] = []
        for auction in auctions:
            item = build_public_auction_item(
                auction,
                listing=listing_by_id.get(auction.domain_id),
            )
            user_high = best_by_auction.get(auction.id, 0.0)
            item.update(
                bidder_tracking_fields(
                    user_id=user.id,
                    user_highest_bid=user_high,
                    current_highest_bid=float(auction.current_highest_bid or 0),
                    current_winner_id=auction.current_winner_id,
                    status=auction.status,
                )
            )
            item["auctionType"] = "DOMAIN"
            try:
                from app.service.auction.winner_payment_lifecycle import (
                    WinnerPaymentLifecycleAsync,
                    payment_due_label,
                )

                life = WinnerPaymentLifecycleAsync(self._session)
                track = await life.get_track("DOMAIN", auction.id)
                if track:
                    item["winnerPaymentDueAt"] = track.get("dueAt")
                    item["winnerPaymentDaysLeft"] = payment_due_label(track.get("dueAt"))
            except Exception:
                pass
            items.append(item)

        items.sort(
            key=lambda row: row.get("endTime") or row.get("createdAt") or "",
            reverse=True,
        )
        return items

    async def list_all(
        self,
        *,
        status: Optional[AuctionStatus] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Sequence[Auction]:
        offset = max(0, (page - 1) * page_size)
        return await self._repo.list_all_auctions(
            status=status, limit=page_size, offset=offset
        )

    async def count_all_auctions(
        self,
        *,
        status: Optional[AuctionStatus] = None,
    ) -> int:
        return await self._repo.count_all_auctions(status=status)

    async def list_all_for_admin(
        self,
        *,
        status: Optional[AuctionStatus] = None,
    ) -> list[dict]:
        from app.model.auction.auction_mapper import build_admin_auction_item

        auctions = list(
            await self._repo.list_all_with_details(
                status=status,
                limit=500,
                offset=0,
            )
        )
        listing_ids = list({a.domain_id for a in auctions})
        listings = await self._listing_repo.get_by_ids(listing_ids)
        listing_by_id = {listing.id: listing for listing in listings}

        out: list[dict] = []
        for auction in auctions:
            listing = listing_by_id.get(auction.domain_id)
            out.append(
                build_admin_auction_item(
                    auction,
                    listing=listing,
                )
            )
        return out

    async def re_auction(
        self,
        auction_id: uuid.UUID,
        payload: ReAuctionRequest,
        *,
        actor: AppUser,
    ) -> Auction:
        prior = await self._repo.get_auction_by_id(auction_id)
        if prior is None:
            raise AppException("Auction not found.", status_code=404)

        await self._require_auction_actor(prior, actor)
        await self._require_domain_owner(payload.domain_id, actor)

        if prior.status not in self.RE_AUCTIONABLE:
            raise AppException(
                f"Auction in status {prior.status.value} cannot be re-auctioned.",
                status_code=409,
            )

        if prior.domain_id != payload.domain_id:
            raise AppException(
                "domain_id does not match the source auction.",
                status_code=400,
            )

        blocking = await self._repo.get_blocking_auction_by_domain(payload.domain_id)
        if blocking is not None:
            raise AppException(
                "Domain already has an active or pending auction.", status_code=409
            )

        now = datetime.now(timezone.utc)
        end_time = now + timedelta(seconds=payload.duration.to_seconds())

        new_auction = Auction(
            domain_id=payload.domain_id,
            status=AuctionStatus.DRAFT,
            duration=payload.duration,
            min_bid_price=payload.min_bid_price or prior.min_bid_price,
            current_highest_bid=None,
            total_bids=0,
            current_winner_id=None,
            start_time=now,
            end_time=end_time,
            original_end_time=end_time,
            created_by=actor.id,
        )
        new_auction = await self._repo.create_auction(new_auction)
        listing = await self._listing_repo.get_by_id(payload.domain_id)
        if listing is not None and listing.sale_type == SaleType.AUCTION:
            listing.verification_status = DomainListingVerificationStatus.PENDING
            listing.verification_rejection_reason = None
            listing.verification_admin_note = None
            await self._listing_repo.save(listing)
        await self._fee_service.consume_creation_fee(
            user=actor,
            auction_type=AuctionFeeAuctionType.DOMAIN,
            creation_fee_order_id=payload.creation_fee_order_id,
            auction_id=new_auction.id,
        )
        await self._session.commit()

        logger.info(
            "auction.re_auctioned new_id=%s prior_id=%s domain=%s",
            new_auction.id, prior.id, prior.domain_id,
        )
        return new_auction

    async def close_auction(
        self,
        auction_id: uuid.UUID,
        *,
        actor: AppUser,
        force_cancel: bool = False,
    ) -> Auction:
        from app.service.auction.winner_service import WinnerService

        auction = await self._repo.get_auction_by_id(auction_id)
        if auction is None:
            raise AppException("Auction not found.", status_code=404)

        await self._require_auction_actor(auction, actor)

        if auction.status in {
            AuctionStatus.COMPLETED,
            AuctionStatus.CANCELLED,
            AuctionStatus.UNSOLD,
            AuctionStatus.PAYMENT_PENDING,
        }:
            raise AppException(
                f"Auction already in terminal status {auction.status.value}.",
                status_code=409,
            )

        if force_cancel:
            updated = await self._repo.close_auction(
                auction_id, final_status=AuctionStatus.CANCELLED
            )
            await self._session.commit()
            logger.info("auction.cancelled id=%s by=%s", auction_id, actor.id)
            return updated  # type: ignore[return-value]

        winner_service = WinnerService(self._session)
        resolved = await winner_service.resolve_auction(auction_id)
        return resolved
