"""Domain marketplace enquiries (Java DomainEnquiryController parity, UUID listings)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException
from app.entity.cobranding.domain_enquiry_entity import DomainEnquiry
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.user.app_user import AppUser
from app.repository.domain_listing_repository import DomainListingRepository
from app.service.admin.admin_serializers import serialize_domain_enquiry
from app.utils.marketplace_enums import DomainEnquiryStatus, DomainListingStatus

logger = logging.getLogger(__name__)

# Strictly greater than ₹5L (align with FE isPremiumDomain).
PREMIUM_MARKETPLACE_MIN_PRICE_INR = 500_000.0

DOMAIN_UNAVAILABLE_MSG = (
    "This domain is no longer available for acquisition. It is currently under review."
)

_ALLOWED_TRANSITIONS: dict[DomainEnquiryStatus, set[DomainEnquiryStatus]] = {
    DomainEnquiryStatus.PENDING: {
        DomainEnquiryStatus.IN_PROGRESS,
        DomainEnquiryStatus.ACCEPTED,
        DomainEnquiryStatus.DECLINED,
    },
    DomainEnquiryStatus.IN_PROGRESS: {
        DomainEnquiryStatus.ACCEPTED,
        DomainEnquiryStatus.DECLINED,
    },
    DomainEnquiryStatus.ACCEPTED: {
        DomainEnquiryStatus.DECLINED,
    },
    DomainEnquiryStatus.COMPLETED: set(),
    DomainEnquiryStatus.DECLINED: {
        DomainEnquiryStatus.PENDING,
    },
}

_REMOVABLE_STATUSES = {
    DomainEnquiryStatus.PENDING,
    DomainEnquiryStatus.IN_PROGRESS,
    DomainEnquiryStatus.ACCEPTED,
    DomainEnquiryStatus.COMPLETED,
    DomainEnquiryStatus.DECLINED,
}

_UPDATABLE_STATUSES = {
    DomainEnquiryStatus.PENDING,
    DomainEnquiryStatus.IN_PROGRESS,
    DomainEnquiryStatus.ACCEPTED,
    DomainEnquiryStatus.DECLINED,
}

_ACTIVE_ENQUIRY_STATUSES = (
    DomainEnquiryStatus.PENDING.value,
    DomainEnquiryStatus.IN_PROGRESS.value,
    DomainEnquiryStatus.ACCEPTED.value,
)

_LISTING_PIPELINE_MESSAGE = "Listed premium domain (Pending buyer enquiry)"


def is_premium_marketplace_listing(listing: DomainListing) -> bool:
    """Marketplace listing priced above ₹5L (not OP registry premium)."""
    from app.utils.marketplace_enums import SaleType

    if listing is None:
        return False
    if getattr(listing, "sale_type", None) == SaleType.AUCTION:
        return False
    return float(listing.asking_price or 0) > PREMIUM_MARKETPLACE_MIN_PRICE_INR


class DomainEnquiryService:
    MIN_ASKING_PRICE_INR = PREMIUM_MARKETPLACE_MIN_PRICE_INR

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._listings = DomainListingRepository(session)

    @staticmethod
    def _parse_status(value: str) -> DomainEnquiryStatus:
        normalized = (value or "").strip().upper()
        try:
            status = DomainEnquiryStatus(normalized)
        except ValueError as exc:
            raise AppException(
                f"Invalid status '{value}'. Allowed values: "
                f"{', '.join(s.value for s in DomainEnquiryStatus)}.",
                status_code=400,
            ) from exc
        if status == DomainEnquiryStatus.COMPLETED:
            raise AppException(
                "Cannot set COMPLETED via status update. Use Mark Domain as Sold.",
                status_code=400,
            )
        if status not in _UPDATABLE_STATUSES:
            raise AppException(
                f"Status '{status.value}' cannot be set via this endpoint.",
                status_code=400,
            )
        return status

    @staticmethod
    def _not_deleted_filter():
        return or_(
            DomainEnquiry.is_deleted.is_(False),
            DomainEnquiry.is_deleted.is_(None),
        )

    async def _load_enquiry(
        self,
        enquiry_id: uuid.UUID,
    ) -> DomainEnquiry | None:
        stmt = (
            select(DomainEnquiry)
            .options(
                selectinload(DomainEnquiry.domain_listing).selectinload(
                    DomainListing.listed_by
                ),
            )
            .where(
                DomainEnquiry.id == enquiry_id,
                self._not_deleted_filter(),
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _load_active_enquiry_for_listing(
        self,
        listing_id: uuid.UUID,
    ) -> DomainEnquiry | None:
        stmt = (
            select(DomainEnquiry)
            .options(
                selectinload(DomainEnquiry.domain_listing).selectinload(
                    DomainListing.listed_by
                ),
            )
            .where(
                DomainEnquiry.domain_listing_id == listing_id,
                self._not_deleted_filter(),
                DomainEnquiry.status.in_(_ACTIVE_ENQUIRY_STATUSES),
            )
            .order_by(DomainEnquiry.created_at.desc())
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def _create_listing_pipeline_enquiry(
        self,
        listing: DomainListing,
    ) -> DomainEnquiry:
        row = DomainEnquiry(
            domain_listing_id=listing.id,
            enquirer_user_id=listing.listed_by_user_id,
            full_name="No buyer enquiry yet",
            email="-",
            phone="-",
            message=_LISTING_PIPELINE_MESSAGE,
            status=DomainEnquiryStatus.PENDING.value,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row, attribute_names=["domain_listing"])
        return row

    async def _resolve_enquiry_for_admin_action(
        self,
        entity_id: uuid.UUID,
        *,
        admin: AppUser,
    ) -> DomainEnquiry:
        enquiry = await self._load_enquiry(entity_id)
        if enquiry is not None:
            return enquiry

        listing = await self._listings.get_by_id(entity_id)
        if listing is None:
            raise AppException("Enquiry not found.", status_code=404)

        existing = await self._load_active_enquiry_for_listing(listing.id)
        if existing is not None:
            return existing

        return await self._create_listing_pipeline_enquiry(listing)

    async def submit(
        self,
        domain_listing_id: uuid.UUID,
        *,
        enquirer: AppUser,
        full_name: str | None,
        email: str | None,
        phone: str | None,
        message: str | None,
        listing_locked: DomainListing | None = None,
        skip_commit: bool = False,
    ) -> dict[str, Any]:
        """
        Create a buyer enquiry for a premium marketplace listing.

        When called from cart confirm, pass ``listing_locked`` (FOR UPDATE) and
        ``skip_commit=True`` so the caller can set UNDER_REVIEW in the same txn.
        """
        listing = listing_locked
        if listing is None:
            listing = await self._listings.get_by_id(domain_listing_id)
        if listing is None:
            raise AppException("Domain listing not found.", status_code=404)
        if listing.listed_by_user_id == enquirer.id:
            raise AppException("You cannot enquire about your own domain.", status_code=400)

        if listing.domain_status == DomainListingStatus.UNDER_REVIEW:
            raise AppException(DOMAIN_UNAVAILABLE_MSG, status_code=409)
        if listing.domain_status != DomainListingStatus.AVAILABLE:
            raise AppException("Domain is not available for acquisition.", status_code=400)

        if float(listing.asking_price or 0) <= self.MIN_ASKING_PRICE_INR:
            raise AppException(
                "Premium acquisition is only for domains above ₹5,00,000.",
                status_code=400,
            )

        pipeline_stmt = select(DomainEnquiry).where(
            DomainEnquiry.domain_listing_id == domain_listing_id,
            self._not_deleted_filter(),
            DomainEnquiry.status.in_(_ACTIVE_ENQUIRY_STATUSES),
            DomainEnquiry.message == _LISTING_PIPELINE_MESSAGE,
            DomainEnquiry.full_name == "No buyer enquiry yet",
        )
        pipeline_placeholder = (
            await self._session.execute(pipeline_stmt)
        ).scalar_one_or_none()
        if pipeline_placeholder is not None:
            now = datetime.now(timezone.utc)
            pipeline_placeholder.is_deleted = True
            pipeline_placeholder.deleted_at = now
            pipeline_placeholder.deleted_by = enquirer.id

        # Another buyer's active enquiry blocks new submissions.
        other_stmt = select(DomainEnquiry).where(
            DomainEnquiry.domain_listing_id == domain_listing_id,
            DomainEnquiry.enquirer_user_id != enquirer.id,
            self._not_deleted_filter(),
            DomainEnquiry.status.in_(_ACTIVE_ENQUIRY_STATUSES),
        )
        other = (await self._session.execute(other_stmt)).scalar_one_or_none()
        if other is not None:
            raise AppException(DOMAIN_UNAVAILABLE_MSG, status_code=409)

        stmt = select(DomainEnquiry).where(
            DomainEnquiry.domain_listing_id == domain_listing_id,
            DomainEnquiry.enquirer_user_id == enquirer.id,
            self._not_deleted_filter(),
            DomainEnquiry.status.in_(_ACTIVE_ENQUIRY_STATUSES),
        )
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            was_reopened = bool(existing.completed_at or existing.declined_at)
            is_pipeline_placeholder = (
                existing.message == _LISTING_PIPELINE_MESSAGE
                and existing.full_name == "No buyer enquiry yet"
            )
            if was_reopened or is_pipeline_placeholder:
                now = datetime.now(timezone.utc)
                existing.is_deleted = True
                existing.deleted_at = now
                existing.deleted_by = enquirer.id
            else:
                raise AppException(
                    "You have already submitted an enquiry for this domain.",
                    status_code=400,
                )
        row = DomainEnquiry(
            domain_listing_id=domain_listing_id,
            enquirer_user_id=enquirer.id,
            full_name=full_name,
            email=email,
            phone=phone,
            message=message,
            status=DomainEnquiryStatus.PENDING.value,
        )
        self._session.add(row)
        if skip_commit:
            # Caller (cart confirm) sets UNDER_REVIEW and commits the same txn.
            await self._session.flush()
            await self._session.refresh(row)
        else:
            listing.domain_status = DomainListingStatus.UNDER_REVIEW
            await self._listings.save(listing)
            await self._session.commit()
            await self._session.refresh(row)
        return {
            "id": str(row.id),
            "domainListingId": str(row.domain_listing_id),
            "status": row.status,
            "fullName": row.full_name,
            "email": row.email,
            "phone": row.phone,
            "message": row.message,
            "createdAt": row.created_at.isoformat() if row.created_at else None,
        }

    async def update_status(
        self,
        enquiry_id: uuid.UUID,
        *,
        admin: AppUser,
        status: str,
        admin_notes: str | None = None,
    ) -> dict[str, Any]:
        new_status = self._parse_status(status)
        enquiry = await self._resolve_enquiry_for_admin_action(
            enquiry_id,
            admin=admin,
        )

        try:
            current_status = DomainEnquiryStatus(enquiry.status)
        except ValueError as exc:
            raise AppException(
                f"Enquiry has invalid current status '{enquiry.status}'.",
                status_code=400,
            ) from exc

        allowed = _ALLOWED_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            raise AppException(
                f"Transition not allowed from {current_status.value} to {new_status.value}.",
                status_code=400,
            )

        enquiry.status = new_status.value
        if admin_notes is not None:
            enquiry.admin_notes = admin_notes.strip() or None

        now = datetime.now(timezone.utc)
        if new_status == DomainEnquiryStatus.IN_PROGRESS:
            enquiry.in_progress_at = now
        elif new_status == DomainEnquiryStatus.DECLINED:
            enquiry.declined_at = now
            listing = enquiry.domain_listing
            if listing is None:
                listing = await self._listings.get_by_id(enquiry.domain_listing_id)
            if listing is not None and listing.domain_status == DomainListingStatus.UNDER_REVIEW:
                listing.domain_status = DomainListingStatus.AVAILABLE
                await self._listings.save(listing)

        await self._session.commit()
        await self._session.refresh(enquiry)

        await self._notify_buyer_of_update(
            enquiry,
            status_label=new_status.value.replace("_", " ").title(),
            admin_message=(admin_notes.strip() if admin_notes else None) or None,
        )
        return serialize_domain_enquiry(enquiry)

    async def mark_sold(
        self,
        enquiry_id: uuid.UUID,
        *,
        admin: AppUser,
        admin_notes: str | None = None,
    ) -> dict[str, Any]:
        """Separate admin action: ACCEPTED enquiry → COMPLETED; listing UNDER_REVIEW → SOLD."""
        enquiry = await self._resolve_enquiry_for_admin_action(
            enquiry_id,
            admin=admin,
        )
        try:
            current_status = DomainEnquiryStatus(enquiry.status)
        except ValueError as exc:
            raise AppException(
                f"Enquiry has invalid current status '{enquiry.status}'.",
                status_code=400,
            ) from exc

        if current_status != DomainEnquiryStatus.ACCEPTED:
            raise AppException(
                "Mark Domain as Sold requires an ACCEPTED enquiry.",
                status_code=400,
            )

        listing = enquiry.domain_listing
        if listing is None:
            listing = await self._listings.get_by_id_for_update(enquiry.domain_listing_id)
        else:
            listing = await self._listings.get_by_id_for_update(listing.id)

        if listing is None:
            raise AppException("Domain listing not found.", status_code=404)
        if listing.domain_status != DomainListingStatus.UNDER_REVIEW:
            raise AppException(
                "Listing must be UNDER_REVIEW to mark as sold.",
                status_code=400,
            )

        now = datetime.now(timezone.utc)
        if admin_notes is not None:
            enquiry.admin_notes = admin_notes.strip() or enquiry.admin_notes

        enquiry.status = DomainEnquiryStatus.COMPLETED.value
        enquiry.completed_at = now

        listing.domain_status = DomainListingStatus.SOLD
        listing.sold_at = now
        listing.purchased_by_user_id = enquiry.enquirer_user_id
        await self._listings.save(listing)

        await self._session.commit()
        await self._session.refresh(enquiry)

        await self._notify_buyer_of_update(
            enquiry,
            status_label="Completed — Domain Marked Sold",
            admin_message=(admin_notes.strip() if admin_notes else None) or None,
        )
        return serialize_domain_enquiry(enquiry)

    async def remove_enquiry(
        self,
        enquiry_id: uuid.UUID,
        *,
        admin: AppUser,
        admin_notes: str | None = None,
    ) -> dict[str, Any]:
        enquiry = await self._resolve_enquiry_for_admin_action(
            enquiry_id,
            admin=admin,
        )

        try:
            current_status = DomainEnquiryStatus(enquiry.status)
        except ValueError as exc:
            raise AppException(
                f"Enquiry has invalid current status '{enquiry.status}'.",
                status_code=400,
            ) from exc

        if current_status not in _REMOVABLE_STATUSES:
            raise AppException(
                f"Enquiry status '{current_status.value}' cannot be removed.",
                status_code=400,
            )

        now = datetime.now(timezone.utc)
        enquiry.is_deleted = True
        enquiry.deleted_at = now
        enquiry.deleted_by = admin.id
        if admin_notes is not None:
            enquiry.admin_notes = admin_notes.strip() or None

        # If removing an active premium hold, free the listing.
        if current_status in (
            DomainEnquiryStatus.PENDING,
            DomainEnquiryStatus.IN_PROGRESS,
            DomainEnquiryStatus.ACCEPTED,
        ):
            listing = enquiry.domain_listing
            if listing is None:
                listing = await self._listings.get_by_id(enquiry.domain_listing_id)
            if listing is not None and listing.domain_status == DomainListingStatus.UNDER_REVIEW:
                listing.domain_status = DomainListingStatus.AVAILABLE
                await self._listings.save(listing)

        await self._session.commit()
        return {"success": True, "id": str(enquiry.id)}

    async def _notify_buyer_of_update(
        self,
        enquiry: DomainEnquiry,
        *,
        status_label: str,
        admin_message: str | None,
    ) -> None:
        """Email + in-app notify the buyer whenever admin updates status/notes."""
        from app.core.database import SessionLocal
        from app.entity.notification.notification_type import NotificationType
        from app.service.auth.mail_service import MailService
        from app.service.notification.notification_service import NotificationService

        listing = enquiry.domain_listing
        if listing is None:
            listing = await self._listings.get_by_id(enquiry.domain_listing_id)
        fqdn = (
            f"{listing.domain_name}{listing.domain_extension or ''}"
            if listing is not None
            else "your premium domain"
        )
        buyer_name = enquiry.full_name or "there"
        to_email = (enquiry.email or "").strip()

        # Prefer linked account email when available.
        buyer_user = None
        if enquiry.enquirer_user_id:
            buyer_user = await self._session.get(AppUser, enquiry.enquirer_user_id)
            if buyer_user and buyer_user.email:
                to_email = buyer_user.email.strip() or to_email

        if to_email:
            try:
                await MailService.send_premium_marketplace_buyer_update_email(
                    to_email=to_email,
                    buyer_name=buyer_name,
                    domain_fqdn=fqdn,
                    status_label=status_label,
                    admin_message=admin_message,
                    enquiry_id=str(enquiry.id),
                )
            except Exception:
                logger.exception(
                    "premium_marketplace.buyer_update_email.failed enquiry=%s",
                    enquiry.id,
                )

        if enquiry.enquirer_user_id:
            db = SessionLocal()
            try:
                user = db.query(AppUser).filter(AppUser.id == enquiry.enquirer_user_id).first()
                if user is not None:
                    note_preview = (admin_message or "").strip()
                    message = (
                        f"Status: {status_label}."
                        + (f" Message: {note_preview}" if note_preview else "")
                    )
                    NotificationService.notify(
                        db,
                        user=user,
                        notification_type=NotificationType.DOMAIN_PREMIUM_UPDATE,
                        title=f"Update on {fqdn}",
                        message=message[:500],
                        target_url="/notifications",
                    )
                    db.commit()
            except Exception:
                logger.exception(
                    "premium_marketplace.buyer_update_notify.failed enquiry=%s",
                    enquiry.id,
                )
                db.rollback()
            finally:
                db.close()

    async def list_all_admin(self) -> list[dict[str, Any]]:
        stmt = (
            select(DomainEnquiry)
            .options(
                selectinload(DomainEnquiry.domain_listing).selectinload(
                    DomainListing.listed_by
                ),
            )
            .where(self._not_deleted_filter())
            .order_by(DomainEnquiry.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        enquiries = [serialize_domain_enquiry(r) for r in rows]

        enquired_listing_ids = {
            r.domain_listing_id for r in rows if r.domain_listing_id
        }

        stmt_listings = (
            select(DomainListing)
            .where(
                DomainListing.asking_price > self.MIN_ASKING_PRICE_INR,
                DomainListing.is_deleted.is_(False),
                DomainListing.taken_down.is_(False),
                DomainListing.domain_status == DomainListingStatus.AVAILABLE,
            )
            .options(selectinload(DomainListing.listed_by))
        )
        listings = (await self._session.execute(stmt_listings)).scalars().all()

        from app.entity.cobrother.cobrother_request_entity import CoBrotherRequest
        from app.utils.marketplace_enums import CoBrotherRequestStatus

        listings_to_check = [l.id for l in listings if l.id not in enquired_listing_ids]
        forwarded_listing_ids = set()
        if listings_to_check:
            stmt_requests = select(CoBrotherRequest).where(
                CoBrotherRequest.entity_id.in_(listings_to_check),
                CoBrotherRequest.status.not_in(
                    [CoBrotherRequestStatus.CANCELLED, CoBrotherRequestStatus.REJECTED]
                ),
            )
            active_requests = (await self._session.execute(stmt_requests)).scalars().all()
            forwarded_listing_ids = {r.entity_id for r in active_requests}

        for listing in listings:
            if listing.id not in enquired_listing_ids:
                is_forwarded = listing.id in forwarded_listing_ids
                status = (
                    DomainEnquiryStatus.FORWARDED.value
                    if is_forwarded
                    else DomainEnquiryStatus.PENDING.value
                )
                enquiries.append({
                    "id": str(listing.id),
                    "domainListingId": str(listing.id),
                    "fullName": "No buyer enquiry yet",
                    "email": "-",
                    "phone": "-",
                    "message": "Listed premium domain (Pending buyer enquiry)",
                    "status": status,
                    "isVirtual": True,
                    "createdAt": listing.created_at.isoformat() if listing.created_at else None,
                    "domain": {
                        "id": str(listing.id),
                        "domainName": listing.domain_name,
                        "domainExtension": listing.domain_extension,
                        "askingPrice": float(listing.asking_price or 0),
                        "pricingDemand": listing.pricing_demand,
                        "domainStatus": (
                            listing.domain_status.value
                            if hasattr(listing.domain_status, "value")
                            else listing.domain_status
                        ),
                        "listedBy": {
                            "firstname": listing.listed_by.firstname if listing.listed_by else "",
                            "lastname": listing.listed_by.lastname if listing.listed_by else "",
                            "email": listing.listed_by.email if listing.listed_by else "",
                        } if listing.listed_by else None
                    }
                })

        enquiries.sort(key=lambda e: e.get("createdAt") or "", reverse=True)
        return enquiries
