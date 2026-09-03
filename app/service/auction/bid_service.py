"""
BidService — the realtime hot path.

Concurrency model:
- Each `place_bid` call opens its own transaction.
- The parent Auction row is locked with `SELECT ... FOR UPDATE`, serializing
  bid validation/update for that auction across competing requests.
- All state mutations (insert Bid row, update Auction.current_highest_bid /
  total_bids / current_winner_id / end_time) happen inside that lock, then
  commit atomically.
- WebSocket broadcasts run *after* commit — never before. The backend is the
  single source of truth; the client receives optimistic UI updates only via
  the server-pushed event.

Anti-snipe:
- If remaining time < ANTI_SNIPE_WINDOW (5 minutes), `end_time` is extended
  by ANTI_SNIPE_EXTENSION (5 minutes) and status moves to EXTENDED.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.auction.auction_entity import Auction
from app.entity.auction.bid_entity import Bid
from app.entity.user.app_user import AppUser
from app.model.auction.bid_request import PlaceBidRequest
from app.entity.auction.auction_fee_payment_entity import AuctionFeeAuctionType
from app.repository.bid_repository import BidRepository
from app.service.auction.auction_fee_service import AuctionFeeService
from app.service.auction.domain_auction_guard import ensure_domain_verified_for_auction
from app.utils.auction_bid_limits import bid_limit_fields
from app.utils.auction_place_bid_common import (
    ANTI_SNIPE_EXTENSION,
    ANTI_SNIPE_WINDOW,
    apply_anti_snipe,
    bidder_display_name,
    build_bid_placed_ws_event,
    normalize_bid_amount,
    utc_now,
)
from app.utils.enums import AuctionStatus

logger = logging.getLogger(__name__)


class BidService:
    """Place and validate bids with strict transactional guarantees."""

    # Anti-snipe configuration (shared constants).
    ANTI_SNIPE_WINDOW = ANTI_SNIPE_WINDOW
    ANTI_SNIPE_EXTENSION = ANTI_SNIPE_EXTENSION

    # Minimum bid increment over current highest. Conservative default;
    # promote to per-domain config in the future.
    MIN_BID_INCREMENT = Decimal("1.00")

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._bid_repo = BidRepository(session)
        self._fee_service = AuctionFeeService(session)

    # ------------------------------------------------------------------ #
    # Public                                                              #
    # ------------------------------------------------------------------ #

    async def place_bid(
        self,
        payload: PlaceBidRequest,
        *,
        bidder: AppUser,
    ) -> tuple[Bid, dict[str, Any]]:
        """
        Place a bid atomically. Returns the persisted Bid and a websocket
        event payload that the caller should broadcast post-commit.

        Raises AppException on any validation failure.
        """
        if payload.auction_id is None:
            raise AppException("auction_id is required.", status_code=400)

        if payload.amount <= 0:
            raise AppException("Bid amount must be positive.", status_code=400)

        try:
            bid, ws_event = await self._place_bid_locked(payload, bidder)
        except AppException:
            await self._session.rollback()
            raise
        except SQLAlchemyError:
            await self._session.rollback()
            logger.exception(
                "bid.place.db_error auction=%s bidder=%s",
                payload.auction_id, bidder.id,
            )
            raise AppException("Failed to place bid.", status_code=500)

        # Post-commit dispatch.
        await self._publish_event(payload.auction_id, ws_event)
        return bid, ws_event

    # ------------------------------------------------------------------ #
    # Core (runs inside the row lock)                                     #
    # ------------------------------------------------------------------ #

    async def _place_bid_locked(
        self,
        payload: PlaceBidRequest,
        bidder: AppUser,
    ) -> tuple[Bid, dict[str, Any]]:
        # ── 1. Lock the auction row to serialize concurrent bids on it. ──
        stmt = (
            select(Auction)
            .where(
                Auction.id == payload.auction_id,
                Auction.is_deleted.is_(False),
            )
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        auction: Optional[Auction] = result.scalar_one_or_none()

        if auction is None:
            raise AppException("Auction not found.", status_code=404)

        # ── 2. Validate auction is biddable. ──
        self._validate_auction_state(auction)

        await ensure_domain_verified_for_auction(self._session, auction.domain_id)

        from app.service.auction.winner_payment_lifecycle import assert_user_can_bid_async
        await assert_user_can_bid_async(self._session, bidder)

        # ── 3. Validate bid amount. ──
        self._validate_bid_amount(auction, payload.amount)

        fee_row = await self._fee_service.verify_bid_fee_payment(
            auction_type=AuctionFeeAuctionType.DOMAIN,
            auction_id=auction.id,
            user=bidder,
            razorpay_order_id=payload.razorpay_order_id,
            razorpay_payment_id=payload.razorpay_payment_id,
            razorpay_signature=payload.razorpay_signature,
            expected_bid_amount=payload.amount,
        )

        if auction.created_by == bidder.id:
            raise AppException(
                "Auction creator cannot bid on their own auction.",
                status_code=403,
            )

        # ── 4. Anti-snipe extension (decide before mutating). ──
        now = utc_now()
        new_end, new_status, extended = apply_anti_snipe(
            auction.end_time,
            now,
            status=auction.status,
            extended_status=AuctionStatus.EXTENDED,
        )
        auction.end_time = new_end
        auction.status = new_status

        # ── 5. Clear prior winning-bid flag, insert new winning bid. ──
        await self._bid_repo.clear_winning_flag(auction.id)

        bidder_name = bidder_display_name(bidder)
        bid = Bid(
            auction_id=auction.id,
            bidder_id=bidder.id,
            amount=payload.amount,
            bidder_name=bidder_name,
            is_winning_bid=True,
        )
        bid = await self._bid_repo.create_bid(bid)

        # ── 6. Mutate auction aggregate fields. ──
        auction.current_highest_bid = payload.amount
        auction.current_winner_id = bidder.id
        auction.total_bids = (auction.total_bids or 0) + 1

        await self._fee_service.consume_bid_fee(fee_row)
        await self._session.flush()
        await self._session.commit()

        logger.info(
            "bid.placed auction=%s bidder=%s amount=%s extended=%s",
            auction.id, bidder.id, payload.amount, extended,
        )

        ws_event = self._build_ws_event(auction, bid, extended=extended)
        return bid, ws_event

    # ------------------------------------------------------------------ #
    # Validation                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_auction_state(auction: Auction) -> None:
        if auction.status not in {AuctionStatus.ACTIVE, AuctionStatus.EXTENDED}:
            raise AppException(
                f"Auction is not accepting bids (status={auction.status.value}).",
                status_code=409,
            )
        if auction.end_time <= datetime.now(timezone.utc):
            raise AppException(
                "Auction has already expired.", status_code=409
            )

    def _validate_bid_amount(self, auction: Auction, amount: Decimal) -> None:
        try:
            normalize_bid_amount(
                amount,
                current_highest=auction.current_highest_bid or 0,
                min_bid_price=auction.min_bid_price,
            )
        except ValueError as exc:
            raise AppException(str(exc), status_code=400) from exc

    async def listing_bid_limits(self, auction: Auction) -> dict[str, float]:
        """Expose min/max bid bounds for auction detail APIs."""
        return bid_limit_fields(
            current_highest=auction.current_highest_bid or 0,
            min_bid_price=auction.min_bid_price,
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_ws_event(
        auction: Auction,
        bid: Bid,
        *,
        extended: bool,
    ) -> dict[str, Any]:
        """Construct the payload that subscribers of this auction will receive."""
        event = build_bid_placed_ws_event(
            auction_id=auction.id,
            status=auction.status,
            current_highest_bid=auction.current_highest_bid,
            total_bids=auction.total_bids or 0,
            end_time=auction.end_time,
            bidder_name=bid.bidder_name,
            amount=bid.amount or 0,
            bid_time=bid.created_at,
            extended=extended,
            bid_id=bid.id,
            bidder_id=bid.bidder_id,
        )
        event["domain_id"] = auction.domain_id
        return event

    async def _publish_event(
        self,
        auction_id: uuid.UUID,
        event: dict[str, Any],
    ) -> None:
        """
        Broadcast to WebSocket subscribers. Fails open: a broadcast error must
        never roll back the committed bid (which is already durable).
        """
        try:
            # Lazy import — websocket manager may not be wired yet.
            from app.websocket.manager import broadcast_to_auction  # type: ignore
        except ImportError:
            logger.debug(
                "websocket.manager.broadcast_to_auction not available; "
                "skipping broadcast for auction=%s", auction_id,
            )
            return

        try:
            await broadcast_to_auction(str(auction_id), event)
        except Exception:  # noqa: BLE001
            logger.exception(
                "ws.broadcast.failed auction=%s", auction_id
            )
