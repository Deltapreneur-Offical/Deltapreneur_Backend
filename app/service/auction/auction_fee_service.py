"""Razorpay flows for auction creation fees and per-bid fees."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

import razorpay
from razorpay.errors import BadRequestError, GatewayError, ServerError

from app.core.exceptions import AppException
from app.entity.auction.auction_fee_payment_entity import (
    AuctionFeeAuctionType,
    AuctionFeePayment,
    AuctionFeePaymentKind,
    AuctionFeePaymentStatus,
)
from app.entity.user.app_user import AppUser
from app.integrations.razorpay import client as rzp
from app.repository.auction_fee_payment_repository import AuctionFeePaymentRepository
from app.service.platform.platform_settings_service import PlatformSettingsService
from app.utils.admin_fee_roles import role_waives_auction_platform_fees

logger = logging.getLogger(__name__)


class AuctionFeeService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = AuctionFeePaymentRepository(session)
        self._settings = PlatformSettingsService(session)

    async def create_creation_fee_order(
        self,
        *,
        auction_type: AuctionFeeAuctionType,
        user: AppUser,
        reference_id: uuid.UUID | None = None,
        redeem_points: bool = False,
    ) -> dict:
        if role_waives_auction_platform_fees(getattr(user, "role", None)):
            return {
                "orderId": f"admin_free_{auction_type.value}_{user.id}",
                "amount": 0,
                "currency": "INR",
                "keyId": rzp.get_key_id() if rzp.is_configured() else "",
                "auctionType": auction_type.value,
            }

        if not rzp.is_configured():
            raise AppException("Payment gateway is not configured.", status_code=503)

        fee = await self._settings.auction_creation_fee_inr()
        points_redeemed = 0
        if fee > 0:
            from app.service.user.edge_points_service import EdgePointsService
            fee, points_redeemed = await EdgePointsService.calculate_redemption(
                self._session, user, fee, redeem_points
            )

        receipt = f"acf_{auction_type.value[:3]}_{user.id}"[:40]
        try:
            order = rzp.create_order(
                amount_inr=fee,
                receipt=receipt,
                notes={
                    "userId": str(user.id),
                    "type": f"{auction_type.value.lower()}_auction_creation_fee",
                },
            )
            if points_redeemed > 0:
                from app.service.user.edge_points_service import EdgePointsService
                await EdgePointsService.create_pending_redemption(
                    self._session, user.id, order["id"], points_redeemed
                )
        except (ValueError, RuntimeError) as exc:
            raise AppException(str(exc), status_code=400) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "auction_fees.creation_order_failed auction_type=%s user_id=%s",
                auction_type.value,
                user.id,
            )
            raise AppException(
                f"Unable to create auction creation fee order ({type(exc).__name__}: {exc}).",
                status_code=502,
            ) from exc

        row = AuctionFeePayment(
            payment_kind=AuctionFeePaymentKind.CREATION,
            auction_type=auction_type,
            user_id=user.id,
            reference_id=reference_id,
            fee_amount_inr=fee,
            razorpay_order_id=order["id"],
            status=AuctionFeePaymentStatus.CREATED,
        )
        try:
            await self._repo.create(row)
            await self._session.commit()
        except SQLAlchemyError as exc:
            logger.exception(
                "auction_fees.creation_payment_row_failed auction_type=%s user_id=%s",
                auction_type.value,
                user.id,
            )
            raise AppException(
                f"Unable to persist auction creation fee order ({type(exc).__name__}: {exc}).",
                status_code=500,
            ) from exc
        return {
            "orderId": order["id"],
            "amount": fee,
            "currency": "INR",
            "keyId": rzp.get_key_id(),
            "auctionType": auction_type.value,
        }

    async def verify_creation_fee_payment(
        self,
        *,
        user: AppUser,
        auction_type: AuctionFeeAuctionType,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> dict:
        if not rzp.verify_payment_signature(
            razorpay_order_id, razorpay_payment_id, razorpay_signature
        ):
            from app.service.user.edge_points_service import EdgePointsService
            await EdgePointsService.cancel_redemption(self._session, razorpay_order_id)
            raise AppException("Invalid payment signature.", status_code=400)

        row = await self._repo.get_by_order_id(razorpay_order_id)
        if (
            row is None
            or row.user_id != user.id
            or row.payment_kind != AuctionFeePaymentKind.CREATION
            or row.auction_type != auction_type
        ):
            raise AppException("Creation fee payment not found.", status_code=404)
        if row.status == AuctionFeePaymentStatus.CONSUMED:
            raise AppException("Creation fee payment already used.", status_code=409)

        row.status = AuctionFeePaymentStatus.COMPLETED
        row.razorpay_payment_id = razorpay_payment_id
        row.updated_at = datetime.now(timezone.utc)
        await self._repo.save(row)
        await self._session.commit()
        from app.service.user.edge_points_service import EdgePointsService
        await EdgePointsService.confirm_redemption(self._session, razorpay_order_id)
        return {
            "verified": True,
            "orderId": razorpay_order_id,
            "message": "Auction creation fee confirmed.",
        }

    async def consume_creation_fee(
        self,
        *,
        user: AppUser,
        auction_type: AuctionFeeAuctionType,
        creation_fee_order_id: str,
        auction_id: uuid.UUID,
    ) -> None:
        row = await self._repo.get_completed_creation_payment(
            order_id=creation_fee_order_id,
            user_id=user.id,
            auction_type=auction_type,
        )
        if row is None:
            raise AppException(
                "Valid auction creation fee payment is required.",
                status_code=402,
            )
        row.status = AuctionFeePaymentStatus.CONSUMED
        row.auction_id = auction_id
        row.updated_at = datetime.now(timezone.utc)
        await self._repo.save(row)

    async def create_bid_fee_order(
        self,
        *,
        auction_type: AuctionFeeAuctionType,
        auction_id: uuid.UUID,
        bid_amount: Decimal | float,
        user: AppUser,
        redeem_points: bool = False,
    ) -> dict:
        logger.info(
            "auction_fees.bid_order_start auction_type=%s auction_id=%s user_id=%s bid_amount=%s razorpay_key_id=%s test_mode=%s",
            auction_type.value,
            auction_id,
            user.id,
            bid_amount,
            rzp.get_key_id(),
            rzp.is_test_mode(),
        )

        if float(bid_amount) <= 0:
            raise AppException("Bid amount must be positive.", status_code=400)

        if role_waives_auction_platform_fees(getattr(user, "role", None)):
            return {
                "orderId": f"admin_free_bid_{auction_type.value}_{auction_id}_{user.id}",
                "amount": 0,
                "currency": "INR",
                "keyId": rzp.get_key_id() if rzp.is_configured() else "",
                "auctionType": auction_type.value,
                "auctionId": str(auction_id),
                "bidAmount": float(bid_amount),
            }

        if not rzp.is_configured():
            logger.error("auction_fees.bid_order_failed payment_gateway_not_configured")
            raise AppException("Payment gateway is not configured.", status_code=503)

        # Platform Bid Placement Fee (admin setting) — NOT the user's bid amount.
        fee = float(await self._settings.auction_bid_fee_inr())
        if fee <= 0:
            raise AppException(
                "Auction bid placement fee is not configured.",
                status_code=503,
            )
        points_redeemed = 0
        if fee > 0:
            from app.service.user.edge_points_service import EdgePointsService
            fee, points_redeemed = await EdgePointsService.calculate_redemption(
                self._session, user, fee, redeem_points
            )
            fee = float(fee)

        logger.info(
            "auction_fees.bid_order_charging auction_type=%s auction_id=%s "
            "fee_inr=%s bid_amount=%s (Razorpay charges fee only)",
            auction_type.value,
            auction_id,
            fee,
            bid_amount,
        )

        receipt = f"abf_{auction_id}_{user.id}"[:40]
        try:
            order = rzp.create_order(
                amount_inr=fee,
                receipt=receipt,
                notes={
                    "auctionId": str(auction_id),
                    "userId": str(user.id),
                    "type": f"{auction_type.value.lower()}_auction_bid_fee",
                    "bidAmount": str(bid_amount),
                },
            )
            if points_redeemed > 0:
                from app.service.user.edge_points_service import EdgePointsService
                await EdgePointsService.create_pending_redemption(
                    self._session, user.id, order["id"], points_redeemed
                )
        except AppException:
            raise
        except (ValueError, RuntimeError) as exc:
            logger.warning(
                "auction_fees.bid_order_failed bad_request auction_type=%s auction_id=%s user_id=%s error=%s",
                auction_type.value,
                auction_id,
                user.id,
                exc,
            )
            raise AppException(str(exc), status_code=400) from exc
        except (BadRequestError, GatewayError, ServerError) as exc:
            status_code = 502 if isinstance(exc, GatewayError) else (
                500 if isinstance(exc, ServerError) else 400
            )
            logger.warning(
                "auction_fees.bid_order_failed razorpay_error auction_type=%s auction_id=%s user_id=%s status=%s error=%s",
                auction_type.value,
                auction_id,
                user.id,
                status_code,
                exc,
            )
            raise AppException(
                f"Payment gateway error: {exc}",
                status_code=status_code,
            ) from exc
        except (RequestsConnectionError, RequestsTimeout) as exc:
            logger.exception(
                "auction_fees.bid_order_failed upstream_gateway auction_type=%s auction_id=%s user_id=%s error=%s",
                auction_type.value,
                auction_id,
                user.id,
                exc,
            )
            raise AppException(
                "Unable to reach the payment gateway. Please check your connection and try again.",
                status_code=502,
            ) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "auction_fees.bid_order_failed unexpected auction_type=%s auction_id=%s user_id=%s error=%s",
                auction_type.value,
                auction_id,
                user.id,
                exc,
            )
            raise AppException(
                f"Unable to create bid fee order ({type(exc).__name__}: {exc}).",
                status_code=500,
            ) from exc

        row = AuctionFeePayment(
            payment_kind=AuctionFeePaymentKind.BID,
            auction_type=auction_type,
            user_id=user.id,
            auction_id=auction_id,
            bid_amount=Decimal(str(bid_amount)),
            fee_amount_inr=float(fee),
            razorpay_order_id=order["id"],
            status=AuctionFeePaymentStatus.CREATED,
        )
        try:
            await self._repo.create(row)
            await self._session.commit()
        except SQLAlchemyError as exc:
            logger.exception(
                "auction_fees.bid_payment_row_failed auction_type=%s auction_id=%s user_id=%s",
                auction_type.value,
                auction_id,
                user.id,
            )
            raise AppException(
                f"Unable to persist bid fee order ({type(exc).__name__}: {exc}).",
                status_code=500,
            ) from exc

        logger.info(
            "auction_fees.bid_order_success auction_type=%s auction_id=%s user_id=%s "
            "order_id=%s fee=%s bid_amount=%s",
            auction_type.value,
            auction_id,
            user.id,
            order["id"],
            fee,
            bid_amount,
        )
        return {
            "orderId": order["id"],
            "amount": float(fee),
            "currency": "INR",
            "keyId": rzp.get_key_id(),
            "auctionId": str(auction_id),
            "bidAmount": float(bid_amount),
        }

    async def verify_bid_fee_payment(
        self,
        *,
        auction_type: AuctionFeeAuctionType,
        auction_id: uuid.UUID,
        user: AppUser,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
        expected_bid_amount: Decimal | float,
    ) -> AuctionFeePayment:
        """Validate Razorpay bid-fee payment; mark COMPLETED (not consumed yet)."""
        if (
            role_waives_auction_platform_fees(getattr(user, "role", None))
            and str(razorpay_order_id or "").startswith("admin_free_bid_")
        ):
            # Synthetic row so consume_bid_fee is a no-op-friendly COMPLETED marker.
            row = AuctionFeePayment(
                payment_kind=AuctionFeePaymentKind.BID,
                auction_type=auction_type,
                user_id=user.id,
                auction_id=auction_id,
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id or "admin_free",
                fee_amount_inr=0,
                bid_amount=Decimal(str(expected_bid_amount)),
                status=AuctionFeePaymentStatus.COMPLETED,
            )
            try:
                await self._repo.save(row)
            except Exception:
                logger.debug("auction_fees.admin_free_bid_row_skip", exc_info=True)
            return row

        if not rzp.verify_payment_signature(
            razorpay_order_id, razorpay_payment_id, razorpay_signature
        ):
            from app.service.user.edge_points_service import EdgePointsService
            await EdgePointsService.cancel_redemption(self._session, razorpay_order_id)
            raise AppException("Invalid payment signature.", status_code=400)

        row = await self._repo.get_by_order_id(razorpay_order_id)
        if (
            row is None
            or row.user_id != user.id
            or row.payment_kind != AuctionFeePaymentKind.BID
            or row.auction_type != auction_type
            or row.auction_id != auction_id
        ):
            raise AppException("Bid fee payment not found.", status_code=404)
        if row.status == AuctionFeePaymentStatus.CONSUMED:
            raise AppException("Bid fee payment already used.", status_code=409)
        if row.bid_amount is None or float(row.bid_amount) != float(expected_bid_amount):
            raise AppException(
                "Bid amount does not match the paid bid fee order.",
                status_code=400,
            )

        row.status = AuctionFeePaymentStatus.COMPLETED
        row.razorpay_payment_id = razorpay_payment_id
        row.updated_at = datetime.now(timezone.utc)
        await self._repo.save(row)
        from app.service.user.edge_points_service import EdgePointsService
        await EdgePointsService.confirm_redemption(self._session, razorpay_order_id)
        return row

    async def consume_bid_fee(self, row: AuctionFeePayment) -> None:
        if row.status == AuctionFeePaymentStatus.CONSUMED:
            return
        if row.status != AuctionFeePaymentStatus.COMPLETED:
            raise AppException("Bid fee payment is not verified.", status_code=402)
        row.status = AuctionFeePaymentStatus.CONSUMED
        row.updated_at = datetime.now(timezone.utc)
        await self._repo.save(row)

    async def verify_and_consume_bid_fee(
        self,
        *,
        auction_type: AuctionFeeAuctionType,
        auction_id: uuid.UUID,
        user: AppUser,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
        expected_bid_amount: Decimal | float,
    ) -> AuctionFeePayment:
        row = await self.verify_bid_fee_payment(
            auction_type=auction_type,
            auction_id=auction_id,
            user=user,
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
            expected_bid_amount=expected_bid_amount,
        )
        await self.consume_bid_fee(row)
        return row
