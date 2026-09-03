import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import anyio
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.entity.auction.auction_participation_entity import (
    AuctionParticipation,
    AuctionParticipationStatus,
    AuctionParticipationType,
)
from app.entity.community.community_auction import CommunityAuction
from app.entity.community.community_auction_bid import CommunityAuctionBid
from app.entity.platform.platform_setting_entity import PlatformSetting
from app.entity.community.community_auction_duration import (
    CommunityAuctionDuration,
)
from app.entity.community.community_auction_status import CommunityAuctionStatus
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.utils.auction_place_bid_common import (
    apply_anti_snipe,
    bidder_display_name,
    build_bid_placed_ws_event,
    normalize_bid_amount,
    utc_now,
)
from app.model.community.community_auction_bid_request import (
    CommunityAuctionBidRequest,
)
from app.model.community.community_auction_create_request import (
    CommunityAuctionCreateRequest,
)
from app.service.auction.auction_fee_sync import (
    consume_bid_fee_sync,
    consume_creation_fee_sync,
    verify_bid_fee_sync,
)
from app.repository.community_auction_bid_repository import (
    CommunityAuctionBidRepository,
)
from app.repository.community_auction_repository import CommunityAuctionRepository
from app.repository.community_repository import CommunityRepository
from app.repository.user_repository import UserRepository
from app.integrations.razorpay import client as rzp
from app.service.notification.notification_service import NotificationService
from app.websocket.manager import community_auction_connection_manager


