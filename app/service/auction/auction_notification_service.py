"""In-app notifications for domain auctions (sync Session bridge)."""

from __future__ import annotations

import logging
import uuid

from app.core.database import SessionLocal
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.service.notification.notification_service import NotificationService

logger = logging.getLogger(__name__)


def _notify_sync(
    user: AppUser,
    *,
    title: str,
    message: str,
    target_url: str,
) -> None:
    db = SessionLocal()
    try:
        NotificationService.notify(
            db=db,
            user=user,
            notification_type=NotificationType.AUCTION_UPDATE,
            title=title,
            message=message,
            target_url=target_url,
        )
        db.commit()
    except Exception:
        logger.exception("auction.notify.failed user=%s", user.id)
        db.rollback()
    finally:
        db.close()


def notify_winner_payment_due(
    winner: AppUser,
    *,
    auction_id: uuid.UUID,
    domain_label: str,
    amount_inr: float,
) -> None:
    _notify_sync(
        winner,
        title="You won the domain auction!",
        message=(
            f'You won "{domain_label}" with a bid of ₹{amount_inr:,.2f}. '
            "Complete payment to start the domain transfer."
        ),
        target_url=f"/auction/{auction_id}",
    )


def notify_seller_auction_ended_with_winner(
    seller: AppUser,
    *,
    auction_id: uuid.UUID,
    domain_label: str,
    winner_name: str,
    amount_inr: float,
) -> None:
    _notify_sync(
        seller,
        title="Your domain auction has ended",
        message=(
            f'"{domain_label}" was won by {winner_name} for ₹{amount_inr:,.2f}. '
            "The winner must complete payment to finalize the sale."
        ),
        target_url=f"/auction/{auction_id}",
    )


def notify_winner_payment_completed(
    winner: AppUser,
    *,
    domain_label: str,
    amount_inr: float,
    transfer_url: str,
) -> None:
    _notify_sync(
        winner,
        title="Payment complete — transfer started",
        message=(
            f'Your payment of ₹{amount_inr:,.2f} for "{domain_label}" was successful. '
            "Track the domain transfer from your purchases."
        ),
        target_url=transfer_url,
    )


def notify_seller_payment_received(
    seller: AppUser,
    *,
    domain_label: str,
    winner_name: str,
    amount_inr: float,
    transfer_url: str,
) -> None:
    _notify_sync(
        seller,
        title="Winner payment received",
        message=(
            f"{winner_name} paid ₹{amount_inr:,.2f} for \"{domain_label}\". "
            "Submit the auth code to complete the transfer."
        ),
        target_url=transfer_url,
    )
