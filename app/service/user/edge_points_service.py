import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, func, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.user.app_user import AppUser
from app.entity.user.edge_points_redemption import EdgePointsRedemption, RedemptionStatus
from app.entity.user.edge_points_history import EdgePointsHistory, EdgePointsTransactionType
from app.entity.user.referral_track import ReferralTrack
from app.entity.share.share_link import ShareLink, ShareType
from app.entity.notification.notification import Notification
from app.websocket.manager import notification_connection_manager
from app.service.notification.notification_service import NotificationService
from app.services.referral_rate_limiter import referral_rate_limiter

logger = logging.getLogger(__name__)

_SHARE_TYPE_LABELS = {
    ShareType.MARKETPLACE: "Marketplace",
    ShareType.DOMAIN_SEARCH: "Domain Search",
    ShareType.AI_BRAND_DOMAIN: "AI Brand Name",
}

# SQLSTATE codes / messages produced when the share-system schema columns are
# not present yet (migration `share001` not applied to this database).
_SCHEMA_MISSING_CODES = {"42703", "42P01", "42P10"}


class EdgePointsService:
    @staticmethod
    async def get_wallet_summary(session: AsyncSession, user: AppUser) -> dict[str, Any]:
        # Current points
        current_points = user.edge_points or 0
        worth_inr = float(current_points / 10.0)

        # Total earned (sum of positive history entries)
        earned_stmt = select(func.sum(EdgePointsHistory.points)).filter(
            EdgePointsHistory.user_id == user.id,
            EdgePointsHistory.points > 0
        )
        earned_res = await session.execute(earned_stmt)
        total_earned = earned_res.scalar() or 0

        # Total redeemed (sum of negative history entries)
        redeemed_stmt = select(func.sum(EdgePointsHistory.points)).filter(
            EdgePointsHistory.user_id == user.id,
            EdgePointsHistory.points < 0
        )
        redeemed_res = await session.execute(redeemed_stmt)
        total_redeemed = abs(redeemed_res.scalar() or 0)

        return {
            "current_points": current_points,
            "worth_inr": worth_inr,
            "total_earned": total_earned,
            "total_redeemed": total_redeemed
        }

    @staticmethod
    async def get_wallet_history(session: AsyncSession, user: AppUser) -> list[dict[str, Any]]:
        stmt = select(EdgePointsHistory).filter(
            EdgePointsHistory.user_id == user.id
        ).order_by(EdgePointsHistory.created_at.desc())
        res = await session.execute(stmt)
        history_list = res.scalars().all()
        return [
            {
                "id": str(h.id),
                "points": h.points,
                "transaction_type": h.transaction_type.value,
                "description": h.description,
                "created_at": h.created_at.isoformat() if h.created_at else None
            }
            for h in history_list
        ]

    @staticmethod
    async def get_referral_history(session: AsyncSession, user: AppUser) -> list[dict[str, Any]]:
        stmt = select(ReferralTrack).filter(
            ReferralTrack.referrer_id == user.id,
            ReferralTrack.points_awarded > 0
        ).order_by(ReferralTrack.created_at.desc())
        res = await session.execute(stmt)
        tracks = res.scalars().all()
        return [
            {
                "id": str(t.id),
                "listing_id": str(t.listing_id),
                "listing_type": t.listing_type,
                "visitor_ip": t.visitor_ip,
                "points_awarded": t.points_awarded,
                "created_at": t.created_at.isoformat() if t.created_at else None
            }
            for t in tracks
        ]

    # ── Referral tracking ─────────────────────────────────────────────────────

    @staticmethod
    def _schema_missing_error(exc: Exception) -> bool:
        """True when the error means the share-system schema is not migrated yet."""
        code = getattr(getattr(exc, "orig", None), "sqlstate", None) or ""
        msg = str(exc).lower()
        if code in _SCHEMA_MISSING_CODES:
            return True
        return (
            "does not exist" in msg
            or "undefined column" in msg
            or "undefined table" in msg
            or "matching the on conflict specification" in msg
        )

    @staticmethod
    async def _atomic_track_insert(
        session: AsyncSession,
        *,
        referrer_id: uuid.UUID,
        item_key: str,
        share_link_id: uuid.UUID | None,
        listing_id: uuid.UUID,
        listing_type: str,
        visitor_ip: str,
        visitor_id: uuid.UUID | None,
        visitor_key: str,
        points: int,
    ) -> uuid.UUID | None:
        """Atomic one-reward-per-(referrer, item, receiver) insert.

        Relies on the partial UNIQUE indexes created by migration ``share001``.
        Returns the inserted row id, or None when the insert conflicted
        (duplicate view — no reward). The database serializes concurrent
        identical requests: exactly one wins.
        """
        stmt = pg_insert(ReferralTrack).values(
            referrer_id=referrer_id,
            listing_id=listing_id,
            listing_type=listing_type,
            visitor_ip=visitor_ip,
            visitor_id=visitor_id,
            points_awarded=points,
            share_link_id=share_link_id,
            item_key=item_key,
            visitor_key=visitor_key,
        )
        if visitor_id is not None:
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["referrer_id", "item_key", "visitor_id"],
                index_where=text("visitor_id IS NOT NULL"),
            )
        else:
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["referrer_id", "item_key", "visitor_key"],
                index_where=text("visitor_id IS NULL"),
            )
        stmt = stmt.returning(ReferralTrack.id)
        res = await session.execute(stmt)
        row = res.first()
        return row[0] if row else None

    @staticmethod
    async def _legacy_raw_track_insert(
        session: AsyncSession,
        *,
        referrer_id: uuid.UUID,
        listing_id: uuid.UUID,
        listing_type: str,
        visitor_ip: str,
        visitor_id: uuid.UUID | None,
        points: int,
    ) -> None:
        """Raw INSERT using only the legacy columns.

        Used only pre-migration (when the new columns do not exist yet) so the
        existing marketplace `?ref=` flow keeps working exactly as before.
        """
        now = datetime.now(timezone.utc)
        stmt = text(
            "INSERT INTO referral_tracks "
            "(referrer_id, listing_id, listing_type, visitor_ip, visitor_id, points_awarded, id, created_at, updated_at) "
            "VALUES (:referrer_id, :listing_id, :listing_type, :visitor_ip, :visitor_id, :points, :id, :created_at, :updated_at)"
        )
        await session.execute(
            stmt,
            {
                "referrer_id": referrer_id,
                "listing_id": listing_id,
                "listing_type": listing_type,
                "visitor_ip": visitor_ip,
                "visitor_id": visitor_id,
                "points": points,
                "id": uuid.uuid4(),
                "created_at": now,
                "updated_at": now,
            },
        )

    @staticmethod
    async def _award_referrer_points(
        session: AsyncSession,
        *,
        referrer: AppUser,
        points: int,
        description: str,
    ) -> None:
        referrer.edge_points = (referrer.edge_points or 0) + points
        session.add(referrer)

        history = EdgePointsHistory(
            user_id=referrer.id,
            points=points,
            transaction_type=EdgePointsTransactionType.REFERRAL_EARN,
            description=description,
        )
        session.add(history)

        title = "🎉 Congratulations!"
        message = "You have successfully earned 20 Edge Points!\n\nYour wallet has been updated."
        notification = Notification(
            app_user_id=referrer.id,
            notification_type="REFERRAL_REWARD",
            title=title,
            message=message,
        )
        session.add(notification)
        await session.flush()  # get notification id

        # Live WebSocket notification (fire-and-forget; never breaks the reward)
        try:
            frontend_payload = NotificationService._to_frontend(notification)
            await notification_connection_manager.send_personal_notification(
                referrer.id,
                {
                    "event": "notification_created",
                    "data": frontend_payload,
                },
            )
        except Exception as e:
            logger.warning("Could not dispatch live notification: %s", e)

    @staticmethod
    def _track_response(referrer: AppUser, points: int, message: str | None = None) -> dict[str, Any]:
        if message is None:
            message = (
                "Referral tracked successfully"
                if points > 0
                else "Referral tracked (no points awarded - duplicate or self-click)"
            )
        return {
            "success": True,
            "points_awarded": points,
            "pointsAwarded": points,
            "updated_balance": referrer.edge_points,
            "updatedBalance": referrer.edge_points,
            "message": message,
        }

    @staticmethod
    async def _track_legacy_fallback(
        session: AsyncSession,
        *,
        referrer: AppUser,
        listing_id: uuid.UUID,
        listing_type: str,
        visitor_ip: str,
        visitor_user: Optional[AppUser],
    ) -> dict[str, Any]:
        """Pre-migration fallback replicating today's SELECT-then-INSERT behavior."""
        dup_query = select(ReferralTrack).filter(
            ReferralTrack.referrer_id == referrer.id,
            ReferralTrack.listing_id == listing_id,
            ReferralTrack.points_awarded > 0,
        )
        if visitor_user:
            dup_query = dup_query.filter(
                (ReferralTrack.visitor_ip == visitor_ip) | (ReferralTrack.visitor_id == visitor_user.id)
            )
        else:
            dup_query = dup_query.filter(ReferralTrack.visitor_ip == visitor_ip)

        dup_res = await session.execute(dup_query)
        has_dup = dup_res.scalar_one_or_none() is not None
        points_to_award = 0 if has_dup else 20

        await EdgePointsService._legacy_raw_track_insert(
            session,
            referrer_id=referrer.id,
            listing_id=listing_id,
            listing_type=listing_type,
            visitor_ip=visitor_ip,
            visitor_id=visitor_user.id if visitor_user else None,
            points=points_to_award,
        )

        if points_to_award > 0:
            await EdgePointsService._award_referrer_points(
                session,
                referrer=referrer,
                points=points_to_award,
                description=f"Earned {points_to_award} points from referring {listing_type.capitalize()} listing",
            )

        await session.commit()
        return EdgePointsService._track_response(referrer, points_to_award)

    @staticmethod
    async def track_referral(
        session: AsyncSession,
        referrer_id: uuid.UUID,
        listing_id: uuid.UUID,
        listing_type: str,
        visitor_ip: str,
        visitor_user: Optional[AppUser] = None
    ) -> dict[str, Any]:
        """Legacy referral entry (marketplace `?ref=` links).

        After migration `share001` this uses the atomic ON CONFLICT path (dedupe
        keyed on ``item_key``); before the migration it falls back to the exact
        historical SELECT-then-INSERT behavior using only existing columns.
        """
        referrer_res = await session.execute(select(AppUser).filter(AppUser.id == referrer_id))
        referrer = referrer_res.scalar_one_or_none()
        if not referrer:
            return {"success": False, "message": "Referrer not found"}

        if visitor_user and visitor_user.id == referrer_id:
            return {"success": False, "message": "Self-referrals are not rewarded"}

        item_key = f"{listing_type}:{listing_id}"
        visitor_key = str(visitor_user.id) if visitor_user else visitor_ip

        try:
            inserted_id = await EdgePointsService._atomic_track_insert(
                session,
                referrer_id=referrer_id,
                item_key=item_key,
                share_link_id=None,
                listing_id=listing_id,
                listing_type=listing_type,
                visitor_ip=visitor_ip,
                visitor_id=visitor_user.id if visitor_user else None,
                visitor_key=visitor_key,
                points=20,
            )
        except Exception as exc:
            if not EdgePointsService._schema_missing_error(exc):
                logger.exception("Referral atomic track failed unexpectedly")
                raise
            logger.warning(
                "Share-system schema not migrated yet (falling back to legacy referral path): %s",
                exc,
            )
            return await EdgePointsService._track_legacy_fallback(
                session,
                referrer=referrer,
                listing_id=listing_id,
                listing_type=listing_type,
                visitor_ip=visitor_ip,
                visitor_user=visitor_user,
            )

        if inserted_id is None:
            await session.commit()
            return EdgePointsService._track_response(referrer, 0)

        if not await referral_rate_limiter.check_reward(referrer_id):
            await session.execute(
                update(ReferralTrack)
                .where(ReferralTrack.id == inserted_id)
                .values(points_awarded=0)
            )
            await session.commit()
            return EdgePointsService._track_response(
                referrer, 0, message="Referral tracked (daily reward limit reached)"
            )

        await EdgePointsService._award_referrer_points(
            session,
            referrer=referrer,
            points=20,
            description=f"Earned 20 points from referring {listing_type.capitalize()} listing",
        )
        await session.commit()
        return EdgePointsService._track_response(referrer, 20)

    @staticmethod
    async def track_share_referral(
        session: AsyncSession,
        *,
        share: ShareLink,
        visitor_ip: str,
        visitor_user: Optional[AppUser] = None,
        visitor_key_from_cookie: Optional[str] = None,
    ) -> dict[str, Any]:
        """Referral entry for a tokenized share link (DOMAIN_SEARCH / AI_BRAND_DOMAIN).

        The referrer and the shared item are resolved server-side from the share
        record — the client never supplies a referrer UUID. The reward is
        atomic: one per (referrer, item, receiver), enforced by the database.
        """
        referrer_res = await session.execute(select(AppUser).filter(AppUser.id == share.referrer_id))
        referrer = referrer_res.scalar_one_or_none()
        if not referrer:
            # A logged-out sender created this share — no authenticated referrer
            # exists, so no Edge Points reward can ever be granted (by design).
            return {
                "success": False,
                "message": "Anonymous share has no referrer - no reward",
            }

        # Self-referral: logged-in visitor is the share owner.
        if visitor_user and visitor_user.id == share.referrer_id:
            return {"success": False, "message": "Self-referrals are not rewarded"}

        # Self-referral: anonymous visitor carries the sender's own visitor cookie.
        if (
            not visitor_user
            and share.referrer_visitor_key
            and visitor_key_from_cookie
            and share.referrer_visitor_key == visitor_key_from_cookie
        ):
            return {"success": False, "message": "Self-referrals are not rewarded"}

        domain = (share.domain or "").lower()
        if not domain:
            return {"success": False, "message": "Shared item is missing"}

        visitor_key = (
            str(visitor_user.id)
            if visitor_user
            else (visitor_key_from_cookie or visitor_ip)
        )
        # One reward per receiver per sender per DOMAIN — same item_key for
        # DOMAIN_SEARCH and AI_BRAND_DOMAIN shares of the same domain.
        item_key = f"domain:{domain}"
        listing_type = "domain"
        # listing_id is NOT NULL for legacy parity with no FK; for domain shares
        # use a STABLE uuid5 derived from the domain (same value for every share
        # of the same domain — never a random fabrication). Dedupe uses item_key.
        listing_id = uuid.uuid5(uuid.NAMESPACE_URL, f"cobrother-share:{item_key}")

        try:
            inserted_id = await EdgePointsService._atomic_track_insert(
                session,
                referrer_id=referrer.id,
                item_key=item_key,
                share_link_id=share.id,
                listing_id=listing_id,
                listing_type=listing_type,
                visitor_ip=visitor_ip,
                visitor_id=visitor_user.id if visitor_user else None,
                visitor_key=visitor_key,
                points=20,
            )
        except Exception as exc:
            if not EdgePointsService._schema_missing_error(exc):
                logger.exception("Share referral atomic track failed unexpectedly")
                raise
            logger.warning(
                "Share-system schema not migrated yet; share tracking unavailable: %s",
                exc,
            )
            await session.rollback()
            return {
                "success": False,
                "message": "Share tracking is not available yet. The database migration has not been applied.",
            }

        if inserted_id is None:
            await session.commit()
            return EdgePointsService._track_response(referrer, 0)

        if not await referral_rate_limiter.check_reward(referrer.id):
            await session.execute(
                update(ReferralTrack)
                .where(ReferralTrack.id == inserted_id)
                .values(points_awarded=0)
            )
            await session.commit()
            return EdgePointsService._track_response(
                referrer, 0, message="Referral tracked (daily reward limit reached)"
            )

        label = _SHARE_TYPE_LABELS.get(share.share_type, "Share")
        await EdgePointsService._award_referrer_points(
            session,
            referrer=referrer,
            points=20,
            description=f"Earned 20 points from {label} share",
        )
        await session.commit()
        return EdgePointsService._track_response(referrer, 20)

    @staticmethod
    async def calculate_redemption(
        session: AsyncSession,
        user: AppUser,
        order_amount_inr: float,
        redeem_requested: bool
    ) -> tuple[float, int]:
        if not redeem_requested or order_amount_inr <= 0:
            return order_amount_inr, 0

        # Calculate pending points to prevent double spending
        pending_stmt = select(func.sum(EdgePointsRedemption.edge_points_redeemed)).filter(
            EdgePointsRedemption.user_id == user.id,
            EdgePointsRedemption.status == RedemptionStatus.PENDING
        )
        pending_res = await session.execute(pending_stmt)
        pending_points = pending_res.scalar() or 0

        available_points = max(0, (user.edge_points or 0) - pending_points)
        if available_points <= 0:
            return order_amount_inr, 0

        # Redemption: 10 Edge Points = ₹1. Max redeem per order = ₹500 (5000 points)
        max_points_redeemable = min(5000, available_points, int(round(order_amount_inr * 10)))
        rupees_discount = float(max_points_redeemable / 10.0)

        final_amount = max(0.0, order_amount_inr - rupees_discount)
        return final_amount, max_points_redeemable

    @staticmethod
    async def create_pending_redemption(
        session: AsyncSession,
        user_id: uuid.UUID,
        razorpay_order_id: str,
        points: int
    ) -> Optional[EdgePointsRedemption]:
        if points <= 0:
            return None

        redemption = EdgePointsRedemption(
            user_id=user_id,
            razorpay_order_id=razorpay_order_id,
            edge_points_redeemed=points,
            status=RedemptionStatus.PENDING
        )
        session.add(redemption)
        await session.commit()
        return redemption

    @staticmethod
    async def confirm_redemption(session: AsyncSession, razorpay_order_id: str) -> None:
        stmt = select(EdgePointsRedemption).filter(
            EdgePointsRedemption.razorpay_order_id == razorpay_order_id,
            EdgePointsRedemption.status == RedemptionStatus.PENDING
        )
        res = await session.execute(stmt)
        redemption = res.scalar_one_or_none()
        if not redemption:
            return

        redemption.status = RedemptionStatus.COMPLETED
        session.add(redemption)

        # Deduct points from user
        user_res = await session.execute(select(AppUser).filter(AppUser.id == redemption.user_id))
        user = user_res.scalar_one()
        user.edge_points = max(0, (user.edge_points or 0) - redemption.edge_points_redeemed)
        session.add(user)

        # Log history
        history = EdgePointsHistory(
            user_id=redemption.user_id,
            points=-redemption.edge_points_redeemed,
            transaction_type=EdgePointsTransactionType.CHECKOUT_REDEEM,
            description=f"Redeemed {redemption.edge_points_redeemed} points on purchase"
        )
        session.add(history)
        await session.commit()

    @staticmethod
    async def cancel_redemption(session: AsyncSession, razorpay_order_id: str) -> None:
        stmt = select(EdgePointsRedemption).filter(
            EdgePointsRedemption.razorpay_order_id == razorpay_order_id,
            EdgePointsRedemption.status == RedemptionStatus.PENDING
        )
        res = await session.execute(stmt)
        redemption = res.scalar_one_or_none()
        if not redemption:
            return

        redemption.status = RedemptionStatus.FAILED
        session.add(redemption)
        await session.commit()