class CommunityAuctionService:
    @staticmethod
    def _computed_end_time(auction: CommunityAuction) -> datetime | None:
        """Derive end_time when DB row is ACTIVE but end_time was never persisted."""
        if auction.end_time:
            return auction.end_time
        if auction.original_end_time:
            return auction.original_end_time
        if not auction.start_time or not auction.duration:
            return None
        try:
            duration = CommunityAuctionDuration(auction.duration)
        except ValueError:
            return None
        return auction.start_time + timedelta(days=duration.days)

    _TERMINAL_LISTING_STATUSES = frozenset({
        CommunityAuctionStatus.ENDED.value,
        CommunityAuctionStatus.COMPLETED.value,
        CommunityAuctionStatus.UNSOLD.value,
        CommunityAuctionStatus.CLOSED.value,
    })

    @staticmethod
    def _prepare_auction_for_new_listing(
        db: Session,
        auction: CommunityAuction,
        request: CommunityAuctionCreateRequest,
        current_user: AppUser,
        *,
        clear_bids: bool,
    ) -> None:
        if clear_bids:
            bids = CommunityAuctionBidRepository.find_by_auction_id(
                db=db,
                auction_id=auction.id,
            )
            for bid in bids:
                CommunityAuctionBidRepository.soft_delete(
                    db=db,
                    bid=bid,
                    deleted_by=current_user.id,
                )

        auction.created_by = current_user.id
        auction.status = CommunityAuctionStatus.PAYMENT_PENDING.value
        auction.duration = request.duration.value
        auction.min_bid_price = request.min_bid_price
        auction.current_highest_bid = None
        auction.total_bids = 0
        auction.current_winner_id = None
        auction.start_time = None
        auction.end_time = None
        auction.original_end_time = None
        auction.listing_fee_order_id = None
        auction.listing_fee_payment_id = None
        auction.listing_fee_paid = False
        auction.winner_payment_order_id = None
        auction.winner_payment_id = None
        auction.winner_payment_paid = False
        auction.auction_title = request.auction_title
        auction.auction_skills = request.auction_skills
        auction.work_type = request.work_type.value if request.work_type else None
        auction.expected_rate = request.expected_rate
        auction.available_from = request.available_from
        auction.additional_info = request.additional_info

    @staticmethod
    def _to_response(auction: CommunityAuction) -> dict:
        resolved_end = CommunityAuctionService._computed_end_time(auction)
        payload = {
            "id": str(auction.id),
            "community_id": str(auction.community_id),
            "created_by": str(auction.created_by),
            "status": auction.status,
            "duration": auction.duration,
            "min_bid_price": float(auction.min_bid_price),
            "current_highest_bid": (
                float(auction.current_highest_bid)
                if auction.current_highest_bid is not None
                else None
            ),
            "total_bids": auction.total_bids,
            "current_winner_id": (
                str(auction.current_winner_id)
                if auction.current_winner_id
                else None
            ),
            "start_time": auction.start_time.isoformat() if auction.start_time else None,
            "end_time": resolved_end.isoformat() if resolved_end else None,
            "original_end_time": (
                auction.original_end_time.isoformat()
                if auction.original_end_time
                else (resolved_end.isoformat() if resolved_end else None)
            ),
            "listing_fee_order_id": auction.listing_fee_order_id,
            "listing_fee_payment_id": auction.listing_fee_payment_id,
            "listing_fee_paid": auction.listing_fee_paid,
            "winner_payment_order_id": getattr(auction, "winner_payment_order_id", None),
            "winner_payment_id": getattr(auction, "winner_payment_id", None),
            "winner_payment_paid": bool(getattr(auction, "winner_payment_paid", False)),
            "auction_title": auction.auction_title,
            "auction_skills": auction.auction_skills,
            "work_type": auction.work_type,
            "expected_rate": auction.expected_rate,
            "available_from": (
                auction.available_from.isoformat()
                if auction.available_from
                else None
            ),
            "additional_info": auction.additional_info,
            "created_at": auction.created_at.isoformat() if auction.created_at else None,
            "updated_at": auction.updated_at.isoformat() if auction.updated_at else None,
            "featured": bool(getattr(auction, "featured", False)),
        }
        # Frontend compatibility (camelCase aliases expected by React pages/hooks).
        payload.update(
            {
                "communityId": payload["community_id"],
                "createdBy": payload["created_by"],
                "minBidPrice": payload["min_bid_price"],
                "currentHighestBid": payload["current_highest_bid"] or 0,
                "totalBids": payload["total_bids"],
                "currentWinnerId": payload["current_winner_id"],
                "startTime": payload["start_time"],
                "endTime": payload["end_time"],
                "originalEndTime": payload["original_end_time"],
                "listingFeeOrderId": payload["listing_fee_order_id"],
                "listingFeePaymentId": payload["listing_fee_payment_id"],
                "listingFeePaid": payload["listing_fee_paid"],
                "winnerPaymentOrderId": payload["winner_payment_order_id"],
                "winnerPaymentId": payload["winner_payment_id"],
                "winnerPaymentPaid": payload["winner_payment_paid"],
                "auctionTitle": payload["auction_title"],
                "auctionSkills": payload["auction_skills"],
                "workType": payload["work_type"],
                "expectedRate": payload["expected_rate"],
                "availableFrom": payload["available_from"],
                "additionalInfo": payload["additional_info"],
                "createdAt": payload["created_at"],
                "updatedAt": payload["updated_at"],
                "featured": payload["featured"],
            }
        )
        return payload

    @staticmethod
    def _enrich_auction_response(
        db: Session,
        payload: dict,
        auction: CommunityAuction,
    ) -> dict:
        if auction.current_winner_id:
            winner = UserRepository.find_by_id(db, auction.current_winner_id)
            if winner:
                payload["currentWinnerName"] = CommunityAuctionService._get_user_display_name(
                    winner
                )
        return payload

    @staticmethod
    def _bid_to_response(bid: CommunityAuctionBid) -> dict:
        payload = {
            "id": str(bid.id),
            "auction_id": str(bid.auction_id),
            "bidder_id": str(bid.bidder_id),
            "bidder_name": bid.bidder_name,
            "amount": float(bid.amount),
            "bid_time": bid.bid_time.isoformat() if bid.bid_time else None,
            "winning_bid": bid.winning_bid,
            "created_at": bid.created_at.isoformat() if bid.created_at else None,
            "updated_at": bid.updated_at.isoformat() if bid.updated_at else None,
        }
        payload.update(
            {
                "auctionId": payload["auction_id"],
                "bidderId": payload["bidder_id"],
                "bidderName": payload["bidder_name"],
                "bidTime": payload["bid_time"],
                "winningBid": payload["winning_bid"],
                "createdAt": payload["created_at"],
                "updatedAt": payload["updated_at"],
            }
        )
        return payload

    @staticmethod
    def _participation_fee_inr(db: Session) -> float:
        row = db.query(PlatformSetting).filter(
            PlatformSetting.setting_key == "community_auction_participation_fee_inr"
        ).first()
        if not row:
            return 118.0
        try:
            return float((row.setting_value or "").strip())
        except Exception:
            return 118.0

    @staticmethod
    def _has_paid_participation(
        db: Session,
        auction_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        from app.service.auction.auction_fee_sync import has_community_participation_paid

        return has_community_participation_paid(db, auction_id, user_id)

    @staticmethod
    def _build_bid_placed_event(
        auction: CommunityAuction,
        bid_data: dict,
        *,
        extended: bool = False,
    ) -> dict:
        bidder_name = bid_data.get("bidderName") or bid_data.get("bidder_name") or ""
        bid_time_raw = bid_data.get("bidTime") or bid_data.get("bid_time")
        bid_time = None
        if isinstance(bid_time_raw, datetime):
            bid_time = bid_time_raw
        return build_bid_placed_ws_event(
            auction_id=auction.id,
            status=auction.status,
            current_highest_bid=auction.current_highest_bid,
            total_bids=auction.total_bids,
            end_time=auction.end_time,
            bidder_name=bidder_name,
            amount=bid_data.get("amount") or 0,
            bid_time=bid_time,
            extended=extended,
            bid_id=bid_data.get("id"),
            bidder_id=bid_data.get("bidderId") or bid_data.get("bidder_id"),
        )

    @staticmethod
    def _profile_display_status(status: str | None) -> str:
        normalized = (status or "").upper()
        if normalized in {
            CommunityAuctionStatus.ACTIVE.value,
            CommunityAuctionStatus.EXTENDED.value,
        }:
            return "LIVE"
        if normalized == CommunityAuctionStatus.PAYMENT_PENDING.value:
            return "DRAFT"
        if normalized in {
            CommunityAuctionStatus.ENDED.value,
            CommunityAuctionStatus.COMPLETED.value,
            CommunityAuctionStatus.UNSOLD.value,
            CommunityAuctionStatus.CLOSED.value,
        }:
            return "ENDED"
        return "DRAFT"

    @staticmethod
    def to_profile_summary(auction: CommunityAuction) -> dict:
        resolved_end = CommunityAuctionService._computed_end_time(auction)
        starting_bid = float(auction.min_bid_price)
        current_bid = float(auction.current_highest_bid or 0)
        display_status = CommunityAuctionService._profile_display_status(auction.status)
        return {
            "auctionId": str(auction.id),
            "communityId": str(auction.community_id),
            "creatorId": str(auction.community_id),
            "startingBid": starting_bid,
            "currentBid": current_bid,
            "minBidPrice": starting_bid,
            "currentHighestBid": current_bid,
            "totalBids": int(auction.total_bids or 0),
            "status": auction.status,
            "displayStatus": display_status,
            "endTime": resolved_end.isoformat() if resolved_end else None,
            "startTime": auction.start_time.isoformat() if auction.start_time else None,
            "duration": auction.duration,
            "visibility": "PUBLIC" if display_status == "LIVE" else "DRAFT",
            "auctionTitle": auction.auction_title,
            "winnerPaymentPaid": bool(getattr(auction, "winner_payment_paid", False)),
        }

    @staticmethod
    def build_profile_summaries_by_community(
        auctions: list[CommunityAuction],
    ) -> dict[str, dict]:
        summaries: dict[str, dict] = {}
        for auction in auctions:
            key = str(auction.community_id)
            if key not in summaries:
                summaries[key] = CommunityAuctionService.to_profile_summary(auction)
        return summaries

    @staticmethod
    def _build_profile_sync_event(
        auction: CommunityAuction,
        event: str,
    ) -> dict:
        summary = CommunityAuctionService.to_profile_summary(auction)
        return {
            "event": event,
            "type": event,
            **summary,
        }

    @staticmethod
    def _broadcast_profile_sync(
        auction: CommunityAuction,
        event: str,
    ) -> None:
        payload = CommunityAuctionService._build_profile_sync_event(auction, event)
        try:
            anyio.from_thread.run(
                community_auction_connection_manager.broadcast_to_auction,
                f"community_profile_{auction.community_id}",
                payload,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Creator profile auction sync failed community=%s event=%s",
                auction.community_id,
                event,
            )

    @staticmethod
    def _broadcast_bid_update(
        auction: CommunityAuction,
        bid_data: dict,
        *,
        extended: bool = False,
    ) -> None:
        payload = CommunityAuctionService._build_bid_placed_event(
            auction,
            bid_data,
            extended=extended,
        )
        try:
            anyio.from_thread.run(
                community_auction_connection_manager.broadcast_to_auction,
                f"community_auction_{auction.id}",
                payload,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Bid saved but live WebSocket broadcast failed"
            )
        CommunityAuctionService._broadcast_profile_sync(auction, "new_bid_received")
        if extended:
            CommunityAuctionService._broadcast_profile_sync(
                auction,
                "creator_auction_updated",
            )

    @staticmethod
    def _broadcast_auction_event(auction_id: uuid.UUID, payload: dict) -> None:
        try:
            anyio.from_thread.run(
                community_auction_connection_manager.broadcast_to_auction,
                f"community_auction_{auction_id}",
                payload,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Creator auction live broadcast failed room=%s", auction_id
            )

    @staticmethod
    def _build_auction_ended_event(
        auction: CommunityAuction,
        *,
        event_type: str,
        message: str,
        winner_name: str | None = None,
    ) -> dict:
        return {
            "type": event_type,
            "auctionId": str(auction.id),
            "status": auction.status,
            "currentHighestBid": float(auction.current_highest_bid or 0),
            "totalBids": auction.total_bids,
            "endTime": auction.end_time.isoformat() if auction.end_time else None,
            "currentWinnerName": winner_name,
            "winnerPaymentPaid": bool(getattr(auction, "winner_payment_paid", False)),
            "message": message,
        }

    @staticmethod
    def _get_user_display_name(user: AppUser) -> str:
        first_name = getattr(user, "firstname", None) or getattr(user, "first_name", None)
        last_name = getattr(user, "lastname", None) or getattr(user, "last_name", None)

        full_name = " ".join(
            part for part in [first_name, last_name] if part
        ).strip()

        if full_name:
            return full_name

        username = getattr(user, "username", None)
        if username:
            return username

        return user.email

    @staticmethod
    def create_auction(
        db: Session,
        request: CommunityAuctionCreateRequest,
        current_user: AppUser,
    ) -> dict:
        try:
            community_id = uuid.UUID(request.community_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid community_id",
            ) from None

        community = CommunityRepository.find_by_id(
            db=db,
            community_id=community_id,
        )

        if not community:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Creator profile not found",
            )

        if community.app_user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only auction your own community profile",
            )

        from app.utils.admin_fee_roles import role_waives_auction_platform_fees
        is_admin = role_waives_auction_platform_fees(getattr(current_user, "role", None))

        existing_auction = CommunityAuctionRepository.find_by_community_id(
            db=db,
            community_id=community_id,
        )

        if existing_auction:
            if existing_auction.status in {
                CommunityAuctionStatus.PAYMENT_PENDING.value,
                CommunityAuctionStatus.ACTIVE.value,
                CommunityAuctionStatus.EXTENDED.value,
            }:
                # End-to-end UX compatibility with frontend modal:
                # if payment is still pending, refresh fields and return the same row
                # so UI can continue directly to listing-fee payment.
                if existing_auction.status == CommunityAuctionStatus.PAYMENT_PENDING.value:
                    CommunityAuctionService._prepare_auction_for_new_listing(
                        db=db,
                        auction=existing_auction,
                        request=request,
                        current_user=current_user,
                        clear_bids=False,
                    )
                    saved_auction = CommunityAuctionRepository.save(
                        db=db,
                        auction=existing_auction,
                    )
                    CommunityAuctionService._broadcast_profile_sync(
                        saved_auction,
                        "creator_auction_updated",
                    )
                    return CommunityAuctionService._to_response(saved_auction)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="You already have a live auction. View it from your Creator profile.",
                )

            if existing_auction.status in CommunityAuctionService._TERMINAL_LISTING_STATUSES:
                CommunityAuctionService._prepare_auction_for_new_listing(
                    db=db,
                    auction=existing_auction,
                    request=request,
                    current_user=current_user,
                    clear_bids=True,
                )
                duration = CommunityAuctionDuration(request.duration.value)
                now = datetime.now(timezone.utc)
                end_time = now + timedelta(days=duration.days)
                existing_auction.status = CommunityAuctionStatus.ACTIVE.value
                existing_auction.start_time = now
                existing_auction.end_time = end_time
                existing_auction.original_end_time = end_time
                existing_auction.listing_fee_paid = True
                saved_auction = CommunityAuctionRepository.save(
                    db=db,
                    auction=existing_auction,
                )
                if not is_admin:
                    consume_creation_fee_sync(
                        db,
                        user_id=current_user.id,
                        order_id=request.creation_fee_order_id,
                        auction_id=saved_auction.id,
                    )
                db.commit()
                NotificationService.notify(
                    db=db,
                    user=current_user,
                    notification_type=NotificationType.AUCTION_UPDATE,
                    title="Creator auction created",
                    message="Your community auction is now active.",
                    target_url="/community-auctions",
                )
                CommunityAuctionService._broadcast_profile_sync(
                    saved_auction,
                    "creator_auction_live",
                )
                return CommunityAuctionService._to_response(saved_auction)

        duration = CommunityAuctionDuration(request.duration.value)
        now = datetime.now(timezone.utc)
        end_time = now + timedelta(days=duration.days)

        auction = CommunityAuction(
            community_id=community_id,
            created_by=current_user.id,
            status=CommunityAuctionStatus.ACTIVE.value,
            duration=request.duration.value,
            min_bid_price=request.min_bid_price,
            current_highest_bid=None,
            total_bids=0,
            current_winner_id=None,
            start_time=now,
            end_time=end_time,
            original_end_time=end_time,
            listing_fee_paid=True,
            winner_payment_order_id=None,
            winner_payment_id=None,
            winner_payment_paid=False,
            auction_title=request.auction_title,
            auction_skills=request.auction_skills,
            work_type=request.work_type.value if request.work_type else None,
            expected_rate=request.expected_rate,
            available_from=request.available_from,
            additional_info=request.additional_info,
        )

        saved_auction = CommunityAuctionRepository.save(
            db=db,
            auction=auction,
        )
        if not is_admin:
            consume_creation_fee_sync(
                db,
                user_id=current_user.id,
                order_id=request.creation_fee_order_id,
                auction_id=saved_auction.id,
            )
        db.commit()

        NotificationService.notify(
            db=db,
            user=current_user,
            notification_type=NotificationType.AUCTION_UPDATE,
            title="Creator auction created",
            message="Your community auction is now active.",
            target_url="/community-auctions",
        )

        CommunityAuctionService._broadcast_profile_sync(
            saved_auction,
            "creator_auction_created",
        )
        CommunityAuctionService._broadcast_profile_sync(
            saved_auction,
            "creator_auction_live",
        )

        return CommunityAuctionService._to_response(saved_auction)

    @staticmethod
    def get_all_auctions(db: Session) -> list[dict]:
        auctions = CommunityAuctionRepository.find_all(db)

        return [
            CommunityAuctionService._to_response(auction)
            for auction in auctions
        ]

    @staticmethod
    def get_all_auctions_for_admin(db: Session) -> list[dict]:
        auctions = CommunityAuctionRepository.find_all_with_details(db)
        rows: list[dict] = []
        for auction in auctions:
            auction_payload = CommunityAuctionService._to_response(auction)
            community = auction.community
            community_payload = None
            if community is not None:
                profile_user = getattr(community, "app_user", None)
                community_payload = {
                    "id": str(community.id),
                    "name": community.name,
                    "email": profile_user.email if profile_user else None,
                    "role": (
                        community.role.value
                        if hasattr(community.role, "value")
                        else community.role
                    ),
                    "industry": community.industry,
                    "imageUrl": community.image_url,
                }
                auction_payload["community"] = community_payload
            creator = auction.creator
            if creator is not None:
                auction_payload["creator"] = {
                    "id": str(creator.id),
                    "firstname": creator.firstname,
                    "lastname": creator.lastname,
                    "email": creator.email,
                }
            winner = auction.current_winner
            if winner is not None:
                auction_payload["currentWinner"] = {
                    "id": str(winner.id),
                    "firstname": winner.firstname,
                    "lastname": winner.lastname,
                    "email": winner.email,
                }
            bids = CommunityAuctionBidRepository.find_by_auction_id(
                db=db,
                auction_id=auction.id,
            )
            bids_payload = [
                CommunityAuctionService._bid_to_response(b)
                for b in bids
            ]
            rows.append(
                {
                    "auction": auction_payload,
                    "community": community_payload,
                    "bids": bids_payload,
                }
            )
        return rows

    @staticmethod
    def get_my_auctions(
        db: Session,
        current_user: AppUser,
    ) -> list[dict]:
        from app.utils.auction_tracking import seller_tracking_fields

        auctions = CommunityAuctionRepository.find_by_creator_id(
            db=db,
            created_by=current_user.id,
        )
        seller = seller_tracking_fields()
        items: list[dict] = []
        for auction in auctions:
            item = CommunityAuctionService._to_response(auction)
            item = CommunityAuctionService._enrich_auction_response(
                db, item, auction
            )
            item.update(seller)
            item["auctionType"] = "CREATOR"
            items.append(item)
        return items

    @staticmethod
    def get_my_bids(
        db: Session,
        current_user: AppUser,
    ) -> list[dict]:
        from app.repository.community_auction_bid_repository import (
            CommunityAuctionBidRepository,
        )
        from app.utils.auction_tracking import bidder_tracking_fields

        bids = CommunityAuctionBidRepository.find_by_bidder_id(
            db=db,
            bidder_id=current_user.id,
        )
        best_by_auction: dict[uuid.UUID, float] = {}
        for bid in bids:
            amount = float(bid.amount or 0)
            prev = best_by_auction.get(bid.auction_id)
            if prev is None or amount > prev:
                best_by_auction[bid.auction_id] = amount

        if not best_by_auction:
            return []

        items: list[dict] = []
        for auction_id, user_high in best_by_auction.items():
            auction = CommunityAuctionRepository.find_by_id(
                db=db,
                auction_id=auction_id,
            )
            if auction is None:
                continue
            item = CommunityAuctionService._to_response(auction)
            item = CommunityAuctionService._enrich_auction_response(
                db, item, auction
            )
            item.update(
                bidder_tracking_fields(
                    user_id=current_user.id,
                    user_highest_bid=user_high,
                    current_highest_bid=float(auction.current_highest_bid or 0),
                    current_winner_id=auction.current_winner_id,
                    status=auction.status,
                )
            )
            item["auctionType"] = "CREATOR"
            items.append(item)

        items.sort(
            key=lambda row: row.get("endTime") or row.get("end_time") or "",
            reverse=True,
        )
        return items

    @staticmethod
    def get_auction_by_id(
        db: Session,
        auction_id: uuid.UUID,
    ) -> dict:
        auction = CommunityAuctionRepository.find_by_id(
            db=db,
            auction_id=auction_id,
        )

        if not auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Creator auction not found",
            )

        return CommunityAuctionService._enrich_auction_response(
            db,
            CommunityAuctionService._to_response(auction),
            auction,
        )

    @staticmethod
    def activate_auction_after_payment(
        db: Session,
        auction_id: uuid.UUID,
        current_user: AppUser,
        payment_id: str = "manual-test-payment",
    ) -> dict:
        auction = CommunityAuctionRepository.find_by_id(
            db=db,
            auction_id=auction_id,
        )

        if not auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Creator auction not found",
            )

        if auction.created_by != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only activate your own auction",
            )

        if auction.status != CommunityAuctionStatus.PAYMENT_PENDING.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Auction is not waiting for payment",
            )

        duration = CommunityAuctionDuration(auction.duration)
        now = datetime.now(timezone.utc)
        end_time = now + timedelta(days=duration.days)

        auction.status = CommunityAuctionStatus.ACTIVE.value
        auction.listing_fee_paid = True
        auction.listing_fee_payment_id = payment_id
        auction.start_time = now
        auction.end_time = end_time
        auction.original_end_time = end_time

        saved_auction = CommunityAuctionRepository.save(
            db=db,
            auction=auction,
        )

        NotificationService.notify(
            db=db,
            user=current_user,
            notification_type=NotificationType.AUCTION_UPDATE,
            title="Creator auction activated",
            message="Your community auction is now active.",
            target_url="/community-auctions",
        )

        CommunityAuctionService._broadcast_profile_sync(
            saved_auction,
            "creator_auction_live",
        )

        return CommunityAuctionService._to_response(saved_auction)

    @staticmethod
    def place_bid(
        db: Session,
        auction_id: uuid.UUID,
        request: CommunityAuctionBidRequest,
        current_user: AppUser,
    ) -> dict:
        from app.service.auction.winner_payment_lifecycle import assert_user_can_bid_sync

        assert_user_can_bid_sync(db, current_user)
        try:
            auction = CommunityAuctionRepository.find_by_id_for_update(
                db=db,
                auction_id=auction_id,
            )

            if not auction:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Creator auction not found",
                )

            if auction.status not in {
                CommunityAuctionStatus.ACTIVE.value,
                CommunityAuctionStatus.EXTENDED.value,
            }:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Auction is not active",
                )

            now = utc_now()

            if auction.end_time and auction.end_time < now:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Auction has already ended",
                )

            if auction.created_by == current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You cannot bid on your own auction",
                )

            community = CommunityRepository.find_by_id(db=db, community_id=auction.community_id)
            if community is not None and community.app_user_id == current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You cannot bid on your own auction",
                )

            try:
                amount_f, _minimum_required, _max_allowed = normalize_bid_amount(
                    request.amount,
                    current_highest=auction.current_highest_bid or 0,
                    min_bid_price=auction.min_bid_price,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc
            request.amount = Decimal(str(amount_f))

            fee_row = verify_bid_fee_sync(
                db,
                user_id=current_user.id,
                auction_id=auction_id,
                bid_amount=request.amount,
                razorpay_order_id=request.razorpay_order_id,
                razorpay_payment_id=request.razorpay_payment_id,
                razorpay_signature=request.razorpay_signature,
            )

            CommunityAuctionBidRepository.mark_existing_bids_not_winning(
                db=db,
                auction_id=auction.id,
                commit=False,
            )

            bidder_name = bidder_display_name(current_user)
            bid = CommunityAuctionBid(
                auction_id=auction.id,
                bidder_id=current_user.id,
                bidder_name=bidder_name,
                amount=request.amount,
                bid_time=now,
                winning_bid=True,
            )
            db.add(bid)

            auction.current_highest_bid = request.amount
            auction.current_winner_id = current_user.id
            auction.total_bids += 1

            new_end, new_status, extended = apply_anti_snipe(
                auction.end_time,
                now,
                status=auction.status,
                extended_status=CommunityAuctionStatus.EXTENDED.value,
            )
            auction.end_time = new_end
            auction.status = new_status

            consume_bid_fee_sync(db, fee_row)
            db.add(auction)
            db.commit()
            db.refresh(bid)
            saved_bid = bid
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logging.getLogger(__name__).exception(
                "community.place_bid.failed auction=%s user=%s",
                auction_id,
                current_user.id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to place bid.",
            ) from None

        NotificationService.notify(
            db=db,
            user=current_user,
            notification_type=NotificationType.AUCTION_UPDATE,
            title="Bid placed successfully",
            message="Your bid has been placed successfully.",
            target_url="/community-auctions",
        )

        auction_owner = UserRepository.find_by_id(
            db=db,
            user_id=auction.created_by,
        )

        if auction_owner:
            NotificationService.notify(
                db=db,
                user=auction_owner,
                notification_type=NotificationType.AUCTION_UPDATE,
                title="New bid received",
                message="A new bid has been placed on your community auction.",
                target_url="/community-auctions",
            )

        bid_data = CommunityAuctionService._bid_to_response(saved_bid)

        CommunityAuctionService._broadcast_bid_update(
            auction=auction,
            bid_data=bid_data,
            extended=extended,
        )

        return bid_data

    @staticmethod
    def get_active_auctions(db: Session) -> list[dict]:
        auctions = CommunityAuctionRepository.find_all(db)
        active_statuses = {
            CommunityAuctionStatus.ACTIVE.value,
            CommunityAuctionStatus.EXTENDED.value,
        }
        return [
            CommunityAuctionService._to_response(auction)
            for auction in auctions
            if auction.status in active_statuses
        ]

    @staticmethod
    def get_auction_by_community_id(
        db: Session,
        community_id: uuid.UUID,
    ) -> dict | None:
        auction = CommunityAuctionRepository.find_by_community_id(
            db=db,
            community_id=community_id,
        )
        if not auction:
            return None
        return CommunityAuctionService._to_response(auction)

    @staticmethod
    def get_auction_bids(
        db: Session,
        auction_id: uuid.UUID,
    ) -> list[dict]:
        auction = CommunityAuctionRepository.find_by_id(
            db=db,
            auction_id=auction_id,
        )

        if not auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Creator auction not found",
            )

        bids = CommunityAuctionBidRepository.find_by_auction_id(
            db=db,
            auction_id=auction_id,
        )

        return [
            CommunityAuctionService._bid_to_response(bid)
            for bid in bids
        ]

    @staticmethod
    def re_auction(
        db: Session,
        auction_id: uuid.UUID,
        *,
        min_bid_price: Decimal,
        duration: CommunityAuctionDuration,
        current_user: AppUser,
        creation_fee_order_id: str,
    ) -> dict:
        auction = CommunityAuctionRepository.find_by_id(db=db, auction_id=auction_id)
        if not auction:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Auction not found")
        community = CommunityRepository.find_by_id(db, auction.community_id)
        if not community or community.app_user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your auction")
        if auction.status != CommunityAuctionStatus.UNSOLD.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Can only re-auction an unsold auction",
            )
        now = datetime.now(timezone.utc)
        end_time = now + timedelta(days=duration.days)
        bids = CommunityAuctionBidRepository.find_by_auction_id(db=db, auction_id=auction.id)
        for b in bids:
            CommunityAuctionBidRepository.soft_delete(db=db, bid=b, deleted_by=current_user.id)
        auction.min_bid_price = min_bid_price
        auction.duration = duration.value
        auction.current_highest_bid = None
        auction.current_winner_id = None
        auction.total_bids = 0
        auction.status = CommunityAuctionStatus.ACTIVE.value
        auction.start_time = now
        auction.end_time = end_time
        auction.original_end_time = end_time
        auction.winner_payment_order_id = None
        auction.winner_payment_id = None
        auction.winner_payment_paid = False
        CommunityAuctionRepository.save(db=db, auction=auction)
        consume_creation_fee_sync(
            db,
            user_id=current_user.id,
            order_id=creation_fee_order_id,
            auction_id=auction.id,
        )
        db.commit()
        CommunityAuctionService._broadcast_profile_sync(auction, "creator_auction_live")
        return CommunityAuctionService._to_response(auction)

    @staticmethod
    def close_auction(db: Session, auction_id: uuid.UUID, current_user: AppUser) -> dict:
        auction = CommunityAuctionRepository.find_by_id(db=db, auction_id=auction_id)
        if not auction:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Auction not found")
        community = CommunityRepository.find_by_id(db, auction.community_id)
        if not community or community.app_user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your auction")
        closable_statuses = {
            CommunityAuctionStatus.UNSOLD.value,
            CommunityAuctionStatus.ACTIVE.value,
            CommunityAuctionStatus.EXTENDED.value,
        }
        if auction.status not in closable_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot close auction in status {auction.status}",
            )

        if auction.status in {
            CommunityAuctionStatus.ACTIVE.value,
            CommunityAuctionStatus.EXTENDED.value,
        } and (auction.total_bids or 0) > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot close an auction that has active bids",
            )

        auction.status = CommunityAuctionStatus.CLOSED.value
        saved = CommunityAuctionRepository.save(db=db, auction=auction)

        CommunityAuctionService._broadcast_auction_event(
            saved.id,
            CommunityAuctionService._build_auction_ended_event(
                saved,
                event_type="AUCTION_CLOSED",
                message="Auction closed by the lister.",
            ),
        )
        CommunityAuctionService._broadcast_profile_sync(
            saved,
            "creator_auction_ended",
        )

        return CommunityAuctionService._to_response(saved)

    @staticmethod
    def end_expired_auctions(db: Session) -> int:
        """Close ACTIVE/EXTENDED auctions whose end_time has passed (Java parity)."""
        now = datetime.now(timezone.utc)
        expired = CommunityAuctionRepository.find_expired_active(db, now)
        for auction in expired:
            try:
                CommunityAuctionService.end_auction(db, auction)
            except Exception:
                logging.getLogger(__name__).exception(
                    "Failed to end community auction id=%s", auction.id
                )
        return len(expired)

    @staticmethod
    def end_auction(db: Session, auction: CommunityAuction) -> dict:
        if auction.status not in {
            CommunityAuctionStatus.ACTIVE.value,
            CommunityAuctionStatus.EXTENDED.value,
        }:
            return CommunityAuctionService._to_response(auction)

        has_winner = (
            auction.total_bids > 0
            and auction.current_highest_bid is not None
            and float(auction.current_highest_bid) > 0
        )

        winner_name: str | None = None
        winner_user: AppUser | None = None

        if has_winner:
            bids = CommunityAuctionBidRepository.find_by_auction_id(db, auction.id)
            for bid in bids:
                bid.winning_bid = False
            top_bid = bids[0] if bids else None
            if top_bid:
                top_bid.winning_bid = True
                auction.current_winner_id = top_bid.bidder_id
                winner_name = top_bid.bidder_name
                winner_user = UserRepository.find_by_id(db, top_bid.bidder_id)
                if winner_user:
                    winner_name = CommunityAuctionService._get_user_display_name(winner_user)
            auction.status = CommunityAuctionStatus.ENDED.value
            auction.winner_payment_paid = False
            auction.winner_payment_order_id = None
            auction.winner_payment_id = None
            event_type = "AUCTION_ENDED"
            message = (
                f"{winner_name or 'The top bidder'} won with ₹"
                f"{float(auction.current_highest_bid):,.2f}"
            )
        else:
            auction.status = CommunityAuctionStatus.UNSOLD.value
            event_type = "AUCTION_UNSOLD"
            message = "Auction ended with no bids."

        saved = CommunityAuctionRepository.save(db=db, auction=auction)

        CommunityAuctionService._broadcast_auction_event(
            saved.id,
            CommunityAuctionService._build_auction_ended_event(
                saved,
                event_type=event_type,
                message=message,
                winner_name=winner_name,
            ),
        )
        CommunityAuctionService._broadcast_profile_sync(
            saved,
            "creator_auction_ended",
        )

        community = CommunityRepository.find_by_id(db, saved.community_id)
        lister: AppUser | None = None
        if community:
            lister = UserRepository.find_by_id(db, community.app_user_id)

        if has_winner and winner_user:
            NotificationService.notify(
                db,
                user=winner_user,
                notification_type=NotificationType.COMMUNITY_AUCTION_ENDED,
                title="You Won the Profile Auction!",
                message=(
                    f'You won the auction for "{saved.auction_title}" with a bid of ₹'
                    f"{float(saved.current_highest_bid):,.2f}. "
                    "Complete payment to finalize your win."
                ),
                target_url=f"/community-auction/{saved.id}",
            )
            # Persist 7-day payment window in platform_settings (no schema change).
            if hasattr(db, "query"):
                try:
                    import json

                    due = datetime.now(timezone.utc) + timedelta(days=7)
                    key = f"wpt:COMMUNITY:{saved.id}"
                    payload = {
                        "auctionType": "COMMUNITY",
                        "auctionId": str(saved.id),
                        "winnerUserId": str(winner_user.id),
                        "sellerUserId": str(lister.id) if lister else None,
                        "winningAmount": float(saved.current_highest_bid or 0),
                        "title": saved.auction_title or str(saved.id),
                        "payPath": f"/creator-auction/{saved.id}",
                        "dueAt": due.isoformat(),
                        "winEmailSentAt": None,
                        "reminderSentOn": None,
                        "forfeitedAt": None,
                    }
                    row = (
                        db.query(PlatformSetting)
                        .filter(PlatformSetting.setting_key == key)
                        .first()
                    )
                    if row is None:
                        db.add(
                            PlatformSetting(
                                setting_key=key,
                                setting_value=json.dumps(payload),
                                updated_at=datetime.now(timezone.utc),
                            )
                        )
                    else:
                        row.setting_value = json.dumps(payload)
                        row.updated_at = datetime.now(timezone.utc)
                    db.commit()
                except Exception:
                    logging.getLogger(__name__).exception(
                        "creator.winner_window_persist_failed auction=%s", saved.id
                    )

        if lister:
            if has_winner:
                NotificationService.notify(
                    db,
                    user=lister,
                    notification_type=NotificationType.COMMUNITY_AUCTION_ENDED,
                    title="Your Profile Auction Has Ended",
                    message=(
                        f"Your profile was won by {winner_name or 'the top bidder'} "
                        f"for ₹{float(saved.current_highest_bid):,.2f}. "
                        "The winner must complete payment to finalize."
                    ),
                    target_url="/community",
                )
            else:
                NotificationService.notify(
                    db,
                    user=lister,
                    notification_type=NotificationType.COMMUNITY_AUCTION_ENDED,
                    title="Auction Ended — No Bids",
                    message=(
                        f'Your profile auction "{saved.auction_title}" ended with no bids. '
                        "The creation fee is not refunded for zero-bid auctions. "
                        "Pay again to re-list — tip: improve your profile details and starting bid."
                    ),
                    target_url="/auctions?view=yours",
                )

        return CommunityAuctionService._enrich_auction_response(
            db,
            CommunityAuctionService._to_response(saved),
            saved,
        )

    @staticmethod
    def create_winner_payment_order(
        db: Session,
        auction_id: uuid.UUID,
        current_user: AppUser,
    ) -> dict:
        auction = CommunityAuctionRepository.find_by_id(db=db, auction_id=auction_id)
        if not auction:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Auction not found")
        if auction.current_winner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the auction winner can pay the winning bid amount.",
            )
        if auction.status != CommunityAuctionStatus.ENDED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Auction is not awaiting winner payment.",
            )
        if auction.winner_payment_paid:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Winning bid has already been paid.",
            )
        amount = float(auction.current_highest_bid or 0)
        if amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid winning bid amount.",
            )
        if not rzp.is_configured():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Payment gateway is not configured.",
            )
        receipt = f"comm_win_{str(auction_id).replace('-', '')[:12]}"
        try:
            order = rzp.create_order(
                amount_inr=amount,
                receipt=receipt,
                notes={
                    "auctionId": str(auction_id),
                    "type": "community_auction_winner_payment",
                },
            )
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).exception("community_auction.winner_payment.order_failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Payment order creation failed: {exc!s}",
            ) from exc

        auction.winner_payment_order_id = order["id"]
        CommunityAuctionRepository.save(db=db, auction=auction)
        return {
            "orderId": order["id"],
            "amount": amount,
            "currency": "INR",
            "keyId": rzp.get_key_id(),
            "auctionId": str(auction_id),
        }

    @staticmethod
    def verify_winner_payment(
        db: Session,
        auction_id: uuid.UUID,
        *,
        razorpay_payment_id: str,
        razorpay_order_id: str,
        razorpay_signature: str,
        current_user: AppUser,
    ) -> dict:
        auction = CommunityAuctionRepository.find_by_id(db=db, auction_id=auction_id)
        if not auction:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Auction not found")
        if auction.current_winner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the auction winner can verify this payment.",
            )
        if auction.winner_payment_paid and auction.status == CommunityAuctionStatus.COMPLETED.value:
            return {
                "success": True,
                "message": "Winning bid payment already completed.",
                "auction": CommunityAuctionService._enrich_auction_response(
                    db,
                    CommunityAuctionService._to_response(auction),
                    auction,
                ),
            }
        if auction.status != CommunityAuctionStatus.ENDED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Auction is not awaiting winner payment.",
            )
        if auction.winner_payment_order_id and auction.winner_payment_order_id != razorpay_order_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Order id does not match this auction payment.",
            )
        if not rzp.verify_payment_signature(
            razorpay_order_id, razorpay_payment_id, razorpay_signature
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment verification failed — invalid signature",
            )

        auction.winner_payment_paid = True
        auction.winner_payment_id = razorpay_payment_id
        auction.status = CommunityAuctionStatus.COMPLETED.value
        saved = CommunityAuctionRepository.save(db=db, auction=auction)

        winner_name = CommunityAuctionService._get_user_display_name(current_user)
        community = CommunityRepository.find_by_id(db, saved.community_id)
        lister = (
            UserRepository.find_by_id(db, community.app_user_id)
            if community
            else None
        )

        NotificationService.notify(
            db,
            user=current_user,
            notification_type=NotificationType.COMMUNITY_AUCTION_ENDED,
            title="Payment Complete",
            message=(
                f'Your payment of ₹{float(saved.current_highest_bid):,.2f} for '
                f'"{saved.auction_title}" was successful. Our team will coordinate next steps.'
            ),
            target_url=f"/community-auction/{saved.id}",
        )
        if lister:
            NotificationService.notify(
                db,
                user=lister,
                notification_type=NotificationType.COMMUNITY_AUCTION_ENDED,
                title="Winner Payment Received",
                message=(
                    f"{winner_name} completed payment of ₹"
                    f"{float(saved.current_highest_bid):,.2f} for your profile auction."
                ),
                target_url="/community",
            )

        CommunityAuctionService._broadcast_auction_event(
            saved.id,
            {
                "type": "PAYMENT_COMPLETED",
                "auctionId": str(saved.id),
                "status": saved.status,
                "currentHighestBid": float(saved.current_highest_bid or 0),
                "winnerPaymentPaid": True,
                "message": "Winner payment completed.",
            },
        )
        CommunityAuctionService._broadcast_profile_sync(
            saved,
            "creator_auction_updated",
        )

        return {
            "success": True,
            "message": "Winning bid payment verified. Auction is now complete.",
            "auction": CommunityAuctionService._enrich_auction_response(
                db,
                CommunityAuctionService._to_response(saved),
                saved,
            ),
        }
