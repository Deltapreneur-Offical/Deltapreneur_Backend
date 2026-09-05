"""Venture pitch workflow (buyer investment proposals)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.exceptions import AppException
from app.utils.equity_percent import normalize_equity_percent
from app.entity.coventure.venture_acquisition_application_entity import (
    VentureAcquisitionApplication,
)
from app.entity.coventure.venture_entity import Venture
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.repository.user_repository import UserRepository
from app.repository.venture_acquisition_repository import VentureAcquisitionRepository
from app.repository.venture_repository import VentureRepository
from app.service.notification.notification_service import NotificationService
from app.service.venture.venture_deal_service import VentureDealService
from app.utils.venture_enums import (
    VentureAcquisitionApplicationSource,
    VentureAcquisitionApplicationStatus,
    VentureDealType,
    VentureListingApprovalStatus,
    VentureListingMode,
    VentureListingStatus,
)

logger = logging.getLogger(__name__)

COBROTHER_CONTACT_EMAIL = "support@deltapreneur.com"


def _serialize_pitch(
    app: VentureAcquisitionApplication,
    *,
    include_buyer_phone: bool = False,
) -> dict[str, Any]:
    venture = app.venture
    brand = venture.brand_details if venture else None
    buyer = app.buyer
    buyer_payload = None
    if buyer:
        buyer_payload = {
            "id": str(buyer.id),
            "firstname": buyer.firstname,
            "lastname": buyer.lastname,
            "email": buyer.email,
        }
        if include_buyer_phone and buyer.phone_number:
            buyer_payload["phoneNumber"] = buyer.phone_number
    return {
        "id": str(app.id),
        "ventureId": str(app.venture_id),
        "buyerUserId": str(app.buyer_user_id),
        "status": app.status.value,
        "source": app.source.value,
        "message": app.message,
        "investmentProposal": app.investment_proposal,
        "additionalNotes": app.additional_notes,
        "offeredAmount": app.offer_amount,
        "requestedEquityPercent": normalize_equity_percent(app.equity_percent_sought),
        "sellerAcceptedAt": (
            app.seller_accepted_at.isoformat() if app.seller_accepted_at else None
        ),
        "createdAt": app.created_at.isoformat() if app.created_at else None,
        "buyer": buyer_payload,
        "venture": {
            "id": str(venture.id),
            "brandName": brand.brand_name if brand else None,
            "dealType": venture.deal_type.value if venture and venture.deal_type else None,
            "listingMode": venture.listing_mode.value if venture else None,
        } if venture else None,
    }


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
        logger.exception("Failed to send pitch notification")
        db.rollback()
    finally:
        db.close()


def _notify_admins_sync(
    *,
    notification_type: NotificationType,
    title: str,
    message: str,
    target_url: str | None = None,
) -> None:
    db = SessionLocal()
    try:
        from app.entity.user.app_user import AppUser as AppUserModel

        admins = db.query(AppUserModel).filter(AppUserModel.role == UserRole.ADMIN).all()
        for admin in admins:
            NotificationService.notify(
                db,
                user=admin,
                notification_type=notification_type,
                title=title,
                message=message,
                target_url=target_url,
            )
        db.commit()
    except Exception:
        logger.exception("Failed to notify admins")
        db.rollback()
    finally:
        db.close()


class VenturePitchService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._pitches = VentureAcquisitionRepository(session)
        self._ventures = VentureRepository(session)
        self._deals = VentureDealService(session)

    async def submit_pitch(
        self,
        venture_id: uuid.UUID,
        *,
        buyer: AppUser,
        offered_amount: float,
        requested_equity_percent: float,
        message: str,
        additional_notes: str | None = None,
        investment_proposal: str | None = None,
    ) -> dict[str, Any]:
        """Submit a venture bid (investment proposal on ownership liquidation listings).

        Bid fields: Bid Amount (INR), Equity Requested (%), Message, Additional Notes.
        Legacy listings with FULL_ACQUISITION still force 100% equity for backward compatibility.
        """
        message_text = (message or investment_proposal or "").strip()
        if offered_amount <= 0:
            raise AppException("Bid amount must be positive.", status_code=400)
        if requested_equity_percent <= 0 or requested_equity_percent > 100:
            raise AppException("Equity percent must be between 0 and 100.", status_code=400)
        if not message_text:
            raise AppException("Message is required.", status_code=400)

        result = await self._session.execute(
            select(Venture).where(Venture.id == venture_id).with_for_update()
        )
        venture = result.scalar_one_or_none()
        if venture is None:
            raise AppException("Venture not found.", status_code=404)
        if venture.listing_mode != VentureListingMode.VENTURE:
            raise AppException("Bids are only accepted on venture sale listings.", status_code=400)
        if venture.listing_approval_status != VentureListingApprovalStatus.APPROVED:
            raise AppException("This venture is not available for bids yet.", status_code=400)
        is_acquisition_offer = venture.deal_type == VentureDealType.FULL_ACQUISITION
        ownership_liquidation = normalize_equity_percent(venture.equity_percent_offered)
        if is_acquisition_offer:
            requested_equity_percent = 100.0
        elif not is_acquisition_offer and ownership_liquidation is None:
            raise AppException("This venture is not available for bids yet.", status_code=400)
        if venture.venture_listing_status != VentureListingStatus.ACTIVE:
            raise AppException("This venture is no longer accepting bids.", status_code=400)
        if venture.listed_by_user_id == buyer.id:
            raise AppException("You cannot bid on your own venture.", status_code=400)

        prior = await self._pitches.get_by_venture_and_buyer(venture_id, buyer.id)
        if prior is not None and prior.status in (
            VentureAcquisitionApplicationStatus.PENDING,
            VentureAcquisitionApplicationStatus.SHORTLISTED,
            VentureAcquisitionApplicationStatus.SELLER_ACCEPTED,
            VentureAcquisitionApplicationStatus.DEAL_SELECTED,
        ):
            raise AppException("You already have an active bid on this venture.", status_code=409)

        application = VentureAcquisitionApplication(
            venture_id=venture_id,
            buyer_user_id=buyer.id,
            status=VentureAcquisitionApplicationStatus.PENDING,
            source=VentureAcquisitionApplicationSource.REGULAR_APPLY,
            message=message_text,
            investment_proposal=message_text,
            additional_notes=(additional_notes or "").strip() or None,
            offer_amount=float(offered_amount),
            equity_percent_sought=normalize_equity_percent(requested_equity_percent),
        )
        application = await self._pitches.create(application)
        await self._session.commit()

        brand_name = venture.brand_details.brand_name if venture.brand_details else "Venture"
        if is_acquisition_offer:
            notif_type = NotificationType.VENTURE_OFFER_SUBMITTED
            title = "New Acquisition Bid"
            owner_msg = f"A buyer submitted an acquisition bid for {brand_name}."
            admin_msg = f"Acquisition bid received for {brand_name}."
        else:
            notif_type = NotificationType.VENTURE_PITCH_SUBMITTED
            title = "New Venture Bid"
            owner_msg = f"A buyer submitted a bid for {brand_name}."
            admin_msg = f"Bid received for {brand_name}."
        if venture.listed_by_user_id:
            _notify_sync(
                venture.listed_by_user_id,
                notification_type=notif_type,
                title=title,
                message=owner_msg,
                target_url="/ventures/dashboard",
            )
        _notify_admins_sync(
            notification_type=notif_type,
            title=title,
            message=admin_msg,
            target_url="/admin",
        )
        return _serialize_pitch(application)

    async def seller_accept(
        self,
        pitch_id: uuid.UUID,
        *,
        seller: AppUser,
    ) -> dict[str, Any]:
        app = await self._pitches.get_by_id(pitch_id)
        if app is None:
            raise AppException("Bid not found.", status_code=404)
        venture = app.venture
        if venture is None or venture.listed_by_user_id != seller.id:
            raise AppException("Not authorized.", status_code=403)
        if app.status not in (
            VentureAcquisitionApplicationStatus.PENDING,
            VentureAcquisitionApplicationStatus.SHORTLISTED,
        ):
            raise AppException("Bid is not pending.", status_code=400)

        now = datetime.now(timezone.utc)
        app.status = VentureAcquisitionApplicationStatus.SELLER_ACCEPTED
        app.seller_accepted_at = now
        await self._pitches.save(app)
        await self._session.commit()

        _notify_sync(
            app.buyer_user_id,
            notification_type=NotificationType.VENTURE_PITCH_ACCEPTED,
            title="Bid Accepted",
            message="Your venture bid was accepted by the seller.",
            target_url="/ventures/dashboard",
        )
        return _serialize_pitch(app)

    async def seller_reject(
        self,
        pitch_id: uuid.UUID,
        *,
        seller: AppUser,
    ) -> dict[str, Any]:
        app = await self._pitches.get_by_id(pitch_id)
        if app is None:
            raise AppException("Bid not found.", status_code=404)
        venture = app.venture
        if venture is None or venture.listed_by_user_id != seller.id:
            raise AppException("Not authorized.", status_code=403)
        if app.status not in (
            VentureAcquisitionApplicationStatus.PENDING,
            VentureAcquisitionApplicationStatus.SHORTLISTED,
            VentureAcquisitionApplicationStatus.SELLER_ACCEPTED,
        ):
            raise AppException("Bid cannot be rejected in its current state.", status_code=400)

        app.status = VentureAcquisitionApplicationStatus.SELLER_REJECTED
        await self._pitches.save(app)
        await self._session.commit()

        _notify_sync(
            app.buyer_user_id,
            notification_type=NotificationType.VENTURE_PITCH_REJECTED,
            title="Bid Not Accepted",
            message="The seller did not accept your venture bid.",
            target_url="/ventures/dashboard",
        )
        return _serialize_pitch(app)

    async def seller_shortlist(
        self,
        pitch_id: uuid.UUID,
        *,
        seller: AppUser,
    ) -> dict[str, Any]:
        app = await self._pitches.get_by_id(pitch_id)
        if app is None:
            raise AppException("Bid not found.", status_code=404)
        venture = app.venture
        if venture is None or venture.listed_by_user_id != seller.id:
            raise AppException("Not authorized.", status_code=403)
        if app.status != VentureAcquisitionApplicationStatus.PENDING:
            raise AppException("Only pending pitches can be shortlisted.", status_code=400)

        app.status = VentureAcquisitionApplicationStatus.SHORTLISTED
        await self._pitches.save(app)
        await self._session.commit()
        return _serialize_pitch(app)

    async def buyer_withdraw(
        self,
        pitch_id: uuid.UUID,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        app = await self._pitches.get_by_id(pitch_id)
        if app is None:
            raise AppException("Bid not found.", status_code=404)
        if app.buyer_user_id != buyer.id:
            raise AppException("Not authorized.", status_code=403)
        if app.status not in (
            VentureAcquisitionApplicationStatus.PENDING,
            VentureAcquisitionApplicationStatus.SHORTLISTED,
        ):
            raise AppException("Only pending pitches can be withdrawn.", status_code=400)

        app.status = VentureAcquisitionApplicationStatus.CANCELLED
        await self._pitches.save(app)
        await self._session.commit()
        return _serialize_pitch(app)

    async def finalize_deal(
        self,
        venture_id: uuid.UUID,
        pitch_id: uuid.UUID,
        *,
        seller: AppUser,
    ) -> dict[str, Any]:
        result = await self._session.execute(
            select(Venture).where(Venture.id == venture_id).with_for_update()
        )
        venture = result.scalar_one_or_none()
        if venture is None:
            raise AppException("Venture not found.", status_code=404)
        if venture.listed_by_user_id != seller.id:
            raise AppException("Not authorized.", status_code=403)
        if venture.listing_approval_status != VentureListingApprovalStatus.APPROVED:
            raise AppException("This venture is not approved for deals yet.", status_code=400)
        if venture.venture_listing_status != VentureListingStatus.ACTIVE:
            raise AppException("Listing is not active.", status_code=400)

        app = await self._pitches.get_by_id(pitch_id)
        if app is None or app.venture_id != venture_id:
            raise AppException("Bid not found.", status_code=404)
        if app.status not in (
            VentureAcquisitionApplicationStatus.PENDING,
            VentureAcquisitionApplicationStatus.SHORTLISTED,
            VentureAcquisitionApplicationStatus.SELLER_ACCEPTED,
        ):
            raise AppException("Pitch cannot be selected for deal.", status_code=400)

        now = datetime.now(timezone.utc)
        app.status = VentureAcquisitionApplicationStatus.DEAL_SELECTED
        app.seller_accepted_at = app.seller_accepted_at or now
        await self._pitches.save(app)

        venture.venture_listing_status = VentureListingStatus.DEAL_FINALIZED
        venture.selected_pitch_id = app.id
        venture.closed_at = now
        venture.closed_by_user_id = seller.id
        await self._ventures.save(venture)

        deal = await self._deals.create_from_pitch(venture=venture, pitch=app)
        await self._session.commit()

        brand_name = venture.brand_details.brand_name if venture.brand_details else "Venture"
        msg = (
            f"Deal finalized for {brand_name}. "
            "Awaiting Deltapreneur admin approval before payment."
        )
        _notify_sync(
            app.buyer_user_id,
            notification_type=NotificationType.VENTURE_DEAL_FINALIZED,
            title="Deal Finalized",
            message=msg,
            target_url=f"/ventures/deals/{deal['id']}",
        )
        _notify_sync(
            seller.id,
            notification_type=NotificationType.VENTURE_DEAL_FINALIZED,
            title="Deal Finalized",
            message=f"You selected a buyer for {brand_name}.",
            target_url=f"/ventures/deals/{deal['id']}",
        )
        _notify_admins_sync(
            notification_type=NotificationType.VENTURE_DEAL_FINALIZED,
            title="Venture Deal Finalized",
            message=f"Deal finalized for {brand_name}.",
            target_url="/admin",
        )
        return {"pitch": _serialize_pitch(app), "deal": deal}

    async def close_listing(
        self,
        venture_id: uuid.UUID,
        *,
        actor: AppUser,
        admin: bool = False,
    ) -> dict[str, Any]:
        result = await self._session.execute(
            select(Venture).where(Venture.id == venture_id).with_for_update()
        )
        venture = result.scalar_one_or_none()
        if venture is None:
            raise AppException("Venture not found.", status_code=404)
        if not admin and venture.listed_by_user_id != actor.id:
            raise AppException("Not authorized.", status_code=403)

        now = datetime.now(timezone.utc)
        venture.venture_listing_status = VentureListingStatus.CLOSED
        venture.closed_at = now
        venture.closed_by_user_id = actor.id
        await self._ventures.save(venture)
        await self._session.commit()

        brand_name = venture.brand_details.brand_name if venture.brand_details else "Venture"
        if venture.listed_by_user_id and venture.listed_by_user_id != actor.id:
            _notify_sync(
                venture.listed_by_user_id,
                notification_type=NotificationType.VENTURE_LISTING_CLOSED,
                title="Listing Closed",
                message=f"{brand_name} was closed by admin.",
                target_url="/ventures/dashboard",
            )
        return {"ventureId": str(venture_id), "status": venture.venture_listing_status.value}

    async def list_my_pitches(self, buyer: AppUser) -> list[dict[str, Any]]:
        rows = await self._pitches.list_by_buyer(buyer.id)
        return [_serialize_pitch(r) for r in rows if r.venture and r.venture.listing_mode == VentureListingMode.VENTURE]

    async def list_received(self, seller: AppUser) -> list[dict[str, Any]]:
        rows = await self._pitches.list_by_seller_ventures(seller.id)
        return [
            _serialize_pitch(r, include_buyer_phone=True)
            for r in rows
            if r.venture and r.venture.listing_mode == VentureListingMode.VENTURE
        ]

    async def list_all_admin(self) -> list[dict[str, Any]]:
        rows = await self._pitches.list_all_for_admin()
        return [_serialize_pitch(r) for r in rows]

    async def get_pitch(
        self,
        pitch_id: uuid.UUID,
        viewer: AppUser,
    ) -> dict[str, Any]:
        app = await self._pitches.get_by_id(pitch_id)
        if app is None:
            raise AppException("Bid not found.", status_code=404)
        venture = app.venture
        if (
            viewer.role != UserRole.ADMIN
            and app.buyer_user_id != viewer.id
            and (venture is None or venture.listed_by_user_id != viewer.id)
        ):
            raise AppException("Bid not found.", status_code=404)
        include_phone = (
            viewer.role == UserRole.ADMIN
            or (venture is not None and venture.listed_by_user_id == viewer.id)
        )
        return _serialize_pitch(app, include_buyer_phone=include_phone)

    async def list_public_bids(self, venture_id: uuid.UUID) -> list[dict[str, Any]]:
        venture = await self._ventures.get_by_id(venture_id)
        if venture is None:
            raise AppException("Venture not found.", status_code=404)
        if venture.listing_mode != VentureListingMode.VENTURE:
            raise AppException("Bids are only available for venture sale listings.", status_code=400)
        if venture.listing_approval_status != VentureListingApprovalStatus.APPROVED:
            raise AppException("This venture is not publicly available.", status_code=400)
        rows = await self._pitches.list_by_venture(venture_id)
        return [
            {
                "equityPercent": normalize_equity_percent(app.equity_percent_sought),
                "bidAmount": app.offer_amount,
                "createdAt": app.created_at.isoformat() if app.created_at else None,
            }
            for app in rows
            if app.status
            not in (
                VentureAcquisitionApplicationStatus.CANCELLED,
                VentureAcquisitionApplicationStatus.SELLER_REJECTED,
            )
        ]
