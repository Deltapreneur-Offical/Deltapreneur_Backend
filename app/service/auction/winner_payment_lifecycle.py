"""
Winner payment window (7 days), daily reminder dedupe, blacklist, Option A forfeit.

Uses existing ``platform_settings`` rows only — no new tables / no schema migration.
Safe for shared RDS (row upserts only; no DROP/TRUNCATE).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.entity.auction.auction_fee_payment_entity import (
    AuctionFeeAuctionType,
    AuctionFeePayment,
    AuctionFeePaymentKind,
    AuctionFeePaymentStatus,
)
from app.entity.platform.platform_setting_entity import PlatformSetting
from app.entity.user.app_user import AppUser
from app.integrations.razorpay import client as rzp

logger = logging.getLogger(__name__)

PAYMENT_WINDOW_DAYS = 7
TRACK_PREFIX = "wpt:"
BLOCK_PREFIX = "bidblock:"
BLOCK_INDEX_KEY = "bidblock_index"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _track_key(auction_type: str, auction_id: uuid.UUID) -> str:
    return f"{TRACK_PREFIX}{auction_type.upper()}:{auction_id}"


def _block_key(user_id: uuid.UUID) -> str:
    return f"{BLOCK_PREFIX}{user_id}"


def days_left_until(due_at_iso: str | None) -> int | None:
    """Calendar days from today (UTC) until due date. 0 = due today; negative = overdue."""
    if not due_at_iso:
        return None
    try:
        due = datetime.fromisoformat(due_at_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    due_date = due.astimezone(timezone.utc).date()
    today = _utc_now().date()
    return (due_date - today).days


def payment_due_label(due_at_iso: str | None) -> str | None:
    left = days_left_until(due_at_iso)
    if left is None:
        return None
    if left < 0:
        return "Payment overdue"
    if left == 0:
        return "Payment due today"
    if left == 1:
        return "Payment due in 1 day"
    return f"Payment due in {left} days"


class WinnerPaymentLifecycleAsync:
    """AsyncSession helpers (domain / software auctions)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get(self, key: str) -> str | None:
        result = await self._session.execute(
            select(PlatformSetting).where(PlatformSetting.setting_key == key)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return getattr(row, "setting_value", None)

    async def _set(self, key: str, value: str) -> None:
        result = await self._session.execute(
            select(PlatformSetting).where(PlatformSetting.setting_key == key)
        )
        row = result.scalar_one_or_none()
        now = _utc_now()
        if row is None:
            self._session.add(
                PlatformSetting(setting_key=key, setting_value=value, updated_at=now)
            )
        else:
            row.setting_value = value
            row.updated_at = now
        await self._session.flush()

    async def get_track(self, auction_type: str, auction_id: uuid.UUID) -> dict[str, Any] | None:
        raw = await self._get(_track_key(auction_type, auction_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def list_open_tracks(self) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(PlatformSetting).where(
                PlatformSetting.setting_key.like(f"{TRACK_PREFIX}%")
            )
        )
        rows = result.scalars().all()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                data = json.loads(row.setting_value or "{}")
            except json.JSONDecodeError:
                continue
            if data.get("forfeitedAt") or data.get("zeroBid"):
                continue
            if data.get("dueAt"):
                out.append(data)
        return out

    async def process_reminders_and_forfeits(self) -> dict[str, int]:
        """Daily reminders + Option A forfeit when dueAt passed. Read/upsert settings only."""
        stats = {"reminders": 0, "forfeits": 0}
        tracks = await self.list_open_tracks()
        for track in tracks:
            left = days_left_until(track.get("dueAt"))
            if left is None:
                continue
            if left >= 0:
                if await self.try_send_daily_reminder(track):
                    stats["reminders"] += 1
                continue
            # Past due date → forfeit (Option A)
            if await self._forfeit_unpaid_winner(track):
                stats["forfeits"] += 1
        await self._session.commit()
        return stats

    async def _forfeit_unpaid_winner(self, track: dict[str, Any]) -> bool:
        if track.get("forfeitedAt"):
            return False
        auction_type = str(track.get("auctionType") or "DOMAIN").upper()
        auction_id = uuid.UUID(str(track["auctionId"]))
        winner_id = uuid.UUID(str(track["winnerUserId"])) if track.get("winnerUserId") else None
        seller_id = uuid.UUID(str(track["sellerUserId"])) if track.get("sellerUserId") else None
        title = track.get("title") or "auction"
        amount = float(track.get("winningAmount") or 0)

        if winner_id:
            await self.block_user(
                user_id=winner_id,
                reason=(
                    f"Unpaid winning bid on “{title}” (₹{amount:,.2f}). "
                    "Contact support / admin to unblacklist."
                ),
                auction_type=auction_type,
                auction_id=auction_id,
                winning_amount=amount,
                title=title,
            )
            # Notify winner
            result = await self._session.execute(
                select(AppUser).where(AppUser.id == winner_id)
            )
            winner = result.scalar_one_or_none()
            if winner:
                try:
                    from app.service.auction.auction_notification_service import _notify_sync

                    _notify_sync(
                        winner,
                        title="Account blocked — unpaid auction win",
                        message=(
                            f"You did not pay for “{title}” within 7 days. "
                            "Your account is blocked from bidding until an admin unblocks you."
                        ),
                        target_url=track.get("payPath") or "/auctions",
                    )
                except Exception:
                    logger.exception("forfeit.winner_notify_failed")

        # Mark auction UNSOLD (domain / software). Creator handled best-effort.
        try:
            if auction_type == "DOMAIN":
                from app.entity.auction.auction_entity import Auction
                from app.utils.enums import AuctionStatus

                result = await self._session.execute(
                    select(Auction).where(Auction.id == auction_id)
                )
                auction = result.scalar_one_or_none()
                if auction is not None and auction.status.value in {
                    "PAYMENT_PENDING",
                    "ENDED",
                }:
                    auction.status = AuctionStatus.UNSOLD
                    auction.current_winner_id = None
            elif auction_type == "TECHNOLOGY" or auction_type == "SOFTWARE":
                from app.entity.cocreation.software_auction import SoftwareAuction
                from app.utils.enums import AuctionStatus

                result = await self._session.execute(
                    select(SoftwareAuction).where(SoftwareAuction.id == auction_id)
                )
                auction = result.scalar_one_or_none()
                if auction is not None and str(getattr(auction.status, "value", auction.status)) in {
                    "ENDED",
                    "PAYMENT_PENDING",
                }:
                    auction.status = AuctionStatus.UNSOLD
                    auction.current_winner_id = None
        except Exception:
            logger.exception("forfeit.mark_unsold_failed auction=%s", auction_id)

        refunded = False
        if seller_id:
            try:
                at = AuctionFeeAuctionType.DOMAIN
                if auction_type in {"TECHNOLOGY", "SOFTWARE"}:
                    at = AuctionFeeAuctionType.SOFTWARE
                elif auction_type == "CREATOR":
                    at = AuctionFeeAuctionType.COMMUNITY
                refunded = await self.refund_creation_fee_if_any(
                    auction_type=at,
                    auction_id=auction_id,
                    seller_user_id=seller_id,
                )
            except Exception:
                logger.exception("forfeit.refund_failed auction=%s", auction_id)

            result = await self._session.execute(
                select(AppUser).where(AppUser.id == seller_id)
            )
            seller = result.scalar_one_or_none()
            if seller:
                try:
                    from app.service.auction.auction_notification_service import _notify_sync

                    msg = (
                        f"We're sorry — the winner of “{title}” did not complete payment. "
                        "The auction is marked Unsold. "
                    )
                    msg += (
                        "Your auction creation fee has been refunded to your original payment method "
                        "(bank reflection may take a few days)."
                        if refunded
                        else "If a creation fee was charged, our team will process the refund."
                    )
                    msg += " You can re-list this auction when ready."
                    _notify_sync(
                        seller,
                        title="Auction cancelled — winner did not pay",
                        message=msg,
                        target_url="/auctions?view=yours",
                    )
                except Exception:
                    logger.exception("forfeit.seller_notify_failed")

        track["forfeitedAt"] = _utc_now().isoformat()
        await self._set(_track_key(auction_type, auction_id), json.dumps(track))
        return True

    async def start_winner_window(
        self,
        *,
        auction_type: str,
        auction_id: uuid.UUID,
        winner_user_id: uuid.UUID,
        seller_user_id: uuid.UUID | None,
        winning_amount: float,
        title: str,
        pay_path: str,
    ) -> dict[str, Any]:
        due = _utc_now() + timedelta(days=PAYMENT_WINDOW_DAYS)
        track = {
            "auctionType": auction_type.upper(),
            "auctionId": str(auction_id),
            "winnerUserId": str(winner_user_id),
            "sellerUserId": str(seller_user_id) if seller_user_id else None,
            "winningAmount": float(winning_amount),
            "title": title,
            "payPath": pay_path,
            "dueAt": due.isoformat(),
            "winEmailSentAt": None,
            "reminderSentOn": None,
            "forfeitedAt": None,
            "creationFeeRefundedAt": None,
            "zeroBidNoticeSentAt": None,
        }
        await self._set(_track_key(auction_type, auction_id), json.dumps(track))
        return track

    async def mark_win_email_sent(self, auction_type: str, auction_id: uuid.UUID) -> None:
        track = await self.get_track(auction_type, auction_id) or {}
        track["winEmailSentAt"] = _utc_now().isoformat()
        await self._set(_track_key(auction_type, auction_id), json.dumps(track))

    async def is_user_bidding_blocked(self, user_id: uuid.UUID) -> tuple[bool, str | None]:
        raw = await self._get(_block_key(user_id))
        if not raw:
            return False, None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return True, "Bidding blocked."
        if data.get("unblockedAt"):
            return False, None
        return True, data.get("reason") or "Bidding blocked for unpaid auction win."

    async def block_user(
        self,
        *,
        user_id: uuid.UUID,
        reason: str,
        auction_type: str,
        auction_id: uuid.UUID,
        winning_amount: float,
        title: str,
    ) -> None:
        payload = {
            "userId": str(user_id),
            "reason": reason,
            "blockedAt": _utc_now().isoformat(),
            "auctionType": auction_type.upper(),
            "auctionId": str(auction_id),
            "winningAmount": float(winning_amount),
            "title": title,
            "unblockedAt": None,
            "unblockedBy": None,
        }
        await self._set(_block_key(user_id), json.dumps(payload))
        idx_raw = await self._get(BLOCK_INDEX_KEY)
        try:
            idx = json.loads(idx_raw) if idx_raw else []
        except json.JSONDecodeError:
            idx = []
        uid = str(user_id)
        if uid not in idx:
            idx.append(uid)
            await self._set(BLOCK_INDEX_KEY, json.dumps(idx))

    async def unblock_user(self, user_id: uuid.UUID, *, by_admin_id: uuid.UUID | None) -> bool:
        raw = await self._get(_block_key(user_id))
        if not raw:
            return False
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
        data["unblockedAt"] = _utc_now().isoformat()
        data["unblockedBy"] = str(by_admin_id) if by_admin_id else None
        await self._set(_block_key(user_id), json.dumps(data))
        return True

    async def list_blocked_users(self) -> list[dict[str, Any]]:
        idx_raw = await self._get(BLOCK_INDEX_KEY)
        try:
            idx = json.loads(idx_raw) if idx_raw else []
        except json.JSONDecodeError:
            idx = []
        out: list[dict[str, Any]] = []
        for uid in idx:
            raw = await self._get(f"{BLOCK_PREFIX}{uid}")
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if data.get("unblockedAt"):
                continue
            # Enrich with user email/name when possible
            try:
                user_uuid = uuid.UUID(uid)
                result = await self._session.execute(
                    select(AppUser).where(AppUser.id == user_uuid)
                )
                user = result.scalar_one_or_none()
                if user:
                    data["email"] = user.email
                    data["firstname"] = user.firstname
                    data["lastname"] = user.lastname
                    data["displayName"] = (
                        f"{(user.firstname or '').strip()} {(user.lastname or '').strip()}".strip()
                        or user.email
                    )
            except Exception:
                logger.debug("bidblock.enrich_failed user=%s", uid, exc_info=True)
            due_label = None
            if data.get("auctionId") and data.get("auctionType"):
                try:
                    tr = await self.get_track(
                        str(data["auctionType"]),
                        uuid.UUID(str(data["auctionId"])),
                    )
                    due_label = payment_due_label((tr or {}).get("dueAt"))
                except Exception:
                    due_label = None
            data["paymentDueLabel"] = due_label
            out.append(data)
        out.sort(key=lambda r: r.get("blockedAt") or "", reverse=True)
        return out

    async def mark_zero_bid_notice_sent(
        self, auction_type: str, auction_id: uuid.UUID, seller_user_id: uuid.UUID, title: str
    ) -> bool:
        """Return True if this is the first zero-bid notice (dedupe)."""
        key = _track_key(auction_type, auction_id)
        track = await self.get_track(auction_type, auction_id) or {
            "auctionType": auction_type.upper(),
            "auctionId": str(auction_id),
            "sellerUserId": str(seller_user_id),
            "title": title,
            "winningAmount": 0,
            "zeroBid": True,
        }
        if track.get("zeroBidNoticeSentAt"):
            return False
        track["zeroBidNoticeSentAt"] = _utc_now().isoformat()
        track["sellerUserId"] = str(seller_user_id)
        track["title"] = title
        await self._set(key, json.dumps(track))
        return True

    async def try_send_daily_reminder(self, track: dict[str, Any]) -> bool:
        """Send at most one reminder email per calendar day. Returns True if sent."""
        if track.get("forfeitedAt") or not track.get("dueAt"):
            return False
        today = date.today().isoformat()
        if track.get("reminderSentOn") == today:
            return False
        # Do not send a daily reminder on the same calendar day as the win email.
        win_sent = track.get("winEmailSentAt")
        if win_sent:
            try:
                win_dt = datetime.fromisoformat(str(win_sent).replace("Z", "+00:00"))
                if win_dt.tzinfo is None:
                    win_dt = win_dt.replace(tzinfo=timezone.utc)
                if win_dt.astimezone(timezone.utc).date().isoformat() == today:
                    return False
            except ValueError:
                pass
        left = days_left_until(track["dueAt"])
        if left is None or left < 0:
            return False
        # left == 0 → last day (strict reminder)
        winner_id = track.get("winnerUserId")
        if not winner_id:
            return False
        result = await self._session.execute(
            select(AppUser).where(AppUser.id == uuid.UUID(winner_id))
        )
        winner = result.scalar_one_or_none()
        if winner is None or not winner.email:
            return False

        title = track.get("title") or "your auction"
        amount = float(track.get("winningAmount") or 0)
        pay_path = track.get("payPath") or "/"
        from app.core.config import settings

        base = (getattr(settings, "FRONTEND_BASE_URL", None) or "https://www.deltapreneur.com").rstrip("/")
        pay_url = f"{base}{pay_path}"
        if left == 0:
            subject = f"Final reminder: pay today for “{title}” or your account will be blocked"
            body = (
                f"<p>Hi,</p>"
                f"<p>This is your <strong>final reminder</strong>. You won <strong>{title}</strong> "
                f"with a bid of <strong>₹{amount:,.2f}</strong>.</p>"
                f"<p>If you do not complete payment <strong>today</strong>, your account will be "
                f"<strong>blocked from bidding</strong> on Deltapreneur until an admin unblocks you.</p>"
                f"<p><a href=\"{pay_url}\">Complete payment now</a></p>"
            )
        else:
            subject = f"Payment reminder: {left} days left for “{title}”"
            body = (
                f"<p>Hi,</p>"
                f"<p>You won <strong>{title}</strong> with a bid of <strong>₹{amount:,.2f}</strong>.</p>"
                f"<p><strong>{left} days left</strong> to complete payment.</p>"
                f"<p><a href=\"{pay_url}\">Pay now</a></p>"
            )
        try:
            from app.service.auth.mail_service import MailService
            from fastapi_mail import FastMail

            message = MailService._html_message(
                subject=subject,
                recipients=[winner.email],
                body=body,
            )
            await FastMail(MailService._conf()).send_message(message)
        except Exception:
            logger.exception("winner_payment.reminder_email_failed auction=%s", track.get("auctionId"))
            return False

        track["reminderSentOn"] = today
        await self._set(
            _track_key(track["auctionType"], uuid.UUID(track["auctionId"])),
            json.dumps(track),
        )
        return True

    async def send_win_email(self, track: dict[str, Any]) -> None:
        if track.get("winEmailSentAt"):
            return
        winner_id = track.get("winnerUserId")
        if not winner_id:
            return
        result = await self._session.execute(
            select(AppUser).where(AppUser.id == uuid.UUID(winner_id))
        )
        winner = result.scalar_one_or_none()
        if winner is None or not winner.email:
            return
        title = track.get("title") or "your auction"
        amount = float(track.get("winningAmount") or 0)
        pay_path = track.get("payPath") or "/"
        from app.core.config import settings

        base = (getattr(settings, "FRONTEND_BASE_URL", None) or "https://www.deltapreneur.com").rstrip("/")
        pay_url = f"{base}{pay_path}"
        due_label = payment_due_label(track.get("dueAt")) or f"{PAYMENT_WINDOW_DAYS} days"
        body = (
            f"<p>Hi,</p>"
            f"<p>Congratulations — you won <strong>{title}</strong> with a bid of "
            f"<strong>₹{amount:,.2f}</strong>.</p>"
            f"<p>Please complete payment within <strong>7 days</strong> ({due_label}). "
            f"According to our bidding rules, unpaid wins may result in your account being "
            f"blocked from future bidding.</p>"
            f"<p><a href=\"{pay_url}\">Proceed to payment</a></p>"
        )
        try:
            from app.service.auth.mail_service import MailService
            from fastapi_mail import FastMail

            message = MailService._html_message(
                subject=f"You won “{title}” — complete payment",
                recipients=[winner.email],
                body=body,
            )
            await FastMail(MailService._conf()).send_message(message)
            await self.mark_win_email_sent(track["auctionType"], uuid.UUID(track["auctionId"]))
        except Exception:
            logger.exception("winner_payment.win_email_failed auction=%s", track.get("auctionId"))

    async def refund_creation_fee_if_any(
        self,
        *,
        auction_type: AuctionFeeAuctionType,
        auction_id: uuid.UUID,
        seller_user_id: uuid.UUID,
    ) -> bool:
        """Refund seller creation fee (Option A). Idempotent via track flag."""
        track = await self.get_track(auction_type.value, auction_id) or {}
        if track.get("creationFeeRefundedAt"):
            return False
        stmt = (
            select(AuctionFeePayment)
            .where(
                AuctionFeePayment.payment_kind == AuctionFeePaymentKind.CREATION,
                AuctionFeePayment.auction_type == auction_type,
                AuctionFeePayment.user_id == seller_user_id,
                AuctionFeePayment.auction_id == auction_id,
                AuctionFeePayment.status.in_(
                    [
                        AuctionFeePaymentStatus.COMPLETED,
                        AuctionFeePaymentStatus.CONSUMED,
                    ]
                ),
            )
            .order_by(AuctionFeePayment.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            # Also try match by user + type without auction_id (consumed before link)
            stmt2 = (
                select(AuctionFeePayment)
                .where(
                    AuctionFeePayment.payment_kind == AuctionFeePaymentKind.CREATION,
                    AuctionFeePayment.auction_type == auction_type,
                    AuctionFeePayment.user_id == seller_user_id,
                    AuctionFeePayment.status.in_(
                        [
                            AuctionFeePaymentStatus.COMPLETED,
                            AuctionFeePaymentStatus.CONSUMED,
                        ]
                    ),
                )
                .order_by(AuctionFeePayment.created_at.desc())
                .limit(1)
            )
            result2 = await self._session.execute(stmt2)
            row = result2.scalar_one_or_none()

        if row is None or not row.razorpay_payment_id:
            track["creationFeeRefundedAt"] = "skipped_no_payment"
            await self._set(_track_key(auction_type.value, auction_id), json.dumps(track))
            return False
        if str(row.razorpay_order_id or "").startswith("admin_free"):
            track["creationFeeRefundedAt"] = "skipped_admin_free"
            await self._set(_track_key(auction_type.value, auction_id), json.dumps(track))
            return False
        try:
            if rzp.is_configured():
                rzp.refund_payment(row.razorpay_payment_id, float(row.fee_amount_inr or 0))
            track["creationFeeRefundedAt"] = _utc_now().isoformat()
            track["creationFeeRefundPaymentId"] = row.razorpay_payment_id
            await self._set(_track_key(auction_type.value, auction_id), json.dumps(track))
            return True
        except Exception:
            logger.exception(
                "winner_payment.creation_fee_refund_failed auction=%s payment=%s",
                auction_id,
                row.razorpay_payment_id,
            )
            return False


def assert_user_can_bid_sync(db: Session, user: AppUser) -> None:
    """Sync guard for creator auction place_bid."""
    from fastapi import HTTPException, status

    row = (
        db.query(PlatformSetting)
        .filter(PlatformSetting.setting_key == _block_key(user.id))
        .first()
    )
    if not row or not row.setting_value:
        return
    try:
        data = json.loads(row.setting_value)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is blocked from bidding. Contact support.",
        )
    if data.get("unblockedAt"):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=data.get("reason")
        or "Your account is blocked from bidding after an unpaid auction win.",
    )


async def assert_user_can_bid_async(session: AsyncSession, user: AppUser) -> None:
    from app.core.exceptions import AppException

    life = WinnerPaymentLifecycleAsync(session)
    blocked, reason = await life.is_user_bidding_blocked(user.id)
    if blocked:
        raise AppException(
            reason or "Your account is blocked from bidding after an unpaid auction win.",
            status_code=403,
        )
