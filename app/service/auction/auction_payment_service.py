"""
Razorpay payment flow for domain auction winners (PAYMENT_PENDING → COMPLETED).

After successful payment, marks the domain listing sold and starts the standard
marketplace transfer workflow (same as a direct domain purchase).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.auction.auction_entity import Auction
from app.entity.auction.payment_entity import Payment
from app.entity.auction.transaction_entity import Transaction
from app.entity.domain.domain_marketplace_transaction_entity import (
    DomainMarketplaceTransaction,
)
from app.entity.user.app_user import AppUser
from app.integrations.razorpay import client as rzp
from app.model.payment.payment_response import payment_status_label
from app.repository.auction_repository import AuctionRepository
from app.repository.domain_listing_repository import DomainListingRepository
from app.repository.domain_marketplace_transaction_repository import (
    DomainMarketplaceTransactionRepository,
)
from app.repository.payment_repository import PaymentRepository
from app.service.domain.domain_marketplace_transaction_service import (
    DomainMarketplaceTransactionService,
)
from app.service.domain.domain_transfer_notification_service import (
    DomainTransferNotificationService,
)
from app.utils.enums import AuctionStatus, PaymentStatus, TransactionStatus
from app.utils.marketplace_enums import DomainListingStatus, MarketplacePaymentStatus

logger = logging.getLogger(__name__)


class AuctionPaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._auctions = AuctionRepository(session)
        self._payments = PaymentRepository(session)

    async def create_winner_order(
        self,
        auction_id: uuid.UUID,
        user: AppUser,
        redeem_points: bool = False,
    ) -> dict[str, Any]:
        if not rzp.is_configured():
            raise AppException(
                "Payment gateway is not configured.",
                status_code=503,
            )

        auction = await self._lock_auction(auction_id)
        self._require_winner(auction, user)
        self._require_payment_pending(auction)

        if await self._payments.get_success_for_auction(auction_id):
            raise AppException(
                "This auction has already been paid for.",
                status_code=409,
            )

        amount = self._winner_payment_amount(auction)
        amount_to_charge = float(amount)
        points_redeemed = 0
        if amount_to_charge > 0:
            from app.service.user.edge_points_service import EdgePointsService
            amount_to_charge, points_redeemed = await EdgePointsService.calculate_redemption(
                self._session, user, amount_to_charge, redeem_points
            )

        receipt = f"auc_{str(auction_id).replace('-', '')[:24]}"
        try:
            rzp_order = rzp.create_order(
                amount_inr=amount_to_charge,
                receipt=receipt,
                notes={
                    "auctionId": str(auction_id),
                    "userId": str(user.id),
                    "type": "domain_auction_winner",
                },
            )
            if points_redeemed > 0:
                from app.service.user.edge_points_service import EdgePointsService
                await EdgePointsService.create_pending_redemption(
                    self._session, user.id, rzp_order["id"], points_redeemed
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("razorpay.create_order.failed auction=%s", auction_id)
            raise AppException(
                "Could not create payment order. Please try again.",
                status_code=502,
            ) from exc

        existing = await self._payments.get_open_for_auction_user(
            auction_id, user.id
        )
        if existing:
            existing.razorpay_order_id = rzp_order["id"]
            existing.amount = amount
            existing.currency = "INR"
            existing.payment_status = PaymentStatus.PENDING
            existing.razorpay_payment_id = None
            existing.paid_at = None
            existing.updated_at = datetime.now(timezone.utc)
            payment = await self._payments.save(existing)
        else:
            payment = Payment(
                auction_id=auction_id,
                user_id=user.id,
                razorpay_order_id=rzp_order["id"],
                amount=amount,
                currency="INR",
                payment_status=PaymentStatus.PENDING,
            )
            payment = await self._payments.create(payment)

        await self._session.commit()

        return {
            "orderId": rzp_order["id"],
            "amount": float(amount),
            "currency": "INR",
            "keyId": rzp.get_key_id(),
            "paymentId": payment.id,
            "status": payment_status_label(payment.payment_status),
            "auction": {
                "id": auction.id,
                "domainId": auction.domain_id,
                "status": auction.status,
                "currentHighestBid": auction.current_highest_bid,
                "currentWinnerId": auction.current_winner_id,
            },
        }

    async def verify_winner_payment(
        self,
        *,
        user: AppUser,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> dict[str, Any]:
        payment = await self._payments.get_by_order_id(razorpay_order_id)
        if payment is None:
            raise AppException("Payment record not found.", status_code=404)

        if payment.user_id != user.id:
            raise AppException(
                "You are not authorized to verify this payment.",
                status_code=403,
            )

        auction = await self._lock_auction(payment.auction_id)

        if payment.payment_status == PaymentStatus.SUCCESS:
            if auction.status != AuctionStatus.COMPLETED:
                auction.status = AuctionStatus.COMPLETED
                await self._session.flush()
            transfer_tx = await self._ensure_domain_transfer(
                auction,
                payment,
                user,
            )
            await self._session.commit()
            from app.service.user.edge_points_service import EdgePointsService
            await EdgePointsService.confirm_redemption(self._session, razorpay_order_id)
            return self._verify_success_payload(auction, payment, transfer_tx)

        if not rzp.verify_payment_signature(
            razorpay_order_id,
            razorpay_payment_id,
            razorpay_signature,
        ):
            from app.service.user.edge_points_service import EdgePointsService
            await EdgePointsService.cancel_redemption(self._session, razorpay_order_id)
            payment.payment_status = PaymentStatus.FAILED
            payment.updated_at = datetime.now(timezone.utc)
            await self._record_transaction(
                payment,
                razorpay_payment_id,
                TransactionStatus.FAILED,
                {"reason": "signature_mismatch"},
            )
            await self._session.commit()
            raise AppException("Invalid payment signature.", status_code=400)

        if auction.status != AuctionStatus.PAYMENT_PENDING:
            if auction.status == AuctionStatus.COMPLETED:
                payment.payment_status = PaymentStatus.SUCCESS
                payment.razorpay_payment_id = razorpay_payment_id
                transfer_tx = await self._ensure_domain_transfer(
                    auction,
                    payment,
                    user,
                )
                await self._session.commit()
                return self._verify_success_payload(auction, payment, transfer_tx)
            raise AppException(
                f"Auction is not awaiting payment (status={auction.status.value}).",
                status_code=409,
            )

        self._require_winner(auction, user)

        now = datetime.now(timezone.utc)
        payment.payment_status = PaymentStatus.SUCCESS
        payment.razorpay_payment_id = razorpay_payment_id
        payment.paid_at = now
        payment.updated_at = now

        auction.status = AuctionStatus.COMPLETED

        await self._record_transaction(
            payment,
            razorpay_payment_id,
            TransactionStatus.VERIFIED,
            {
                "razorpay_order_id": razorpay_order_id,
                "razorpay_payment_id": razorpay_payment_id,
            },
        )

        transfer_tx = await self._ensure_domain_transfer(auction, payment, user)
        await self._session.flush()
        await self._session.commit()
        from app.service.user.edge_points_service import EdgePointsService
        await EdgePointsService.confirm_redemption(self._session, razorpay_order_id)

        await self._publish_payment_completed(auction, payment, transfer_tx)

        logger.info(
            "auction.payment.completed id=%s winner=%s amount=%s transfer=%s",
            auction.id,
            user.id,
            payment.amount,
            transfer_tx.id if transfer_tx else None,
        )
        return self._verify_success_payload(auction, payment, transfer_tx)

    @staticmethod
    def _verify_success_payload(
        auction: Auction,
        payment: Payment,
        transfer_tx: DomainMarketplaceTransaction | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "success": True,
            "message": "Payment verified. Domain transfer has started.",
            "auctionId": auction.id,
            "auctionStatus": auction.status,
            "paymentStatus": payment_status_label(payment.payment_status),
        }
        if transfer_tx is not None:
            payload["transferTransactionId"] = transfer_tx.id
            payload["transferStatus"] = transfer_tx.transfer_status.value
        return payload

    async def _ensure_domain_transfer(
        self,
        auction: Auction,
        payment: Payment,
        buyer: AppUser,
    ) -> DomainMarketplaceTransaction | None:
        if not payment.razorpay_payment_id:
            return None

        tx_repo = DomainMarketplaceTransactionRepository(self._session)
        existing = await tx_repo.get_by_razorpay_payment_id(payment.razorpay_payment_id)
        if existing is not None:
            return existing

        listing_repo = DomainListingRepository(self._session)
        listing = await listing_repo.get_by_id_for_update(auction.domain_id)
        if listing is None:
            logger.error(
                "auction.payment.listing_missing auction=%s listing=%s",
                auction.id,
                auction.domain_id,
            )
            return None

        winning_amount = float(payment.amount or auction.current_highest_bid or 0)
        if winning_amount <= 0:
            logger.error(
                "auction.payment.invalid_amount auction=%s amount=%s",
                auction.id,
                winning_amount,
            )
            return None

        now = datetime.now(timezone.utc)
        listing.domain_status = DomainListingStatus.SOLD
        listing.payment_status = MarketplacePaymentStatus.COMPLETED
        listing.purchased_by_user_id = buyer.id
        listing.razorpay_order_id = payment.razorpay_order_id
        listing.razorpay_payment_id = payment.razorpay_payment_id
        listing.sold_at = now
        listing.asking_price = winning_amount
        await listing_repo.save(listing)

        tx_service = DomainMarketplaceTransactionService(self._session)
        notify = DomainTransferNotificationService(self._session)
        try:
            tx = await tx_service.create_from_payment(
                listing,
                buyer=buyer,
                razorpay_order_id=payment.razorpay_order_id,
                razorpay_payment_id=payment.razorpay_payment_id,
                gross_amount_inr=winning_amount,
            )
            await notify.on_payment_completed(tx)
            return tx
        except IntegrityError:
            replay = await tx_repo.get_by_razorpay_payment_id(payment.razorpay_payment_id)
            return replay

    async def _lock_auction(self, auction_id: uuid.UUID) -> Auction:
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
        return auction

    @staticmethod
    def _winner_payment_amount(auction: Auction) -> Decimal:
        winning_bid = auction.current_highest_bid
        if winning_bid is None or float(winning_bid) <= 0:
            raise AppException(
                "No winning bid amount is available for this auction.",
                status_code=409,
            )
        return Decimal(str(winning_bid))

    @staticmethod
    def _require_payment_pending(auction: Auction) -> None:
        if auction.status != AuctionStatus.PAYMENT_PENDING:
            raise AppException(
                f"Auction is not awaiting payment (status={auction.status.value}).",
                status_code=409,
            )

    @staticmethod
    def _require_winner(auction: Auction, user: AppUser) -> None:
        if auction.current_winner_id != user.id:
            raise AppException(
                "Only the auction winner can complete this payment.",
                status_code=403,
            )

    async def _record_transaction(
        self,
        payment: Payment,
        reference: str,
        status: TransactionStatus,
        gateway_response: dict[str, Any],
    ) -> None:
        txn = Transaction(
            payment_id=payment.id,
            transaction_reference=reference,
            transaction_status=status,
            gateway_response=gateway_response,
        )
        self._session.add(txn)

    async def _publish_payment_completed(
        self,
        auction: Auction,
        payment: Payment,
        transfer_tx: DomainMarketplaceTransaction | None,
    ) -> None:
        event: dict[str, Any] = {
            "type": "PAYMENT_COMPLETED",
            "auctionId": str(auction.id),
            "auction_id": str(auction.id),
            "domain_id": str(auction.domain_id),
            "status": auction.status.value,
            "winnerPaymentPaid": True,
            "currentHighestBid": float(payment.amount or 0),
            "winner": {
                "user_id": str(payment.user_id),
                "amount": str(payment.amount),
            },
            "razorpay_order_id": payment.razorpay_order_id,
            "razorpay_payment_id": payment.razorpay_payment_id,
        }
        if transfer_tx is not None:
            event["transferTransactionId"] = str(transfer_tx.id)
            event["transferStatus"] = transfer_tx.transfer_status.value
        try:
            from app.websocket.manager import broadcast_to_auction  # type: ignore

            await broadcast_to_auction(str(auction.id), event)
        except Exception:  # noqa: BLE001
            logger.exception(
                "ws.broadcast.failed auction=%s event=PAYMENT_COMPLETED",
                auction.id,
            )
