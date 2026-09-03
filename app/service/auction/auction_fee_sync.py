"""Sync-session helpers for community auction fee flows."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.entity.auction.auction_fee_payment_entity import (
    AuctionFeeAuctionType,
    AuctionFeePayment,
    AuctionFeePaymentKind,
    AuctionFeePaymentStatus,
)
from app.entity.auction.auction_participation_entity import (
    AuctionParticipation,
    AuctionParticipationStatus,
    AuctionParticipationType,
)
from app.entity.platform.platform_setting_entity import PlatformSetting
from app.integrations.razorpay import client as rzp
from app.service.platform.platform_settings_service import (
    DEFAULT_PARTICIPATION_FEE,
    KEY_COMMUNITY_PARTICIPATION_FEE,
)


def _settings_float(db: Session, key: str, default: float) -> float:
    row = db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first()
    if row is None:
        return default
    try:
        return float(str(row.setting_value).strip())
    except ValueError:
        return default


def auction_creation_fee_inr(db: Session) -> float:
    return _settings_float(db, "auction_creation_fee_inr", 118.0)


def auction_bid_fee_inr(db: Session) -> float:
    return _settings_float(db, "auction_bid_fee_inr", 20.0)


def community_participation_fee_inr(db: Session) -> float:
    return _settings_float(
        db,
        KEY_COMMUNITY_PARTICIPATION_FEE,
        DEFAULT_PARTICIPATION_FEE,
    )


def has_community_participation_paid(
    db: Session,
    auction_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    row = db.query(AuctionParticipation).filter(
        AuctionParticipation.auction_type == AuctionParticipationType.COMMUNITY,
        AuctionParticipation.auction_id == auction_id,
        AuctionParticipation.user_id == user_id,
        AuctionParticipation.status == AuctionParticipationStatus.COMPLETED,
    ).first()
    return row is not None


def consume_creation_fee_sync(
    db: Session,
    *,
    user_id: uuid.UUID,
    order_id: str,
    auction_id: uuid.UUID,
) -> None:
    row = (
        db.query(AuctionFeePayment)
        .filter(
            AuctionFeePayment.razorpay_order_id == order_id,
            AuctionFeePayment.user_id == user_id,
            AuctionFeePayment.payment_kind == AuctionFeePaymentKind.CREATION,
            AuctionFeePayment.auction_type == AuctionFeeAuctionType.COMMUNITY,
            AuctionFeePayment.status == AuctionFeePaymentStatus.COMPLETED,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Valid auction creation fee payment is required.",
        )
    row.status = AuctionFeePaymentStatus.CONSUMED
    row.auction_id = auction_id
    row.updated_at = datetime.now(timezone.utc)
    db.flush()


def verify_bid_fee_sync(
    db: Session,
    *,
    user_id: uuid.UUID,
    auction_id: uuid.UUID,
    bid_amount: Decimal | float,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> AuctionFeePayment:
    if not rzp.verify_payment_signature(
        razorpay_order_id, razorpay_payment_id, razorpay_signature
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid bid fee payment signature.",
        )
    row = (
        db.query(AuctionFeePayment)
        .filter(
            AuctionFeePayment.razorpay_order_id == razorpay_order_id,
            AuctionFeePayment.user_id == user_id,
            AuctionFeePayment.auction_id == auction_id,
            AuctionFeePayment.payment_kind == AuctionFeePaymentKind.BID,
            AuctionFeePayment.auction_type == AuctionFeeAuctionType.COMMUNITY,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bid fee payment not found.",
        )
    if row.status == AuctionFeePaymentStatus.CONSUMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bid fee payment already used.",
        )
    if row.bid_amount is None or float(row.bid_amount) != float(bid_amount):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bid amount does not match the paid bid fee order.",
        )
    row.status = AuctionFeePaymentStatus.COMPLETED
    row.razorpay_payment_id = razorpay_payment_id
    row.updated_at = datetime.now(timezone.utc)
    db.flush()
    return row


def consume_bid_fee_sync(db: Session, row: AuctionFeePayment) -> None:
    if row.status == AuctionFeePaymentStatus.CONSUMED:
        return
    if row.status != AuctionFeePaymentStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Bid fee payment is not verified.",
        )
    row.status = AuctionFeePaymentStatus.CONSUMED
    row.updated_at = datetime.now(timezone.utc)
    db.flush()


def verify_and_consume_bid_fee_sync(
    db: Session,
    *,
    user_id: uuid.UUID,
    auction_id: uuid.UUID,
    bid_amount: Decimal | float,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> None:
    row = verify_bid_fee_sync(
        db,
        user_id=user_id,
        auction_id=auction_id,
        bid_amount=bid_amount,
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
        razorpay_signature=razorpay_signature,
    )
    consume_bid_fee_sync(db, row)
