"""Venture deal escrow and timeline workflow."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.coventure.partner_entity import CoVenture
from app.entity.coventure.venture_acquisition_application_entity import (
    VentureAcquisitionApplication,
)
from app.entity.coventure.venture_deal_event_entity import VentureDealEvent
from app.entity.coventure.venture_deal_transaction_entity import VentureDealTransaction
from app.entity.coventure.venture_entity import Venture
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.integrations.razorpay import client as rzp
from app.repository.coventure_repository import CoVentureRepository
from app.repository.seller_payout_profile_repository import SellerPayoutProfileRepository
from app.repository.venture_deal_repository import VentureDealRepository
from app.repository.venture_repository import VentureRepository
from app.service.platform.listing_pricing_service import ListingPricingService
from app.service.notification.notification_service import NotificationService
from app.service.payout.seller_payout_profile_service import SellerPayoutProfileService
from app.core.database import SessionLocal
from app.repository.user_repository import UserRepository
from app.utils.transfer_enums import MarketplaceEscrowStatus
from app.utils.equity_percent import normalize_equity_percent
from app.utils.money import round_inr
from app.utils.venture_enums import (
    CoVentureStatus,
    VentureDealEventType,
    VentureDealKind,
    VentureDealStatus,
    VentureListingStatus,
)

logger = logging.getLogger(__name__)

COBROTHER_CONTACT_EMAIL = "support@hubregistrar.com"


def coventure_gross_amount_inr(venture: Venture | None) -> float:
    """Listed partnership fee from brand deal_value (whole INR rupees)."""
    if venture is None:
        return 0.0
    brand = venture.brand_details
    if brand is None or brand.deal_value is None:
        return 0.0
    value = float(brand.deal_value)
    return value if value > 0 else 0.0

DEAL_EVENT_LABELS: dict[VentureDealEventType, str] = {
    VentureDealEventType.CREATED: "Deal created",
    VentureDealEventType.PAYMENT_INITIATED: "Payment initiated",
    VentureDealEventType.PAYMENT_RECEIVED: "Payment received",
    VentureDealEventType.ESCROW_RELEASED: "Escrow released",
    VentureDealEventType.DEAL_COMPLETED: "Deal completed",
    VentureDealEventType.DEAL_CANCELLED: "Deal cancelled",
    VentureDealEventType.ADMIN_NOTE: "Admin update",
}


def _user_contact_summary(user: AppUser | None) -> dict[str, Any] | None:
    if user is None:
        return None
    name = f"{user.firstname or ''} {user.lastname or ''}".strip() or None
    return {
        "id": str(user.id),
        "name": name,
        "firstname": user.firstname,
        "lastname": user.lastname,
        "email": user.email,
        "phoneNumber": user.phone_number,
    }


def _serialize_deal(txn: VentureDealTransaction) -> dict[str, Any]:
    venture = txn.venture
    brand = venture.brand_details if venture else None
    events = list(txn.events) if txn.events is not None else []
    co_app = txn.co_venture_application
    partner_name = co_app.full_name if co_app else None
    buyer = _user_contact_summary(txn.buyer)
    if buyer and partner_name and txn.deal_kind == VentureDealKind.CO_VENTURE:
        buyer = {**buyer, "name": partner_name, "phoneNumber": co_app.phone or buyer.get("phoneNumber")}
    payload = {
        "id": str(txn.id),
        "ventureId": str(txn.venture_id),
        "buyerId": str(txn.buyer_id),
        "sellerId": str(txn.seller_id),
        "pitchId": str(txn.pitch_id) if txn.pitch_id else None,
        "coVentureApplicationId": (
            str(txn.co_venture_application_id) if txn.co_venture_application_id else None
        ),
        "dealKind": txn.deal_kind.value,
        "dealStatus": txn.deal_status.value,
        "escrowStatus": txn.escrow_status.value,
        "grossAmountInr": txn.gross_amount_inr,
        "platformFeeInr": txn.platform_fee_inr,
        "sellerPayoutInr": txn.seller_payout_inr,
        "equityPercent": normalize_equity_percent(txn.equity_percent),
        "razorpayOrderId": txn.razorpay_order_id,
        "razorpayPaymentId": txn.razorpay_payment_id,
        "createdAt": txn.created_at.isoformat() if txn.created_at else None,
        "finalizedAt": txn.finalized_at.isoformat() if txn.finalized_at else None,
        "completedAt": txn.completed_at.isoformat() if txn.completed_at else None,
        "cobrotherContactEmail": COBROTHER_CONTACT_EMAIL,
        "partnerName": partner_name,
        "buyer": buyer,
        "seller": _user_contact_summary(txn.seller),
        "venture": {
            "brandName": brand.brand_name if brand else None,
            "equityPercentOffered": normalize_equity_percent(
                venture.equity_percent_offered if venture else None
            ),
            "dealValue": round_inr(brand.deal_value) if brand and brand.deal_value else None,
        } if venture else None,
        "timeline": [
            {
                "eventType": e.event_type.value,
                "label": DEAL_EVENT_LABELS.get(e.event_type, e.event_type.value),
                "message": e.message,
                "createdAt": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }
    return payload


def _notify_sync(
    user_id: uuid.UUID,
    *,
    notification_type: NotificationType,
    title: str,
    message: str,
    target_url: str | None = None,
) -> None:
    db = SessionLocal()
    try:
        user = UserRepository.find_by_id(db, user_id)
        if user is None:
            return
        NotificationService.notify(
            db,
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
            target_url=target_url,
        )
        db.commit()
    except Exception:
        logger.exception("Failed to send deal notification")
        db.rollback()
    finally:
        db.close()


class VentureDealService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = VentureDealRepository(session)
        self._ventures = VentureRepository(session)
        self._co_repo = CoVentureRepository(session)
        self._pricing = ListingPricingService(session)
        self._profiles = SellerPayoutProfileRepository(session)

    async def _seller_payout_fields(
        self,
        txn: VentureDealTransaction,
        *,
        include_profile: bool = False,
    ) -> dict[str, Any]:
        profile = await self._profiles.get_by_user_id(txn.seller_id)
        complete = SellerPayoutProfileService.is_complete(profile)
        fields: dict[str, Any] = {
            "sellerPayoutProfileComplete": complete,
            "sellerPayoutProfileReady": complete,
            "sellerPayoutProfileMissing": profile is None,
        }
        if include_profile and profile is not None:
            fields["sellerPayoutProfile"] = SellerPayoutProfileService(
                self._session
            )._serialize(profile)
        return fields

    async def _sync_coventure_deal_pricing(self, txn: VentureDealTransaction) -> bool:
        """Align co-venture deal amounts with the listing fee (legacy ₹0 deals)."""
        if txn.deal_kind != VentureDealKind.CO_VENTURE:
            return False
        if txn.deal_status in (
            VentureDealStatus.COMPLETED,
            VentureDealStatus.CANCELLED,
            VentureDealStatus.REFUNDED,
            VentureDealStatus.PAYMENT_HELD,
        ):
            return False

        listed_gross = coventure_gross_amount_inr(txn.venture)
        if listed_gross <= 0:
            return False

        changed = False
        if float(txn.gross_amount_inr or 0) != listed_gross:
            commission_pct = await self._pricing.acquisition_commission_percent()
            platform_fee = float(round_inr(listed_gross * float(commission_pct) / 100.0))
            txn.gross_amount_inr = listed_gross
            txn.platform_fee_inr = platform_fee
            txn.seller_payout_inr = float(round_inr(listed_gross) - round_inr(platform_fee))
            changed = True

        if txn.deal_status == VentureDealStatus.IN_PROGRESS:
            txn.deal_status = VentureDealStatus.PENDING_ADMIN_APPROVAL
            await self._add_event(
                txn,
                VentureDealEventType.ADMIN_NOTE,
                message="Partnership fee synced from listing; awaiting admin approval before payment.",
            )
            changed = True

        if changed:
            await self._repo.save(txn)
            await self._session.commit()
        return changed

    async def sync_coventure_deals_for_venture(self, venture: Venture) -> None:
        """After listing fee is updated, upgrade open co-venture deals."""
        from sqlalchemy import select

        open_statuses = (
            VentureDealStatus.IN_PROGRESS,
            VentureDealStatus.PENDING_ADMIN_APPROVAL,
        )
        stmt = (
            select(VentureDealTransaction)
            .where(
                VentureDealTransaction.venture_id == venture.id,
                VentureDealTransaction.deal_kind == VentureDealKind.CO_VENTURE,
                VentureDealTransaction.deal_status.in_(open_statuses),
            )
        )
        result = await self._session.execute(stmt)
        for txn in result.scalars().all():
            txn.venture = venture
            await self._sync_coventure_deal_pricing(txn)

    async def _backfill_missing_coventure_deals(self, user: AppUser) -> None:
        """Create deal rows for partnerships finalized before deal tracking existed."""
        selected = await self._co_repo.list_selected_for_parties(user.id)
        changed = False
        for application in selected:
            if application.venture is None:
                continue
            existing = await self._repo.get_by_co_venture_application(application.id)
            if existing is not None:
                continue
            open_deal = await self._repo.get_open_for_venture_and_buyer(
                application.venture_id,
                application.applicant_user_id,
            )
            if open_deal is not None:
                continue
            await self.create_from_coventure(
                venture=application.venture,
                application=application,
                gross_amount_inr=coventure_gross_amount_inr(application.venture),
            )
            changed = True
        if changed:
            await self._session.commit()

    async def _add_event(
        self,
        txn: VentureDealTransaction,
        event_type: VentureDealEventType,
        *,
        actor: AppUser | None = None,
        message: str | None = None,
    ) -> None:
        await self._repo.add_event(
            VentureDealEvent(
                transaction_id=txn.id,
                event_type=event_type,
                actor_user_id=actor.id if actor else None,
                message=message,
            )
        )

    async def buy_full_acquisition(
        self,
        venture_id: uuid.UUID,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        raise AppException("Direct buy is no longer available", status_code=410)

    async def create_from_pitch(
        self,
        *,
        venture: Venture,
        pitch: VentureAcquisitionApplication,
    ) -> dict[str, Any]:
        gross = float(pitch.offer_amount or 0)
        if gross <= 0:
            raise AppException("Pitch must include a valid offer amount.", status_code=400)

        commission_pct = venture.commission_percent_applied
        if commission_pct is None:
            commission_pct = await self._pricing.acquisition_commission_percent()
        platform_fee = float(round_inr(gross * float(commission_pct) / 100.0))
        seller_payout = float(round_inr(gross) - round_inr(platform_fee))
        now = datetime.now(timezone.utc)

        txn = VentureDealTransaction(
            venture_id=venture.id,
            buyer_id=pitch.buyer_user_id,
            seller_id=venture.listed_by_user_id,
            pitch_id=pitch.id,
            deal_kind=VentureDealKind.VENTURE_SALE,
            deal_status=VentureDealStatus.PENDING_ADMIN_APPROVAL,
            escrow_status=MarketplaceEscrowStatus.HELD,
            gross_amount_inr=gross,
            platform_fee_inr=platform_fee,
            seller_payout_inr=seller_payout,
            equity_percent=normalize_equity_percent(pitch.equity_percent_sought),
            finalized_at=now,
        )
        txn = await self._repo.create(txn)
        await self._add_event(
            txn,
            VentureDealEventType.CREATED,
            message="Deal created from selected pitch.",
        )
        await self._session.flush()
        reloaded = await self._repo.get_by_id(txn.id)
        return _serialize_deal(reloaded or txn)

    async def create_from_coventure(
        self,
        *,
        venture: Venture,
        application: CoVenture,
        gross_amount_inr: float | None = None,
    ) -> dict[str, Any]:
        """Create a co-venture deal after partner selection.

        When the listing has a partnership fee (deal_value), the deal follows the
        same admin-approval → payment flow as venture sales. Free partnerships
        skip payment and go straight to in-progress assistance.
        """
        commission_pct = await self._pricing.acquisition_commission_percent()
        gross = float(gross_amount_inr if gross_amount_inr is not None else coventure_gross_amount_inr(venture))
        platform_fee = float(round_inr(gross * float(commission_pct) / 100.0)) if gross > 0 else 0.0
        seller_payout = float(round_inr(gross) - round_inr(platform_fee)) if gross > 0 else 0.0
        now = datetime.now(timezone.utc)

        txn = VentureDealTransaction(
            venture_id=venture.id,
            buyer_id=application.applicant_user_id,
            seller_id=venture.listed_by_user_id,
            co_venture_application_id=application.id,
            deal_kind=VentureDealKind.CO_VENTURE,
            deal_status=(
                VentureDealStatus.PENDING_ADMIN_APPROVAL
                if gross > 0
                else VentureDealStatus.IN_PROGRESS
            ),
            escrow_status=MarketplaceEscrowStatus.HELD,
            gross_amount_inr=gross,
            platform_fee_inr=platform_fee,
            seller_payout_inr=seller_payout,
            finalized_at=now,
        )
        txn = await self._repo.create(txn)
        await self._add_event(
            txn,
            VentureDealEventType.CREATED,
            message=(
                "Co-venture partnership deal created. Awaiting admin approval before payment."
                if gross > 0
                else "Co-venture partnership deal created."
            ),
        )
        await self._session.flush()
        reloaded = await self._repo.get_by_id(txn.id)
        return _serialize_deal(reloaded or txn)

    async def create_payment_order(
        self,
        deal_id: uuid.UUID,
        *,
        buyer: AppUser,
        redeem_points: bool = False,
    ) -> dict[str, Any]:
        if not rzp.is_configured():
            raise AppException("Payment gateway is not configured.", status_code=503)

        txn = await self._repo.get_by_id(deal_id)
        if txn is None:
            raise AppException("Deal not found.", status_code=404)
        if txn.buyer_id != buyer.id:
            raise AppException("Not authorized.", status_code=403)
        if txn.deal_status != VentureDealStatus.PENDING_PAYMENT:
            raise AppException("Deal is not awaiting payment.", status_code=400)
        if txn.gross_amount_inr <= 0:
            txn.deal_status = VentureDealStatus.IN_PROGRESS
            await self._repo.save(txn)
            await self._add_event(
                txn,
                VentureDealEventType.DEAL_COMPLETED,
                actor=buyer,
                message="No payment required for this deal.",
            )
            await self._session.commit()
            return {"contactOnly": True, "dealId": str(deal_id)}

        amount_to_charge = txn.gross_amount_inr
        points_redeemed = 0
        if amount_to_charge > 0:
            from app.service.user.edge_points_service import EdgePointsService
            amount_to_charge, points_redeemed = await EdgePointsService.calculate_redemption(
                self._session, buyer, amount_to_charge, redeem_points
            )

        receipt = f"vd_{str(deal_id).replace('-', '')[:20]}"
        try:
            rzp_order = rzp.create_order(
                amount_inr=amount_to_charge,
                receipt=receipt,
                notes={"ventureDealId": str(deal_id), "buyerId": str(buyer.id)},
            )
            if points_redeemed > 0:
                from app.service.user.edge_points_service import EdgePointsService
                await EdgePointsService.create_pending_redemption(
                    self._session, buyer.id, rzp_order["id"], points_redeemed
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("venture deal create_order failed deal=%s", deal_id)
            raise AppException(
                "Could not create payment order. Please try again.",
                status_code=502,
            ) from exc

        txn.razorpay_order_id = rzp_order["id"]
        await self._repo.save(txn)
        await self._add_event(
            txn,
            VentureDealEventType.PAYMENT_INITIATED,
            actor=buyer,
            message="Payment order created.",
        )
        await self._session.commit()

        return {
            "orderId": rzp_order["id"],
            "amount": txn.gross_amount_inr,
            "currency": "INR",
            "dealId": str(deal_id),
            "keyId": rzp.get_key_id(),
        }

    async def verify_payment(
        self,
        deal_id: uuid.UUID,
        *,
        buyer: AppUser,
        razorpay_payment_id: str,
        razorpay_order_id: str,
        razorpay_signature: str,
    ) -> dict[str, Any]:
        existing_payment = await self._repo.get_by_razorpay_payment_id(razorpay_payment_id)
        if existing_payment is not None:
            if existing_payment.id != deal_id:
                raise AppException(
                    "This payment is already linked to another deal.",
                    status_code=409,
                )
            if existing_payment.buyer_id != buyer.id:
                raise AppException("Not authorized.", status_code=403)
            return _serialize_deal(existing_payment)

        txn = await self._repo.get_by_id_for_update(deal_id)
        if txn is None:
            raise AppException("Deal not found.", status_code=404)
        if txn.buyer_id != buyer.id:
            raise AppException("Not authorized.", status_code=403)
        if txn.deal_status == VentureDealStatus.PAYMENT_HELD:
            return _serialize_deal(txn)
        if txn.deal_status != VentureDealStatus.PENDING_PAYMENT:
            raise AppException("Deal is not awaiting payment.", status_code=400)
        if txn.razorpay_order_id and txn.razorpay_order_id != razorpay_order_id:
            raise AppException(
                "Payment order does not match this deal.",
                status_code=400,
            )

        if not rzp.verify_payment_signature(
            razorpay_order_id, razorpay_payment_id, razorpay_signature,
        ):
            from app.service.user.edge_points_service import EdgePointsService
            await EdgePointsService.cancel_redemption(self._session, razorpay_order_id)
            raise AppException("Payment verification failed.", status_code=400)

        txn.razorpay_payment_id = razorpay_payment_id
        txn.razorpay_order_id = razorpay_order_id
        txn.deal_status = VentureDealStatus.PAYMENT_HELD
        txn.escrow_status = MarketplaceEscrowStatus.HELD
        await self._repo.save(txn)
        await self._add_event(
            txn,
            VentureDealEventType.PAYMENT_RECEIVED,
            actor=buyer,
            message="Payment received and held in escrow.",
        )
        from app.service.user.edge_points_service import EdgePointsService
        await EdgePointsService.confirm_redemption(self._session, razorpay_order_id)

        if txn.venture and txn.deal_kind == VentureDealKind.VENTURE_SALE:
            txn.venture.purchased_by_user_id = buyer.id

        await self._session.commit()

        deal_url = f"/ventures/deals/{deal_id}"
        _notify_sync(
            txn.seller_id,
            notification_type=NotificationType.VENTURE_DEAL_PAYMENT_RECEIVED,
            title="Payment Received",
            message="Buyer payment is held in escrow. HubRegistrar will assist with next steps.",
            target_url=deal_url,
        )
        _notify_sync(
            buyer.id,
            notification_type=NotificationType.VENTURE_DEAL_PAYMENT_RECEIVED,
            title="Payment Confirmed",
            message="Your payment was received. HubRegistrar will contact you shortly.",
            target_url=deal_url,
        )

        reloaded = await self._repo.get_by_id(deal_id)
        return _serialize_deal(reloaded or txn)

    async def admin_release_escrow(
        self,
        deal_id: uuid.UUID,
        *,
        admin: AppUser,
    ) -> dict[str, Any]:
        txn = await self._repo.get_by_id_for_update(deal_id)
        if txn is None:
            raise AppException("Deal not found.", status_code=404)
        if txn.deal_status != VentureDealStatus.PAYMENT_HELD:
            raise AppException(
                "Deal is not awaiting escrow release.",
                status_code=400,
            )
        if txn.escrow_status != MarketplaceEscrowStatus.HELD:
            raise AppException("Escrow is not in a held state.", status_code=400)
        if txn.gross_amount_inr > 0 and not txn.razorpay_payment_id:
            raise AppException(
                "Cannot release escrow without a recorded payment.",
                status_code=400,
            )

        if txn.seller_payout_inr > 0:
            profile = await self._profiles.get_by_user_id(txn.seller_id)
            if not SellerPayoutProfileService.is_complete(profile):
                raise AppException(
                    "Cannot release escrow. Seller payout profile is incomplete.",
                    status_code=400,
                )

        now = datetime.now(timezone.utc)
        txn.deal_status = VentureDealStatus.COMPLETED
        txn.escrow_status = MarketplaceEscrowStatus.RELEASED
        txn.completed_at = now
        venture = txn.venture
        if venture is not None and txn.deal_kind == VentureDealKind.VENTURE_SALE:
            venture.venture_listing_status = VentureListingStatus.COMPLETED
            venture.purchased_by_user_id = txn.buyer_id
            await self._ventures.save(venture)
        await self._repo.save(txn)
        await self._add_event(
            txn,
            VentureDealEventType.ESCROW_RELEASED,
            actor=admin,
            message="Escrow released by admin.",
        )
        await self._add_event(
            txn,
            VentureDealEventType.DEAL_COMPLETED,
            actor=admin,
            message="Deal completed.",
        )
        await self._session.commit()

        _notify_sync(
            txn.seller_id,
            notification_type=NotificationType.VENTURE_DEAL_COMPLETED,
            title="Deal Completed",
            message="Your venture deal has been completed.",
            target_url=f"/ventures/deals/{deal_id}",
        )
        _notify_sync(
            txn.buyer_id,
            notification_type=NotificationType.VENTURE_DEAL_COMPLETED,
            title="Deal Completed",
            message="Your venture deal has been completed.",
            target_url=f"/ventures/deals/{deal_id}",
        )
        reloaded = await self._repo.get_by_id(deal_id)
        return _serialize_deal(reloaded or txn)

    async def admin_approve_deal(
        self,
        deal_id: uuid.UUID,
        *,
        admin: AppUser,
    ) -> dict[str, Any]:
        txn = await self._repo.get_by_id(deal_id)
        if txn is None:
            raise AppException("Deal not found.", status_code=404)
        if txn.deal_status != VentureDealStatus.PENDING_ADMIN_APPROVAL:
            raise AppException("Deal is not awaiting admin approval.", status_code=400)

        txn.deal_status = VentureDealStatus.PENDING_PAYMENT
        await self._repo.save(txn)
        await self._add_event(
            txn,
            VentureDealEventType.ADMIN_NOTE,
            actor=admin,
            message="Deal approved by admin; buyer may proceed to payment.",
        )
        await self._session.commit()

        brand = txn.venture.brand_details if txn.venture else None
        brand_name = brand.brand_name if brand else "Venture"
        deal_url = f"/ventures/deals/{deal_id}"
        _notify_sync(
            txn.buyer_id,
            notification_type=NotificationType.VENTURE_DEAL_FINALIZED,
            title="Deal Approved",
            message=(
                f"Your deal for {brand_name} was approved. "
                "Complete payment to proceed."
            ),
            target_url=deal_url,
        )
        return _serialize_deal(txn)

    async def admin_reject_deal(
        self,
        deal_id: uuid.UUID,
        *,
        admin: AppUser,
        reason: str = "",
    ) -> dict[str, Any]:
        txn = await self._repo.get_by_id(deal_id)
        if txn is None:
            raise AppException("Deal not found.", status_code=404)
        if txn.deal_status != VentureDealStatus.PENDING_ADMIN_APPROVAL:
            raise AppException("Deal is not awaiting admin approval.", status_code=400)

        txn.deal_status = VentureDealStatus.CANCELLED
        await self._repo.save(txn)
        rejection_note = (reason or "").strip() or None
        await self._add_event(
            txn,
            VentureDealEventType.DEAL_CANCELLED,
            actor=admin,
            message=rejection_note or "Deal rejected by admin.",
        )

        venture = txn.venture
        if venture is not None:
            venture.venture_listing_status = VentureListingStatus.ACTIVE
            venture.closed_at = None
            venture.closed_by_user_id = None
            venture.selected_pitch_id = None
            await self._ventures.save(venture)

        await self._session.commit()

        brand = venture.brand_details if venture else None
        brand_name = brand.brand_name if brand else "Venture"
        detail = f" Reason: {rejection_note}" if rejection_note else ""
        _notify_sync(
            txn.buyer_id,
            notification_type=NotificationType.VENTURE_DEAL_FINALIZED,
            title="Deal Not Approved",
            message=f"Your deal for {brand_name} was not approved.{detail}",
            target_url="/ventures/dashboard",
        )
        if txn.seller_id:
            _notify_sync(
                txn.seller_id,
                notification_type=NotificationType.VENTURE_DEAL_FINALIZED,
                title="Deal Rejected",
                message=f"The deal for {brand_name} was rejected by admin.{detail}",
                target_url="/ventures/dashboard",
            )
        return _serialize_deal(txn)

    async def get_deal(self, deal_id: uuid.UUID, viewer: AppUser) -> dict[str, Any]:
        txn = await self._repo.get_by_id(deal_id)
        if txn is None:
            raise AppException("Deal not found.", status_code=404)
        if (
            viewer.role != UserRole.ADMIN
            and viewer.id not in (txn.buyer_id, txn.seller_id)
        ):
            raise AppException("Deal not found.", status_code=404)
        if await self._sync_coventure_deal_pricing(txn):
            txn = await self._repo.get_by_id(deal_id)
            if txn is None:
                raise AppException("Deal not found.", status_code=404)
        payload = _serialize_deal(txn)
        if viewer.id == txn.seller_id or viewer.role == UserRole.ADMIN:
            payload.update(
                await self._seller_payout_fields(
                    txn,
                    include_profile=viewer.role == UserRole.ADMIN,
                )
            )
        return payload

    async def list_my_deals(self, user: AppUser) -> list[dict[str, Any]]:
        await self._backfill_missing_coventure_deals(user)
        rows = await self._repo.list_for_user(user.id)
        result: list[dict[str, Any]] = []
        for row in rows:
            if await self._sync_coventure_deal_pricing(row):
                row = await self._repo.get_by_id(row.id) or row
            payload = _serialize_deal(row)
            if row.seller_id == user.id and row.seller_payout_inr > 0:
                payload.update(await self._seller_payout_fields(row))
            result.append(payload)
        return result

    async def list_all_admin(self) -> list[dict[str, Any]]:
        rows = await self._repo.list_all_admin()
        result: list[dict[str, Any]] = []
        for row in rows:
            if await self._sync_coventure_deal_pricing(row):
                row = await self._repo.get_by_id(row.id) or row
            payload = _serialize_deal(row)
            payload.update(
                await self._seller_payout_fields(row, include_profile=True)
            )
            result.append(payload)
        return result

    async def admin_refund(
        self,
        deal_id: uuid.UUID,
        *,
        admin: AppUser,
        note: str | None = None,
    ) -> dict[str, Any]:
        txn = await self._repo.get_by_id(deal_id)
        if txn is None:
            raise AppException("Deal not found.", status_code=404)
        if txn.deal_status == VentureDealStatus.REFUNDED:
            return _serialize_deal(txn)
        if txn.escrow_status == MarketplaceEscrowStatus.RELEASED:
            raise AppException("Escrow already released; cannot refund.", status_code=400)
        if not txn.razorpay_payment_id:
            raise AppException("No payment to refund.", status_code=400)

        refund = rzp.refund_payment(txn.razorpay_payment_id, txn.gross_amount_inr)
        now = datetime.now(timezone.utc)
        txn.razorpay_refund_id = refund.get("id")
        txn.deal_status = VentureDealStatus.REFUNDED
        txn.escrow_status = MarketplaceEscrowStatus.REFUNDED
        await self._repo.save(txn)
        refund_note = (note or "").strip() or "Payment refunded by admin."
        await self._add_event(
            txn,
            VentureDealEventType.DEAL_CANCELLED,
            actor=admin,
            message=refund_note,
        )

        venture = txn.venture
        if venture is not None and txn.deal_kind == VentureDealKind.VENTURE_SALE:
            venture.venture_listing_status = VentureListingStatus.ACTIVE
            venture.purchased_by_user_id = None
            venture.closed_at = None
            venture.closed_by_user_id = None
            venture.selected_pitch_id = None
            await self._ventures.save(venture)

        await self._session.commit()

        brand = venture.brand_details if venture else None
        brand_name = brand.brand_name if brand else "Venture"
        deal_url = f"/ventures/deals/{deal_id}"
        _notify_sync(
            txn.buyer_id,
            notification_type=NotificationType.VENTURE_DEAL_FINALIZED,
            title="Deal Refunded",
            message=f"Your payment for {brand_name} has been refunded.",
            target_url=deal_url,
        )
        if txn.seller_id:
            _notify_sync(
                txn.seller_id,
                notification_type=NotificationType.VENTURE_DEAL_FINALIZED,
                title="Deal Refunded",
                message=f"The deal for {brand_name} was refunded to the buyer.",
                target_url="/ventures/dashboard",
            )
        reloaded = await self._repo.get_by_id(deal_id)
        payload = _serialize_deal(reloaded or txn)
        payload.update(await self._seller_payout_fields(txn, include_profile=True))
        return payload
