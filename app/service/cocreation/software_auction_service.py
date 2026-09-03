"""Software auction lifecycle — request, approve, bid, end."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.cocreation.software_auction import SoftwareAuction
from app.entity.cocreation.software_auction_bid import SoftwareAuctionBid
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.integrations.s3.supabase_storage import resolve_media_url
from app.integrations.razorpay import client as rzp
from app.entity.platform.admin_audit_log import AdminAuditLog
from app.repository.admin_audit_log_repository import AdminAuditLogRepository
from app.model.cocreation.software_auction_mapper import (
    auction_to_api,
    build_admin_item,
    build_by_software_payload,
    build_detail_payload,
    software_to_api,
)
from app.repository.software_auction_repository import (
    SoftwareAuctionBidRepository,
    SoftwareAuctionRepository,
)
from app.entity.auction.auction_participation_entity import AuctionParticipationType
from app.repository.auction_participation_repository import AuctionParticipationRepository
from app.repository.software_auction_participation_repository import (
    SoftwareAuctionParticipationRepository,
)
from app.repository.software_repository import SoftwareRepository
from app.service.cocreation.technology_verification_guard import ensure_technology_verified
from app.entity.auction.auction_fee_payment_entity import AuctionFeeAuctionType
from app.service.auction.auction_fee_service import AuctionFeeService
from app.utils.auction_place_bid_common import (
    apply_anti_snipe,
    bidder_display_name,
    build_bid_placed_ws_event,
    normalize_bid_amount,
    utc_now,
)
from app.utils.cocreation_enums import (
    SoftwareAuctionApprovalStatus,
    SoftwareAuctionDuration,
    SoftwarePurchaseType,
    SoftwareStatus,
)
from app.utils.enums import AuctionStatus

logger = logging.getLogger(__name__)



async def _broadcast_software_auction(auction_id: uuid.UUID, event: dict[str, Any]) -> None:
    try:
        from app.websocket.manager import broadcast_to_auction

        await broadcast_to_auction(f"software_auction_{auction_id}", event)
    except Exception:
        logger.debug("software auction ws broadcast skipped", exc_info=True)


class SoftwareAuctionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._auctions = SoftwareAuctionRepository(session)
        self._bids = SoftwareAuctionBidRepository(session)
        self._software = SoftwareRepository(session)
        self._participations = SoftwareAuctionParticipationRepository(session)
        self._auction_participations = AuctionParticipationRepository(session)
        self._fee_service = AuctionFeeService(session)

    async def _participation_fee_paid(
        self,
        auction_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Check unified auction_participations first, then legacy software_auction_participations."""
        unified = getattr(self, "_auction_participations", None)
        if unified is not None:
            if await unified.has_completed(
                AuctionParticipationType.SOFTWARE,
                auction_id,
                user_id,
            ):
                return True
        return await self._participations.has_completed(auction_id, user_id)

    async def create_auction(
        self,
        software_id: uuid.UUID,
        *,
        min_bid_price: float,
        duration: SoftwareAuctionDuration,
        auction_rationale: str,
        source_code_included: bool = False,
        support_included: bool = False,
        support_days: int = 0,
        transfer_details: Optional[str] = None,
        lister: AppUser,
        creation_fee_order_id: str,
    ) -> SoftwareAuction:
        software = await self._software.get_by_id(software_id)
        if software is None:
            raise AppException("Software listing not found.", status_code=404)
        if software.listed_by_user_id != lister.id:
            raise AppException("Not your listing.", status_code=403)
        existing = await self._auctions.get_by_software_id(software_id)
        if existing is not None:
            if existing.approval_status == SoftwareAuctionApprovalStatus.REJECTED:
                existing.min_bid_price = min_bid_price
                existing.duration = duration
                existing.auction_rationale = auction_rationale.strip()
                existing.source_code_included = source_code_included
                existing.support_included = support_included
                existing.support_days = support_days if support_included else 0
                existing.transfer_details = (transfer_details or "").strip() or None
                existing.approval_status = SoftwareAuctionApprovalStatus.PENDING_APPROVAL
                existing.status = AuctionStatus.DRAFT
                existing.rejection_reason = None
                await self._auctions.save(existing)
                if software.purchase_type != SoftwarePurchaseType.AUCTION:
                    software.purchase_type = SoftwarePurchaseType.AUCTION
                software.software_status = SoftwareStatus.PENDING
                await self._software.save(software)
                await self._session.commit()
                return await self._auctions.get_by_software_id(software_id) or existing
            # Frontend "Put in Auction" can be retried; keep this idempotent.
            if existing.approval_status in {
                SoftwareAuctionApprovalStatus.PENDING_APPROVAL,
                SoftwareAuctionApprovalStatus.APPROVED,
            }:
                return existing
            raise AppException("Auction already exists for this software.", status_code=409)

        auction = SoftwareAuction(
            software_id=software_id,
            min_bid_price=min_bid_price,
            duration=duration,
            status=AuctionStatus.DRAFT,
            approval_status=SoftwareAuctionApprovalStatus.PENDING_APPROVAL,
            auction_rationale=auction_rationale.strip(),
            source_code_included=source_code_included,
            support_included=support_included,
            support_days=support_days if support_included else 0,
            transfer_details=(transfer_details or "").strip() or None,
        )
        auction = await self._auctions.create(auction)

        if software.purchase_type != SoftwarePurchaseType.AUCTION:
            software.purchase_type = SoftwarePurchaseType.AUCTION
        software.software_status = SoftwareStatus.PENDING
        await self._software.save(software)
        from app.utils.admin_fee_roles import role_waives_auction_platform_fees
        if not role_waives_auction_platform_fees(getattr(lister, "role", None)):
            await self._fee_service.consume_creation_fee(
                user=lister,
                auction_type=AuctionFeeAuctionType.SOFTWARE,
                creation_fee_order_id=creation_fee_order_id,
                auction_id=auction.id,
            )

        await self._session.commit()
        loaded = await self._auctions.get_by_software_id(software_id)
        return loaded or auction

    async def approve_auction(self, auction_id: uuid.UUID) -> SoftwareAuction:
        auction = await self._auctions.get_by_id(auction_id)
        if auction is None:
            raise AppException("Auction not found.", status_code=404)
        if auction.approval_status != SoftwareAuctionApprovalStatus.PENDING_APPROVAL:
            raise AppException("Auction is not pending approval.", status_code=400)

        now = datetime.now(timezone.utc)
        end = now + timedelta(days=auction.duration.to_days())
        auction.approval_status = SoftwareAuctionApprovalStatus.APPROVED
        auction.status = AuctionStatus.ACTIVE
        auction.start_time = now
        auction.end_time = end
        auction.original_end_time = end
        await self._auctions.save(auction)
        software = await self._software.get_by_id(auction.software_id)
        if software is not None:
            software.software_status = SoftwareStatus.AVAILABLE
            await self._software.save(software)
        await self._session.commit()
        return await self._auctions.get_by_id(auction_id) or auction

    async def reject_auction(
        self,
        auction_id: uuid.UUID,
        *,
        reason: str,
    ) -> SoftwareAuction:
        auction = await self._auctions.get_by_id(auction_id)
        if auction is None:
            raise AppException("Auction not found.", status_code=404)
        if auction.approval_status != SoftwareAuctionApprovalStatus.PENDING_APPROVAL:
            raise AppException("Auction is not pending approval.", status_code=400)

        auction.approval_status = SoftwareAuctionApprovalStatus.REJECTED
        auction.rejection_reason = reason.strip()
        auction.status = AuctionStatus.CLOSED
        await self._auctions.save(auction)
        software = await self._software.get_by_id(auction.software_id)
        if software is not None:
            software.software_status = SoftwareStatus.AVAILABLE
            software.purchase_type = SoftwarePurchaseType.ONE_TIME
            await self._software.save(software)
        await self._session.commit()
        return auction

    async def place_bid(
        self,
        auction_id: uuid.UUID,
        amount: float,
        *,
        bidder: AppUser,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> dict[str, Any]:
        from app.service.auction.winner_payment_lifecycle import assert_user_can_bid_async

        await assert_user_can_bid_async(self._session, bidder)
        stmt = (
            select(SoftwareAuction)
            .where(SoftwareAuction.id == auction_id)
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        auction = result.scalar_one_or_none()
        if auction is None:
            raise AppException("Auction not found.", status_code=404)

        if auction.approval_status != SoftwareAuctionApprovalStatus.APPROVED:
            raise AppException("Auction is not approved yet.", status_code=400)
        if auction.status not in (AuctionStatus.ACTIVE, AuctionStatus.EXTENDED):
            raise AppException("Auction is not active.", status_code=400)

        now = utc_now()
        if auction.end_time and now > auction.end_time:
            raise AppException("Auction has ended.", status_code=400)

        software = await self._software.get_by_id(auction.software_id)
        if software and software.listed_by_user_id == bidder.id:
            raise AppException("You cannot bid on your own listing.", status_code=400)
        if software:
            await ensure_technology_verified(self._session, software.id)

        try:
            amount, _min_required, _max_allowed = normalize_bid_amount(
                amount,
                current_highest=auction.current_highest_bid or 0,
                min_bid_price=auction.min_bid_price,
            )
        except ValueError as exc:
            raise AppException(str(exc), status_code=400) from exc

        fee_row = await self._fee_service.verify_bid_fee_payment(
            auction_type=AuctionFeeAuctionType.SOFTWARE,
            auction_id=auction.id,
            user=bidder,
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
            expected_bid_amount=amount,
        )

        bidder_name = bidder_display_name(bidder)
        bid = SoftwareAuctionBid(
            software_auction_id=auction.id,
            bidder_id=bidder.id,
            amount=amount,
            bidder_name=bidder_name or bidder.email,
            bid_time=now,
        )
        await self._bids.create(bid)

        auction.current_highest_bid = amount
        auction.current_winner_id = bidder.id
        auction.total_bids += 1

        new_end, new_status, extended = apply_anti_snipe(
            auction.end_time,
            now,
            status=auction.status,
            extended_status=AuctionStatus.EXTENDED,
        )
        auction.end_time = new_end
        auction.status = new_status

        await self._fee_service.consume_bid_fee(fee_row)
        await self._auctions.save(auction)
        await self._session.commit()

        event = build_bid_placed_ws_event(
            auction_id=auction.id,
            status=auction.status,
            current_highest_bid=auction.current_highest_bid,
            total_bids=auction.total_bids,
            end_time=auction.end_time,
            bidder_name=bid.bidder_name,
            amount=amount,
            bid_time=now,
            extended=extended,
            bid_id=bid.id,
            bidder_id=bid.bidder_id,
        )
        await _broadcast_software_auction(auction.id, event)

        return {
            "queued": True,
            "message": "Bid placed successfully",
            "amount": amount,
        }

    async def get_auction_detail(self, auction_id: uuid.UUID) -> dict[str, Any]:
        auction = await self._auctions.get_by_id(auction_id, load_bids=True)
        if auction is None:
            raise AppException("Auction not found.", status_code=404)
        bids = await self._bids.list_by_auction(auction_id)
        return build_detail_payload(auction, list(bids))

    async def get_by_software(self, software_id: uuid.UUID) -> dict[str, Any]:
        auction = await self._auctions.get_by_software_id(software_id)
        if auction is None:
            return build_by_software_payload(None, [])
        bids = await self._bids.list_by_auction(auction.id)
        return build_by_software_payload(auction, list(bids))

    def _card_payload(self, a: SoftwareAuction) -> dict[str, Any]:
        return {
            "id": str(a.id),
            "softwareId": str(a.software_id),
            "status": a.status.value if hasattr(a.status, "value") else a.status,
            "approvalStatus": (
                a.approval_status.value
                if hasattr(a.approval_status, "value")
                else a.approval_status
            ),
            "minBidPrice": a.min_bid_price,
            "currentHighestBid": a.current_highest_bid,
            "totalBids": a.total_bids,
            "startTime": (
                a.start_time.isoformat()
                if getattr(a, "start_time", None)
                else None
            ),
            "endTime": (
                a.end_time.isoformat()
                if getattr(a, "end_time", None)
                else None
            ),
            "featured": bool(getattr(a, "featured", False)),
            "name": a.software.name if a.software else None,
            "imageUrl": (
                resolve_media_url(a.software.image_url) if a.software and a.software.image_url else None
            ),
            "category": a.software.category.value if (
                a.software and hasattr(a.software.category, "value")
            ) else (a.software.category if a.software else None),
            "software": software_to_api(a.software) if a.software else None,
            "auctionType": "TECHNOLOGY",
            "currentWinnerId": str(a.current_winner_id) if a.current_winner_id else None,
        }

    async def list_active(self) -> list[dict[str, Any]]:
        auctions = list(await self._auctions.list_active())
        auctions.sort(
            key=lambda a: a.end_time or datetime.max.replace(tzinfo=timezone.utc),
        )
        return [self._card_payload(a) for a in auctions]

    async def list_my_auctions(self, user: AppUser) -> list[dict[str, Any]]:
        """Technology auctions for software listed by the current user."""
        from app.utils.auction_tracking import seller_tracking_fields

        auctions = list(await self._auctions.list_by_lister_user_id(user.id))
        seller = seller_tracking_fields()
        items = []
        for a in auctions:
            item = self._card_payload(a)
            item.update(seller)
            items.append(item)
        return items

    async def list_my_bids(self, user: AppUser) -> list[dict[str, Any]]:
        """Technology auctions the current user has bid on."""
        from app.utils.auction_tracking import bidder_tracking_fields

        bids = list(await self._bids.list_by_bidder_id(user.id))
        best_by_auction: dict[uuid.UUID, float] = {}
        for bid in bids:
            amount = float(bid.amount or 0)
            prev = best_by_auction.get(bid.software_auction_id)
            if prev is None or amount > prev:
                best_by_auction[bid.software_auction_id] = amount

        if not best_by_auction:
            return []

        auctions = list(await self._auctions.list_by_ids(list(best_by_auction.keys())))
        items: list[dict[str, Any]] = []
        for a in auctions:
            item = self._card_payload(a)
            user_high = best_by_auction.get(a.id, 0.0)
            item.update(
                bidder_tracking_fields(
                    user_id=user.id,
                    user_highest_bid=user_high,
                    current_highest_bid=float(a.current_highest_bid or 0),
                    current_winner_id=a.current_winner_id,
                    status=a.status,
                )
            )
            items.append(item)

        items.sort(key=lambda row: row.get("endTime") or "", reverse=True)
        return items

    async def list_all_for_admin(self) -> list[dict[str, Any]]:
        auctions = list(await self._auctions.list_all_with_software())
        return [build_admin_item(a) for a in auctions]

    async def list_pending_for_admin(self) -> list[dict[str, Any]]:
        auctions = list(await self._auctions.list_pending())
        return [build_admin_item(a) for a in auctions]

    async def re_auction(
        self,
        auction_id: uuid.UUID,
        *,
        min_bid_price: float,
        duration: SoftwareAuctionDuration,
        lister: AppUser,
        creation_fee_order_id: str,
    ) -> SoftwareAuction:
        auction = await self._auctions.get_by_id(auction_id)
        if auction is None:
            raise AppException("Auction not found.", status_code=404)
        software = await self._software.get_by_id(auction.software_id)
        if software is None or software.listed_by_user_id != lister.id:
            raise AppException("Not your auction.", status_code=403)
        if auction.status != AuctionStatus.UNSOLD:
            raise AppException("Can only re-auction an unsold auction.", status_code=400)

        now = datetime.now(timezone.utc)
        end = now + timedelta(days=duration.to_days())
        auction.min_bid_price = min_bid_price
        auction.duration = duration
        auction.current_highest_bid = 0
        auction.current_winner_id = None
        auction.winner_payment_order_id = None
        auction.winner_payment_id = None
        auction.winner_payment_paid = False
        auction.total_bids = 0
        auction.approval_status = SoftwareAuctionApprovalStatus.APPROVED
        auction.status = AuctionStatus.ACTIVE
        auction.start_time = now
        auction.end_time = end
        auction.original_end_time = end
        await self._bids.clear_winning_flags(auction.id)
        await self._auctions.save(auction)
        await self._fee_service.consume_creation_fee(
            user=lister,
            auction_type=AuctionFeeAuctionType.SOFTWARE,
            creation_fee_order_id=creation_fee_order_id,
            auction_id=auction.id,
        )
        await self._session.commit()
        return await self._auctions.get_by_id(auction_id) or auction

    async def close_auction(self, auction_id: uuid.UUID, *, lister: AppUser) -> dict:
        auction = await self._auctions.get_by_id(auction_id)
        if auction is None:
            raise AppException("Auction not found.", status_code=404)
        software = await self._software.get_by_id(auction.software_id)
        if software is None or software.listed_by_user_id != lister.id:
            raise AppException("Not your auction.", status_code=403)
        if auction.status != AuctionStatus.UNSOLD:
            raise AppException("Can only close an unsold auction.", status_code=400)
        auction.status = AuctionStatus.CLOSED
        await self._auctions.save(auction)
        await self._release_listing_after_auction(auction)
        await self._session.commit()
        return {"success": True}

    async def end_expired_auctions(self) -> int:
        now = datetime.now(timezone.utc)
        expired = await self._auctions.list_expired(now)
        for auction in expired:
            await self._end_auction(auction)
        if expired:
            await self._session.commit()
        return len(expired)

    async def _release_listing_after_auction(self, auction: SoftwareAuction) -> None:
        """Re-enable direct purchase after an auction ends without a sale (Java parity)."""
        software = await self._software.get_by_id(auction.software_id)
        if software is None:
            return
        software.purchase_type = SoftwarePurchaseType.ONE_TIME
        software.software_status = SoftwareStatus.AVAILABLE
        await self._software.save(software)

    async def _end_auction(self, auction: SoftwareAuction) -> None:
        if auction.total_bids == 0:
            auction.status = AuctionStatus.UNSOLD
        else:
            auction.status = AuctionStatus.ENDED
            auction.winner_payment_paid = False
            auction.winner_payment_order_id = None
            auction.winner_payment_id = None
            bids = await self._bids.list_by_auction(auction.id)
            if bids:
                top = max(bids, key=lambda b: b.amount)
                await self._bids.clear_winning_flags(auction.id)
                top.is_winning_bid = True
                auction.current_winner_id = top.bidder_id
                await self._bids.save(top)
        await self._auctions.save(auction)
        if auction.status in (AuctionStatus.UNSOLD, AuctionStatus.CLOSED):
            await self._release_listing_after_auction(auction)
            try:
                from app.service.auction.winner_payment_lifecycle import (
                    WinnerPaymentLifecycleAsync,
                )
                from app.service.auction.auction_notification_service import _notify_sync
                from app.entity.user.app_user import AppUser as _AppUser

                soft = auction.software
                seller_id = soft.listed_by_user_id if soft else None
                title = soft.name if soft else str(auction.id)
                if seller_id:
                    life = WinnerPaymentLifecycleAsync(self._session)
                    first = await life.mark_zero_bid_notice_sent(
                        "SOFTWARE", auction.id, seller_id, title
                    )
                    if first:
                        seller = await self._session.get(_AppUser, seller_id)
                        if seller:
                            _notify_sync(
                                seller,
                                title="Your technology auction ended with no bids",
                                message=(
                                    f'“{title}” received no bids. Creation fee is not refunded. '
                                    "Pay again to re-list. Tip: improve the listing and starting bid."
                                ),
                                target_url=f"/technology/auction/{auction.id}",
                            )
            except Exception:
                logger.exception("software.zero_bid_notice_failed auction=%s", auction.id)
        elif auction.status == AuctionStatus.ENDED:
            winner_name = ""
            if auction.current_winner_id:
                winning_bids = await self._bids.list_by_auction(auction.id)
                winning = next((b for b in winning_bids if b.is_winning_bid), None)
                winner_name = winning.bidder_name if winning else ""
            try:
                from app.service.auction.winner_payment_lifecycle import (
                    WinnerPaymentLifecycleAsync,
                )

                soft = auction.software
                title = soft.name if soft else str(auction.id)
                seller_id = soft.listed_by_user_id if soft else None
                life = WinnerPaymentLifecycleAsync(self._session)
                track = await life.start_winner_window(
                    auction_type="SOFTWARE",
                    auction_id=auction.id,
                    winner_user_id=auction.current_winner_id,
                    seller_user_id=seller_id,
                    winning_amount=float(auction.current_highest_bid or 0),
                    title=title,
                    pay_path=f"/technology/auction/{auction.id}",
                )
                await life.send_win_email(track)
            except Exception:
                logger.exception("software.winner_window_failed auction=%s", auction.id)
            await _broadcast_software_auction(
                auction.id,
                {
                    "type": "AUCTION_ENDED",
                    "status": auction.status.value,
                    "currentHighestBid": float(auction.current_highest_bid or 0),
                    "currentWinnerName": winner_name,
                    "winnerPaymentPaid": False,
                },
            )

    async def create_auction_for_new_listing(
        self,
        software_id: uuid.UUID,
        *,
        min_bid_price: float,
        duration: SoftwareAuctionDuration,
        auction_rationale: str,
        source_code_included: bool = False,
        support_included: bool = False,
        support_days: int = 0,
        transfer_details: Optional[str] = None,
        lister: AppUser,
        creation_fee_order_id: str,
    ) -> SoftwareAuction:
        """Called during software create when purchase_type is AUCTION."""
        return await self.create_auction(
            software_id,
            min_bid_price=min_bid_price,
            duration=duration,
            auction_rationale=auction_rationale,
            source_code_included=source_code_included,
            support_included=support_included,
            support_days=support_days,
            transfer_details=transfer_details,
            lister=lister,
            creation_fee_order_id=creation_fee_order_id,
        )

    async def take_down_auction(
        self,
        auction_id: uuid.UUID,
        admin: AppUser,
        reason: str,
        description: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        """Admin takedown of a live or approved software auction."""
        auction = await self._auctions.get_by_id(auction_id)
        if auction is None:
            raise AppException("Auction not found.", status_code=404)

        if auction.status not in (AuctionStatus.ACTIVE, AuctionStatus.DRAFT, AuctionStatus.EXTENDED):
            if auction.approval_status != SoftwareAuctionApprovalStatus.APPROVED:
                raise AppException("Only approved or active auctions can be taken down.", status_code=400)

        software = await self._software.get_by_id(auction.software_id)
        if software is None:
            raise AppException("Associated software not found.", status_code=404)

        now = datetime.now(timezone.utc)
        
        # Soft delete / take down auction
        auction.approval_status = SoftwareAuctionApprovalStatus.REJECTED
        auction.rejection_reason = reason
        auction.status = AuctionStatus.TAKEN_DOWN
        auction.taken_down_at = now
        auction.taken_down_by_id = admin.id
        auction.take_down_reason = reason
        auction.take_down_description = description

        # Take down the software listing
        software.status = False
        software.taken_down = True
        software.take_down_reason = reason

        await self._auctions.save(auction)
        await self._software.save(software)
        
        # Create audit log
        audit_repo = AdminAuditLogRepository(self._session)
        audit_log = AdminAuditLog(
            admin_id=admin.id,
            action="TAKE_DOWN_AUCTION",
            entity_id=str(auction.id),
            entity_type="SOFTWARE_AUCTION",
            target_user_id=software.listed_by_user_id,
            reason=reason,
            details=description,
            ip_address=ip_address,
        )
        await audit_repo.save(audit_log)
        
        await self._session.commit()
        
        # Notifications to seller and bidders should be queued/sent here.
        # This acts as a freeze and takedown placeholder.

    async def get_taken_down_auctions(self) -> list[dict]:
        """Fetch all taken down auctions for admin view."""
        auctions = await self._auctions.list_taken_down()
        out = []
        for a in auctions:
            bids = await self._bids.list_by_auction(a.id)
            out.append(build_admin_item(a, bids))
        return out

    async def approve_again_auction(
        self,
        auction_id: uuid.UUID,
        admin: AppUser,
        ip_address: Optional[str] = None,
    ) -> SoftwareAuction:
        """Admin approves a previously rejected or taken down software auction."""
        auction = await self._auctions.get_by_id(auction_id)
        if auction is None:
            raise AppException("Auction not found.", status_code=404)

        if auction.approval_status != SoftwareAuctionApprovalStatus.REJECTED:
            raise AppException("Auction must be rejected or taken down to approve again.", status_code=400)

        software = await self._software.get_by_id(auction.software_id)
        if software is None:
            raise AppException("Associated software not found.", status_code=404)

        now = datetime.now(timezone.utc)
        end = now + timedelta(days=auction.duration.to_days())
        
        # Reset auction
        auction.approval_status = SoftwareAuctionApprovalStatus.APPROVED
        auction.status = AuctionStatus.ACTIVE
        auction.start_time = now
        auction.end_time = end
        auction.original_end_time = end
        
        # Clear takedown/rejection records internally
        auction.rejection_reason = None
        auction.taken_down_at = None
        auction.taken_down_by_id = None
        auction.take_down_reason = None
        auction.take_down_description = None

        # Restore software
        software.software_status = SoftwareStatus.AVAILABLE
        software.status = True
        software.taken_down = False
        software.take_down_reason = None

        await self._auctions.save(auction)
        await self._software.save(software)

        # Create audit log
        audit_repo = AdminAuditLogRepository(self._session)
        audit_log = AdminAuditLog(
            admin_id=admin.id,
            action="APPROVE_AGAIN",
            entity_id=str(auction.id),
            entity_type="SOFTWARE_AUCTION",
            target_user_id=software.listed_by_user_id,
            reason="Approved Again",
            ip_address=ip_address,
        )
        await audit_repo.save(audit_log)
        
        await self._session.commit()
        return await self._auctions.get_by_id(auction_id) or auction

    async def _lock_auction(self, auction_id: uuid.UUID) -> SoftwareAuction:
        stmt = (
            select(SoftwareAuction)
            .where(SoftwareAuction.id == auction_id)
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        auction = result.scalar_one_or_none()
        if auction is None:
            raise AppException("Auction not found.", status_code=404)
        return auction

    @staticmethod
    def _require_winner(auction: SoftwareAuction, user: AppUser) -> None:
        if auction.current_winner_id != user.id:
            raise AppException(
                "Only the auction winner can pay the winning bid amount.",
                status_code=403,
            )

    @staticmethod
    def _winner_payment_amount(auction: SoftwareAuction) -> float:
        amount = float(auction.current_highest_bid or 0)
        if amount <= 0:
            raise AppException("Invalid winning bid amount.", status_code=400)
        return amount

    async def create_winner_payment_order(
        self,
        auction_id: uuid.UUID,
        winner: AppUser,
        *,
        redeem_points: bool = False,
    ) -> dict[str, Any]:
        if not rzp.is_configured():
            raise AppException(
                "Payment gateway is not configured.",
                status_code=503,
            )

        auction = await self._lock_auction(auction_id)
        self._require_winner(auction, winner)
        if auction.status != AuctionStatus.ENDED:
            raise AppException(
                "Auction is not awaiting winner payment.",
                status_code=409,
            )
        if auction.winner_payment_paid:
            raise AppException(
                "Winning bid has already been paid.",
                status_code=409,
            )

        amount = self._winner_payment_amount(auction)
        amount_to_charge = amount
        points_redeemed = 0
        if amount_to_charge > 0:
            from app.service.user.edge_points_service import EdgePointsService

            amount_to_charge, points_redeemed = await EdgePointsService.calculate_redemption(
                self._session,
                winner,
                amount_to_charge,
                redeem_points,
            )

        receipt = f"sw_win_{str(auction_id).replace('-', '')[:12]}"
        try:
            order = rzp.create_order(
                amount_inr=amount_to_charge,
                receipt=receipt,
                notes={
                    "auctionId": str(auction_id),
                    "softwareId": str(auction.software_id),
                    "type": "software_auction_winner_payment",
                },
            )
            if points_redeemed > 0:
                from app.service.user.edge_points_service import EdgePointsService

                await EdgePointsService.create_pending_redemption(
                    self._session,
                    winner.id,
                    order["id"],
                    points_redeemed,
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "software_auction.winner_payment.order_failed auction=%s",
                auction_id,
            )
            raise AppException(
                f"Payment order creation failed: {exc!s}",
                status_code=502,
            ) from exc

        auction.winner_payment_order_id = order["id"]
        await self._auctions.save(auction)
        await self._session.commit()

        return {
            "orderId": order["id"],
            "amount": amount,
            "amountToCharge": amount_to_charge,
            "currency": "INR",
            "keyId": rzp.get_key_id(),
            "auctionId": str(auction_id),
        }

    async def verify_winner_payment(
        self,
        auction_id: uuid.UUID,
        winner: AppUser,
        *,
        razorpay_payment_id: str,
        razorpay_order_id: str,
        razorpay_signature: str,
    ) -> dict[str, Any]:
        auction = await self._lock_auction(auction_id)
        self._require_winner(auction, winner)

        bids = list(await self._bids.list_by_auction(auction_id))
        if auction.winner_payment_paid and auction.status == AuctionStatus.COMPLETED:
            detail = build_detail_payload(auction, bids)
            return {
                "success": True,
                "message": "Winning bid payment already completed.",
                **detail,
            }

        if auction.status != AuctionStatus.ENDED:
            raise AppException(
                "Auction is not awaiting winner payment.",
                status_code=409,
            )
        if (
            auction.winner_payment_order_id
            and auction.winner_payment_order_id != razorpay_order_id
        ):
            raise AppException(
                "Order id does not match this auction payment.",
                status_code=400,
            )
        if not rzp.verify_payment_signature(
            razorpay_order_id,
            razorpay_payment_id,
            razorpay_signature,
        ):
            from app.service.user.edge_points_service import EdgePointsService

            await EdgePointsService.cancel_redemption(self._session, razorpay_order_id)
            raise AppException(
                "Payment verification failed — invalid signature",
                status_code=400,
            )

        from app.service.user.edge_points_service import EdgePointsService
        from app.service.cocreation.cocreation_payment_service import CocreationPaymentService

        await EdgePointsService.confirm_redemption(self._session, razorpay_order_id)

        payment_service = CocreationPaymentService(self._session)
        purchase = await payment_service.complete_auction_winner_purchase(
            auction=auction,
            buyer=winner,
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
        )

        auction.winner_payment_paid = True
        auction.winner_payment_id = razorpay_payment_id
        auction.status = AuctionStatus.COMPLETED
        await self._auctions.save(auction)
        await self._session.commit()

        await _broadcast_software_auction(
            auction.id,
            {
                "type": "PAYMENT_COMPLETED",
                "auctionId": str(auction.id),
                "status": auction.status.value,
                "currentHighestBid": float(auction.current_highest_bid or 0),
                "winnerPaymentPaid": True,
                "purchaseId": str(purchase.id),
            },
        )

        detail = build_detail_payload(auction, bids)
        return {
            "success": True,
            "message": "Winning bid payment verified. Auction is now complete.",
            "purchaseId": str(purchase.id),
            **detail,
        }

