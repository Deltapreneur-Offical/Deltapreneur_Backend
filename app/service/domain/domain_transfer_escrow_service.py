"""Escrow hold, refund, and admin review resolution."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.entity.user.app_user import AppUser
from app.integrations.razorpay import client as rzp
from app.integrations.razorpay.client import AlreadyFullyRefunded
from app.repository.domain_listing_repository import DomainListingRepository
from app.repository.domain_marketplace_transaction_repository import (
    DomainMarketplaceTransactionRepository,
)
from app.service.domain.domain_transfer_event_service import DomainTransferEventService
from app.service.domain.domain_transfer_notification_service import (
    DomainTransferNotificationService,
)
from app.utils.marketplace_enums import DomainListingStatus, MarketplacePaymentStatus
from app.utils.transfer_enums import (
    MarketplaceEscrowStatus,
    MarketplaceTransferStatus,
    TransferEventType,
    TransferVerifiedBy,
)

logger = logging.getLogger(__name__)


class DomainTransferEscrowService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DomainMarketplaceTransactionRepository(session)
        self._listings = DomainListingRepository(session)
        self._events = DomainTransferEventService(session)
        self._notify = DomainTransferNotificationService(session)

    async def _restore_listing(self, listing_id: uuid.UUID, *, refunded: bool = False) -> None:
        """Update listing after refund or cancellation.

        After a refund the listing is restored to AVAILABLE so the
        domain can be purchased again by anyone.  The purchase
        association is preserved via the DomainMarketplaceTransaction
        records, not the listing.
        """
        listing = await self._listings.get_by_id_for_update(listing_id)
        if listing is None:
            return
        # Always restore to AVAILABLE — the listing is the shared
        # marketplace record and must not be stuck in SOLD/REFUNDED.
        # Refund state is tracked on the transaction, not the listing.
        listing.domain_status = DomainListingStatus.AVAILABLE
        listing.payment_status = None
        listing.purchased_by_user_id = None
        listing.active_transaction_id = None
        listing.sold_at = None
        await self._listings.save(listing)

    @staticmethod
    def _compute_gst_inclusive_amount(tx) -> float:
        """Compute the expected GST-inclusive buyer-paid amount."""
        base = float(tx.gross_amount_inr or 0)
        return round(base * 1.18, 2) if base > 0 else 0.0

    async def refund(
        self,
        tx_id: uuid.UUID,
        *,
        admin: AppUser,
        note: str | None = None,
    ) -> dict:
        tx = await self._repo.get_by_id_for_update(tx_id)
        if tx is None:
            raise AppException("Transfer transaction not found.", status_code=404)

        # Idempotent: already refunded at escrow or transfer level.
        if (
            tx.escrow_status == MarketplaceEscrowStatus.REFUNDED
            or tx.transfer_status == MarketplaceTransferStatus.REFUNDED
        ):
            # Fetch the real Razorpay refund ID if we don't have it yet.
            refund_id = tx.razorpay_refund_id
            if not refund_id and tx.razorpay_payment_id:
                try:
                    import razorpay as razorpay_lib
                    from app.integrations.razorpay.client import (
                        _fetch_existing_refund_id,
                    )
                    client_obj = razorpay_lib.Client(
                        auth=(rzp._key_id(), rzp._key_secret())
                    )
                    refund_id = _fetch_existing_refund_id(
                        client_obj, tx.razorpay_payment_id
                    )
                    if refund_id:
                        tx.razorpay_refund_id = refund_id
                        await self._repo.save(tx)
                        await self._session.commit()
                except Exception:
                    pass
            return {
                "success": True,
                "refundId": refund_id,
                "refundAmountInr": self._compute_gst_inclusive_amount(tx),
            }

        if not tx.razorpay_payment_id:
            raise AppException("No payment to refund.", status_code=400)
        if tx.escrow_status == MarketplaceEscrowStatus.RELEASED:
            raise AppException(
                "Escrow already released (seller paid). Cannot refund.",
                status_code=409,
            )
        if tx.transfer_status in (
            MarketplaceTransferStatus.PAYOUT_APPROVED,
            MarketplaceTransferStatus.PAYOUT_RELEASED,
            MarketplaceTransferStatus.COMPLETED,
            MarketplaceTransferStatus.SELLER_PAID,
        ):
            raise AppException(
                f"Transaction is in terminal state '{tx.transfer_status.value}'; cannot refund.",
                status_code=409,
            )

        # --- Call the REAL Razorpay Refund API ---
        # The refund amount is the GST-inclusive buyer-paid amount.
        expected_amount_inr = self._compute_gst_inclusive_amount(tx)

        try:
            refund = rzp.refund_payment(
                tx.razorpay_payment_id, expected_amount_inr
            )
        except AlreadyFullyRefunded as exc:
            # Payment is already fully refunded on Razorpay but our DB
            # was never synced.  Sync the DB state using the REAL
            # Razorpay refund ID (never generate a fake one).
            logger.info(
                "refund.already_refunded_on_razorpay payment=%s tx=%s refund_id=%s",
                tx.razorpay_payment_id, tx.id, exc.refund_id,
            )
            now = datetime.now(timezone.utc)
            tx.escrow_status = MarketplaceEscrowStatus.REFUNDED
            tx.transfer_status = MarketplaceTransferStatus.REFUNDED
            tx.refund_completed_at = now
            tx.razorpay_refund_id = exc.refund_id  # Real Razorpay refund ID
            await self._repo.save(tx)
            await self._restore_listing(tx.domain_listing_id, refunded=True)
            await self._events.log(
                tx.id,
                TransferEventType.REFUNDED,
                actor_user_id=admin.id,
                actor_role="ADMIN",
                payload={
                    "note": note or "Payment already fully refunded on Razorpay. DB synced.",
                    "refundId": exc.refund_id,
                    "refundAmountInr": round(exc.amount_refunded_paise / 100.0, 2),
                    "previousEscrowStatus": "HELD",
                },
            )
            await self._notify.on_refund(tx)
            await self._session.commit()
            return {
                "success": True,
                "refundId": exc.refund_id,
                "refundAmountInr": round(exc.amount_refunded_paise / 100.0, 2),
            }
        except ValueError as exc:
            msg = str(exc)
            msg_lower = msg.lower()
            # Distinguish "already refunded" (409 conflict) from other errors.
            if "already" in msg_lower and ("fully" in msg_lower or "nothing left" in msg_lower):
                raise AppException(msg, status_code=409) from exc
            # "cannot refund payment in" means payment is in wrong state.
            if "cannot refund payment in" in msg_lower:
                raise AppException(msg, status_code=409) from exc
            # Razorpay TEST mode rejects certain refund amounts.
            if "invalid request" in msg_lower:
                environment = rzp.get_environment() or "UNKNOWN"
                payment_id = tx.razorpay_payment_id or "unknown"
                hint = (
                    f"Razorpay {environment} mode rejected the refund for payment {payment_id}. "
                    f"In TEST mode, some payment methods have refund limitations. "
                    f"Refund manually via the Razorpay Dashboard, "
                    f"then click 'Sync Refund Status' to synchronize."
                ) if environment == "TEST" else (
                    f"Razorpay rejected the refund request for payment {payment_id}. "
                    "Check the payment status and refundable amount."
                )
                raise AppException(
                    f"{msg}\n\n{hint}",
                    status_code=400,
                ) from exc
            raise AppException(msg, status_code=400) from exc
        except AppException:
            raise
        except Exception as exc:
            raise AppException(
                f"Razorpay refund failed: {exc}",
                status_code=502,
            ) from exc

        # --- Razorpay refund succeeded — save the REAL refund ID ---
        refund_id = refund.get("id")
        if not refund_id or not str(refund_id).startswith("rfnd_"):
            raise AppException(
                "Razorpay returned an unexpected refund response.",
                status_code=502,
            )

        refund_amount_inr = round(float(refund.get("amount", 0)) / 100.0, 2)

        now = datetime.now(timezone.utc)
        tx.razorpay_refund_id = refund_id
        tx.escrow_status = MarketplaceEscrowStatus.REFUNDED
        tx.transfer_status = MarketplaceTransferStatus.REFUNDED
        tx.refund_completed_at = now
        await self._repo.save(tx)
        await self._restore_listing(tx.domain_listing_id, refunded=True)

        await self._events.log(
            tx.id,
            TransferEventType.REFUNDED,
            actor_user_id=admin.id,
            actor_role="ADMIN",
            payload={
                "note": note,
                "refundId": refund_id,
                "refundAmountInr": refund_amount_inr,
                "previousEscrowStatus": "HELD",
            },
        )
        await self._notify.on_refund(tx)

        # --- Create Track Record for the refund ---
        try:
            from app.service.platform.track_record_service import (
                TrackRecordService,
                TrackRecordCategory,
                PaymentStatus,
                OverallStatus,
                FulfillmentStatus,
            )
            track = TrackRecordService(self._session)
            buyer_name = ""
            buyer_email = ""
            if tx.buyer:
                buyer_name = f"{tx.buyer.firstname or ''} {tx.buyer.lastname or ''}".strip()
                buyer_email = tx.buyer.email or ""
            await track.record_paid_attempt(
                internal_order_id=f"TRK-MKT-REFUND-{tx.id}",
                category=TrackRecordCategory.DOMAIN_MARKETPLACE,
                provider_subcategory="Razorpay",
                item_name=tx.domain_fqdn or str(tx.id),
                item_id=str(tx.domain_listing_id),
                buyer_name=buyer_name,
                buyer_email=buyer_email,
                buyer_user_id=tx.buyer_id,
                amount_charged=refund_amount_inr,
                currency="INR",
                subtotal_ex_gst=float(tx.gross_amount_inr or 0),
                gst_amount=round(float(tx.gross_amount_inr or 0) * 0.18, 2),
                payment_status=PaymentStatus.REFUNDED,
                razorpay_order_id=tx.razorpay_order_id,
                razorpay_payment_id=tx.razorpay_payment_id,
                razorpay_refund_id=refund_id,
                fulfillment_status=FulfillmentStatus.CANCELLED,
                overall_status=OverallStatus.REFUNDED,
                notes=(
                    f"Marketplace refund for {tx.domain_fqdn}. "
                    f"Admin-initiated. "
                    f"Listing price: INR {tx.gross_amount_inr}, "
                    f"GST: INR {round(float(tx.gross_amount_inr or 0) * 0.18, 2)}, "
                    f"Buyer paid: INR {self._compute_gst_inclusive_amount(tx)}, "
                    f"Refunded: INR {refund_amount_inr}."
                ),
            )
        except Exception:
            logger.exception("refund.track_record.failed tx=%s", tx.id)

        await self._session.commit()
        return {
            "success": True,
            "refundId": refund_id,
            "refundAmountInr": refund_amount_inr,
        }

    async def sync_refund_from_razorpay(
        self,
        tx_id: uuid.UUID,
        *,
        admin: AppUser,
    ) -> dict:
        """Check Razorpay for an existing refund and sync the DB if found.

        This does NOT create a new refund.  It only reads Razorpay's state
        and synchronizes CoBrother's database to match.
        """
        tx = await self._repo.get_by_id_for_update(tx_id)
        if tx is None:
            raise AppException("Transfer transaction not found.", status_code=404)

        if not tx.razorpay_payment_id:
            raise AppException(
                "No Razorpay payment ID on this transaction.",
                status_code=400,
            )

        # Already synced with a REAL Razorpay refund ID.
        if (
            tx.escrow_status == MarketplaceEscrowStatus.REFUNDED
            and tx.razorpay_refund_id
            and str(tx.razorpay_refund_id).startswith("rfnd_")
        ):
            return {
                "success": True,
                "alreadySynced": True,
                "refundId": tx.razorpay_refund_id,
                "refundAmountInr": self._compute_gst_inclusive_amount(tx),
                "message": "Refund already synchronized.",
            }

        # If escrow is already REFUNDED but refund ID is missing or fake,
        # we need to sync the real Razorpay refund ID.

        # --- Fetch actual payment from Razorpay ---
        try:
            payment = rzp.fetch_payment(tx.razorpay_payment_id)
        except Exception as exc:
            raise AppException(
                f"Could not fetch payment from Razorpay: {exc}",
                status_code=502,
            ) from exc

        payment_status = str(payment.get("status") or "").lower()
        captured_amount = int(payment.get("amount") or 0)
        amount_refunded = int(payment.get("amount_refunded") or 0)

        # --- Fetch existing refunds from Razorpay ---
        from app.integrations.razorpay.client import _fetch_existing_refund_id
        from app.integrations.razorpay import client as rzp_client
        client_obj = rzp_client.razorpay.Client(
            auth=(rzp._key_id(), rzp._key_secret())
        )
        refund_id = _fetch_existing_refund_id(client_obj, tx.razorpay_payment_id)

        # --- Determine if a FULL refund exists on Razorpay ---
        # Partial refunds should NOT mark the transaction as REFUNDED.
        is_fully_refunded = (
            payment_status == "refunded"
            or (
                captured_amount > 0
                and amount_refunded >= captured_amount
                and refund_id is not None
            )
        )
        has_refund = is_fully_refunded

        if not has_refund:
            # Build a clear message depending on whether there are partial refunds.
            if amount_refunded > 0:
                msg = (
                    f"Partial refund detected on Razorpay: INR {round(amount_refunded / 100.0, 2)} "
                    f"of INR {round(captured_amount / 100.0, 2)} refunded. "
                    f"Full refund required before syncing. "
                    f"Payment status: {payment_status}."
                )
            else:
                msg = (
                    "No refund has been recorded by Razorpay yet. "
                    f"Payment status: {payment_status}. "
                    f"Amount refunded: INR {round(amount_refunded / 100.0, 2)}."
                )
            return {
                "success": True,
                "refundFound": False,
                "paymentStatus": payment_status,
                "capturedAmountInr": round(captured_amount / 100.0, 2),
                "amountRefundedInr": round(amount_refunded / 100.0, 2),
                "message": msg,
            }

        # --- Real full refund found on Razorpay — sync our DB ---
        refund_amount_inr = round(amount_refunded / 100.0, 2)
        now = datetime.now(timezone.utc)
        previous_escrow = tx.escrow_status.value if tx.escrow_status else None
        previous_transfer = tx.transfer_status.value if tx.transfer_status else None

        tx.razorpay_refund_id = refund_id
        tx.escrow_status = MarketplaceEscrowStatus.REFUNDED
        tx.transfer_status = MarketplaceTransferStatus.REFUNDED
        tx.refund_completed_at = now
        await self._repo.save(tx)
        await self._restore_listing(tx.domain_listing_id, refunded=True)

        await self._events.log(
            tx.id,
            TransferEventType.REFUNDED,
            actor_user_id=admin.id,
            actor_role="ADMIN",
            payload={
                "note": "Refund synchronized from Razorpay Dashboard.",
                "refundId": refund_id,
                "refundAmountInr": refund_amount_inr,
                "previousEscrowStatus": previous_escrow,
                "previousTransferStatus": previous_transfer,
            },
        )
        await self._notify.on_refund(tx)

        # --- Create Track Record ---
        try:
            from app.service.platform.track_record_service import (
                TrackRecordService,
                TrackRecordCategory,
                PaymentStatus,
                OverallStatus,
                FulfillmentStatus,
            )
            track = TrackRecordService(self._session)
            buyer_name = ""
            buyer_email = ""
            if tx.buyer:
                buyer_name = f"{tx.buyer.firstname or ''} {tx.buyer.lastname or ''}".strip()
                buyer_email = tx.buyer.email or ""
            await track.record_paid_attempt(
                internal_order_id=f"TRK-MKT-REFUND-{tx.id}",
                category=TrackRecordCategory.DOMAIN_MARKETPLACE,
                provider_subcategory="Razorpay",
                item_name=tx.domain_fqdn or str(tx.id),
                item_id=str(tx.domain_listing_id),
                buyer_name=buyer_name,
                buyer_email=buyer_email,
                buyer_user_id=tx.buyer_id,
                amount_charged=refund_amount_inr,
                currency="INR",
                subtotal_ex_gst=float(tx.gross_amount_inr or 0),
                gst_amount=round(float(tx.gross_amount_inr or 0) * 0.18, 2),
                payment_status=PaymentStatus.REFUNDED,
                razorpay_order_id=tx.razorpay_order_id,
                razorpay_payment_id=tx.razorpay_payment_id,
                razorpay_refund_id=refund_id,
                fulfillment_status=FulfillmentStatus.CANCELLED,
                overall_status=OverallStatus.REFUNDED,
                notes=(
                    f"Marketplace refund for {tx.domain_fqdn}. "
                    f"Synchronized from Razorpay Dashboard. "
                    f"Listing price: INR {tx.gross_amount_inr}, "
                    f"Buyer paid: INR {self._compute_gst_inclusive_amount(tx)}, "
                    f"Refunded: INR {refund_amount_inr}."
                ),
            )
        except Exception:
            logger.exception("sync_refund.track_record.failed tx=%s", tx.id)

        await self._session.commit()

        return {
            "success": True,
            "refundFound": True,
            "refundId": refund_id,
            "refundAmountInr": refund_amount_inr,
            "paymentId": tx.razorpay_payment_id,
            "message": f"Refund synchronized. Refund ID: {refund_id}",
        }

    async def resolve_admin_review(
        self,
        tx_id: uuid.UUID,
        *,
        admin: AppUser,
        action: Literal["refund", "extend_deadline", "cancel"],
        extension_hours: int | None = None,
    ) -> dict:
        tx = await self._repo.get_by_id_for_update(tx_id)
        if tx is None:
            raise AppException("Transfer transaction not found.", status_code=404)
        if action == "cancel":
            # Cancel is allowed for any non-terminal state.
            terminal = {
                MarketplaceTransferStatus.REFUNDED,
                MarketplaceTransferStatus.CANCELLED,
                MarketplaceTransferStatus.COMPLETED,
                MarketplaceTransferStatus.SELLER_PAID,
                MarketplaceTransferStatus.PAYOUT_APPROVED,
                MarketplaceTransferStatus.PAYOUT_RELEASED,
            }
            if tx.transfer_status in terminal:
                raise AppException(
                    f"Cannot cancel transaction in terminal state '{tx.transfer_status.value}'.",
                    status_code=409,
                )
        elif tx.transfer_status != MarketplaceTransferStatus.ADMIN_REVIEW_REQUIRED:
            raise AppException("Transaction is not awaiting admin review.", status_code=400)

        if action == "refund":
            # Do NOT auto-refund via Razorpay API.
            # Open Razorpay Dashboard instead and let admin refund manually.
            if tx.razorpay_payment_id:
                from app.integrations.razorpay import client as rzp_local
                environment = rzp_local.get_environment() or "TEST"
                base_url = "https://dashboard.razorpay.com"
                dashboard_url = f"{base_url}/app/payments/{tx.razorpay_payment_id}"
                await self._session.commit()
                return {
                    "success": True,
                    "action": "open_razorpay",
                    "dashboardUrl": dashboard_url,
                    "paymentId": tx.razorpay_payment_id,
                    "environment": environment,
                    "message": "Open the Razorpay Dashboard to manually process the refund.",
                }
            raise AppException(
                "No Razorpay payment ID for this transaction.", status_code=400,
            )

        if action == "extend_deadline":
            hours = extension_hours or settings.DOMAIN_TRANSFER_SELLER_DEADLINE_HOURS
            now = datetime.now(timezone.utc)
            tx.transfer_status = MarketplaceTransferStatus.AWAITING_AUTH_CODE
            tx.seller_deadline_at = now + timedelta(hours=hours)
            tx.admin_review_required_at = None
            tx.admin_review_reason = None
            tx.email_seller_reminder_12h_sent = False
            tx.email_seller_reminder_6h_sent = False
            tx.email_admin_review_sent = False
            await self._repo.save(tx)
            await self._events.log(
                tx.id,
                TransferEventType.ADMIN_REVIEW,
                actor_user_id=admin.id,
                actor_role="ADMIN",
                payload={"action": "extend_deadline", "hours": hours},
            )
            await self._session.commit()
            return {"success": True, "action": "extend_deadline"}

        if action == "cancel":
            tx.transfer_status = MarketplaceTransferStatus.CANCELLED
            await self._repo.save(tx)
            await self._restore_listing(tx.domain_listing_id, refunded=True)
            await self._events.log(
                tx.id,
                TransferEventType.ADMIN_REVIEW,
                actor_user_id=admin.id,
                actor_role="ADMIN",
                payload={"action": "cancel", "note": "Transaction cancelled by admin."},
            )
            await self._session.commit()
            # If payment was made, admin must refund manually via Razorpay Dashboard.
            dashboard_url = None
            environment = None
            if tx.razorpay_payment_id:
                from app.integrations.razorpay import client as rzp_local
                environment = rzp_local.get_environment() or "TEST"
                dashboard_url = f"https://dashboard.razorpay.com/app/payments/{tx.razorpay_payment_id}"
            return {
                "success": True,
                "action": "cancel",
                "message": "Transaction cancelled. Refund manually through Razorpay Dashboard if needed.",
                "dashboardUrl": dashboard_url,
                "paymentId": tx.razorpay_payment_id,
                "environment": environment,
            }

        raise AppException("Invalid action.", status_code=400)

    async def force_complete(
        self,
        tx_id: uuid.UUID,
        *,
        admin: AppUser,
        reason: str | None = None,
    ) -> dict:
        tx = await self._repo.get_by_id_for_update(tx_id)
        if tx is None:
            raise AppException("Transfer transaction not found.", status_code=404)
        if tx.transfer_status in (
            MarketplaceTransferStatus.SELLER_PAID,
            MarketplaceTransferStatus.PAYOUT_RELEASED,
            MarketplaceTransferStatus.COMPLETED,
            MarketplaceTransferStatus.REFUNDED,
            MarketplaceTransferStatus.CANCELLED,
        ):
            raise AppException("Transaction is already closed.", status_code=409)
        if not reason or not reason.strip():
            raise AppException(
                "A reason is required to force-complete a transfer.",
                status_code=400,
            )
        previous_status = tx.transfer_status.value
        now = datetime.now(timezone.utc)
        tx.transfer_confirmed_at = now
        tx.transfer_verified_at = now
        tx.transfer_verified_by = TransferVerifiedBy.ADMIN
        tx.transfer_status = MarketplaceTransferStatus.PAYOUT_PENDING
        await self._repo.save(tx)
        await self._events.log(
            tx.id,
            TransferEventType.TRANSFER_CONFIRMED,
            actor_user_id=admin.id,
            actor_role="ADMIN",
            payload={
                "forced": True,
                "reason": reason.strip(),
                "previousStatus": previous_status,
            },
        )
        await self._events.log(
            tx.id,
            TransferEventType.PAYOUT_PENDING,
            actor_role="SYSTEM",
            payload={
                "reason": "Transfer completed by admin verification.",
                "adminReason": reason.strip(),
            },
        )
        await self._session.commit()
        return {"success": True}
