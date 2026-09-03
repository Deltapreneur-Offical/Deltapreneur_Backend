"""
WinnerService — terminal-state resolution for auctions.

Called when an auction's end_time has elapsed (by either AuctionTimerService or
an explicit close request). Responsibilities:

- Lock the auction row.
- Determine the winning bid (highest amount, earliest timestamp on ties).
- Transition status:
    * has-bids   → PAYMENT_PENDING (winner needs to pay)
    * no-bids    → UNSOLD
- Idempotent: re-running on an already-resolved auction is a no-op.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.auction.auction_entity import Auction
from app.entity.auction.bid_entity import Bid
from app.repository.bid_repository import BidRepository
from app.utils.enums import AuctionStatus

logger = logging.getLogger(__name__)


class WinnerService:
    """Resolve auction terminal states + winner selection."""

    NON_RESOLVABLE = {
        AuctionStatus.COMPLETED,
        AuctionStatus.CANCELLED,
        AuctionStatus.UNSOLD,
        AuctionStatus.PAYMENT_PENDING,
    }

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._bid_repo = BidRepository(session)

    # ------------------------------------------------------------------ #
    # Public                                                              #
    # ------------------------------------------------------------------ #

    async def resolve_auction(self, auction_id: uuid.UUID) -> Auction:
        """
        Resolve a single auction to its terminal status.

        Locks the auction row to keep this safe against concurrent timer
        sweeps and concurrent bid attempts that may race the deadline.
        """
        stmt = (
            select(Auction)
            .where(
                Auction.id == auction_id,
                Auction.is_deleted.is_(False),
            )
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        auction: Optional[Auction] = result.scalar_one_or_none()
        if auction is None:
            raise AppException("Auction not found.", status_code=404)

        # Idempotency.
        if auction.status in self.NON_RESOLVABLE:
            logger.debug(
                "winner.resolve.skip id=%s status=%s",
                auction.id, auction.status.value,
            )
            return auction

        winning_bid = await self._bid_repo.get_highest_bid(auction.id)

        if winning_bid is None:
            return await self._mark_unsold(auction)

        return await self._mark_payment_pending(auction, winning_bid)

    async def select_winner(self, auction_id: uuid.UUID) -> Optional[Bid]:
        """Return the winning bid for an auction (read-only)."""
        return await self._bid_repo.get_highest_bid(auction_id)

    async def mark_winning_bid(
        self,
        auction_id: uuid.UUID,
        bid_id: uuid.UUID,
    ) -> None:
        """Idempotently flag exactly one bid as the winner."""
        await self._bid_repo.clear_winning_flag(auction_id)
        stmt = (
            update(Bid)
            .where(
                Bid.id == bid_id,
                Bid.auction_id == auction_id,
                Bid.is_deleted.is_(False),
            )
            .values(is_winning_bid=True)
            .execution_options(synchronize_session=False)
        )
        await self._session.execute(stmt)

    # ------------------------------------------------------------------ #
    # Internal transitions                                                #
    # ------------------------------------------------------------------ #

    async def _mark_unsold(self, auction: Auction) -> Auction:
        auction.status = AuctionStatus.UNSOLD
        auction.current_winner_id = None
        await self._session.flush()
        await self._session.commit()
        await self._notify_zero_bid_seller(auction)
        await self._publish_event(
            auction.id,
            {
                "type": "AUCTION_UNSOLD",
                "auction_id": str(auction.id),
                "domain_id": auction.domain_id,
                "status": auction.status.value,
            },
        )
        logger.info("auction.unsold id=%s domain=%s", auction.id, auction.domain_id)
        return auction

    async def _mark_payment_pending(
        self,
        auction: Auction,
        winning_bid: Bid,
    ) -> Auction:
        # First persist the ENDED transition (audit trail), then move to
        # PAYMENT_PENDING in the same commit.
        await self.mark_winning_bid(auction.id, winning_bid.id)

        auction.status = AuctionStatus.PAYMENT_PENDING
        auction.current_winner_id = winning_bid.bidder_id
        auction.current_highest_bid = winning_bid.amount

        await self._session.flush()
        await self._session.commit()

        await self._notify_payment_pending(auction, winning_bid)
        await self._start_winner_payment_window(auction, winning_bid)

        await self._publish_event(
            auction.id,
            {
                "type": "AUCTION_ENDED",
                "auctionId": str(auction.id),
                "auction_id": str(auction.id),
                "domain_id": str(auction.domain_id),
                "status": auction.status.value,
                "currentHighestBid": float(winning_bid.amount),
                "currentWinnerId": str(winning_bid.bidder_id),
                "currentWinnerName": winning_bid.bidder_name,
                "totalBids": auction.total_bids,
                "winnerPaymentPaid": False,
                "winner": {
                    "user_id": str(winning_bid.bidder_id),
                    "name": winning_bid.bidder_name,
                    "winning_amount": str(winning_bid.amount),
                },
            },
        )
        logger.info(
            "auction.payment_pending id=%s winner=%s amount=%s",
            auction.id, winning_bid.bidder_id, winning_bid.amount,
        )
        return auction

    async def _notify_payment_pending(
        self,
        auction: Auction,
        winning_bid: Bid,
    ) -> None:
        from sqlalchemy import select

        from app.entity.cobranding.domain_listing_entity import DomainListing
        from app.entity.user.app_user import AppUser
        from app.service.auction.auction_notification_service import (
            notify_seller_auction_ended_with_winner,
            notify_winner_payment_due,
        )

        domain_label = str(auction.domain_id)
        listing_result = await self._session.execute(
            select(DomainListing).where(DomainListing.id == auction.domain_id)
        )
        listing = listing_result.scalar_one_or_none()
        if listing is not None:
            ext = listing.domain_extension or ""
            if ext and not ext.startswith("."):
                ext = f".{ext}"
            domain_label = f"{listing.domain_name}{ext}".strip() or domain_label

        winner_result = await self._session.execute(
            select(AppUser).where(AppUser.id == winning_bid.bidder_id)
        )
        winner_user = winner_result.scalar_one_or_none()
        if winner_user is not None:
            notify_winner_payment_due(
                winner_user,
                auction_id=auction.id,
                domain_label=domain_label,
                amount_inr=float(winning_bid.amount),
            )

        seller_id = listing.listed_by_user_id if listing else auction.created_by
        if seller_id:
            seller_result = await self._session.execute(
                select(AppUser).where(AppUser.id == seller_id)
            )
            seller_user = seller_result.scalar_one_or_none()
            if seller_user is not None:
                notify_seller_auction_ended_with_winner(
                    seller_user,
                    auction_id=auction.id,
                    domain_label=domain_label,
                    winner_name=winning_bid.bidder_name,
                    amount_inr=float(winning_bid.amount),
                )

    async def _start_winner_payment_window(
        self,
        auction: Auction,
        winning_bid: Bid,
    ) -> None:
        try:
            from app.service.auction.winner_payment_lifecycle import (
                WinnerPaymentLifecycleAsync,
            )

            from sqlalchemy import select
            from app.entity.cobranding.domain_listing_entity import DomainListing

            listing_result = await self._session.execute(
                select(DomainListing).where(DomainListing.id == auction.domain_id)
            )
            listing = listing_result.scalar_one_or_none()
            title = str(auction.domain_id)
            if listing is not None:
                ext = listing.domain_extension or ""
                if ext and not ext.startswith("."):
                    ext = f".{ext}"
                title = f"{listing.domain_name}{ext}".strip() or title
            seller_id = listing.listed_by_user_id if listing else auction.created_by
            life = WinnerPaymentLifecycleAsync(self._session)
            track = await life.start_winner_window(
                auction_type="DOMAIN",
                auction_id=auction.id,
                winner_user_id=winning_bid.bidder_id,
                seller_user_id=seller_id,
                winning_amount=float(winning_bid.amount),
                title=title,
                pay_path=f"/auction/{auction.id}",
            )
            await life.send_win_email(track)
            await self._session.commit()
        except Exception:
            logger.exception(
                "winner_payment.window_start_failed auction=%s", auction.id
            )

    async def _notify_zero_bid_seller(self, auction: Auction) -> None:
        """No bids → unsold, no fee refund; tip the seller once."""
        try:
            from sqlalchemy import select

            from app.entity.cobranding.domain_listing_entity import DomainListing
            from app.entity.user.app_user import AppUser
            from app.service.auction.auction_notification_service import _notify_sync
            from app.service.auction.winner_payment_lifecycle import (
                WinnerPaymentLifecycleAsync,
            )

            listing_result = await self._session.execute(
                select(DomainListing).where(DomainListing.id == auction.domain_id)
            )
            listing = listing_result.scalar_one_or_none()
            title = str(auction.domain_id)
            if listing is not None:
                ext = listing.domain_extension or ""
                if ext and not ext.startswith("."):
                    ext = f".{ext}"
                title = f"{listing.domain_name}{ext}".strip() or title
            seller_id = listing.listed_by_user_id if listing else auction.created_by
            if not seller_id:
                return
            life = WinnerPaymentLifecycleAsync(self._session)
            first = await life.mark_zero_bid_notice_sent(
                "DOMAIN", auction.id, seller_id, title
            )
            await self._session.commit()
            if not first:
                return
            seller_result = await self._session.execute(
                select(AppUser).where(AppUser.id == seller_id)
            )
            seller = seller_result.scalar_one_or_none()
            if seller is None:
                return
            _notify_sync(
                seller,
                title="Your auction ended with no bids",
                message=(
                    f'“{title}” received no bids. The auction creation fee is not refunded '
                    "for zero-bid auctions. You can pay the creation fee again to re-list. "
                    "Tip: try a clearer description, a more competitive starting bid, or "
                    "promote the listing before the next auction."
                ),
                target_url=f"/auction/{auction.id}",
            )
            if seller.email:
                try:
                    from fastapi_mail import FastMail
                    from app.service.auth.mail_service import MailService

                    html = (
                        f"<p>Hi,</p>"
                        f"<p>Your auction for <strong>{title}</strong> ended with "
                        f"<strong>no bids</strong>.</p>"
                        f"<p>The auction creation fee is <strong>not refunded</strong> in this case. "
                        f"You can pay the creation fee again and put the listing back into auction.</p>"
                        f"<p><strong>Tips for next time:</strong> refine the listing details, "
                        f"set a competitive starting bid, and share the live auction link.</p>"
                    )
                    message = MailService._html_message(
                        subject=f"No bids on “{title}” — how to re-list",
                        recipients=[seller.email],
                        body=html,
                    )
                    await FastMail(MailService._conf()).send_message(message)
                except Exception:
                    logger.exception("zero_bid.seller_email_failed auction=%s", auction.id)
        except Exception:
            logger.exception("zero_bid.notify_failed auction=%s", auction.id)

    # ------------------------------------------------------------------ #
    # WebSocket dispatch (post-commit, fail-open)                         #
    # ------------------------------------------------------------------ #

    async def _publish_event(
        self,
        auction_id: uuid.UUID,
        event: dict[str, Any],
    ) -> None:
        try:
            from app.websocket.manager import broadcast_to_auction  # type: ignore
        except ImportError:
            return
        try:
            await broadcast_to_auction(str(auction_id), event)
        except Exception:  # noqa: BLE001
            logger.exception("ws.broadcast.failed auction=%s", auction_id)
