"""Admin forward-to-HubRegistrar workflow (Java AdminService.forwardToHubRegistrar parity)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.entity.cobranding.domain_enquiry_entity import DomainEnquiry
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.cobrother.cobrother_request_entity import CoBrotherRequest
from app.entity.cocreation.software_purchase_entity import SoftwarePurchase
from app.entity.cocreation.software_entity import Software
from app.entity.coventure.partner_entity import CoVenture
from app.entity.coventure.venture_entity import Venture
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.service.cobrother.cobrother_request_mail import (
    notify_cobrother_assigned,
    send_fee_request_email,
)
from app.utils.cocreation_enums import SoftwarePaymentStatus
from app.utils.marketplace_enums import CoBrotherRequestStatus, CoBrotherRequestType

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = (
    CoBrotherRequestStatus.CANCELLED,
    CoBrotherRequestStatus.REJECTED,
)


def _error(message: str) -> dict[str, Any]:
    return {"success": False, "error": message}


def _snapshot(**fields: Any) -> str:
    return json.dumps({k: v for k, v in fields.items() if v is not None})


def _active_request_exists(
    db: Session,
    *,
    entity_id: uuid.UUID,
    request_type: CoBrotherRequestType,
) -> bool:
    stmt = (
        select(CoBrotherRequest.id)
        .where(
            CoBrotherRequest.entity_id == entity_id,
            CoBrotherRequest.request_type == request_type,
            CoBrotherRequest.status.not_in(_TERMINAL_STATUSES),
        )
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none() is not None


def _already_assigned_to_cobrother(
    db: Session,
    *,
    entity_id: uuid.UUID,
    request_type: CoBrotherRequestType,
    cobrother_id: uuid.UUID,
) -> bool:
    stmt = (
        select(CoBrotherRequest.id)
        .where(
            CoBrotherRequest.entity_id == entity_id,
            CoBrotherRequest.request_type == request_type,
            CoBrotherRequest.assigned_cobrother_id == cobrother_id,
            CoBrotherRequest.status.not_in(_TERMINAL_STATUSES),
        )
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none() is not None


def _find_pending_cocreation_request(
    db: Session,
    *,
    purchase_id: uuid.UUID | None,
    software_id: uuid.UUID | None,
) -> CoBrotherRequest | None:
    ids: list[uuid.UUID] = []
    if purchase_id is not None:
        ids.append(purchase_id)
    if software_id is not None:
        ids.append(software_id)
    if not ids:
        return None
    stmt = (
        select(CoBrotherRequest)
        .where(
            CoBrotherRequest.request_type == CoBrotherRequestType.COCREATION,
            CoBrotherRequest.entity_id.in_(ids),
            CoBrotherRequest.status == CoBrotherRequestStatus.PENDING,
        )
        .order_by(CoBrotherRequest.created_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _lister_snapshot_fields(lister: AppUser) -> dict[str, Any]:
    return {
        "listerName": f"{lister.firstname or ''} {lister.lastname or ''}".strip() or lister.email,
        "listerEmail": lister.email,
        "listerPhone": lister.phone_number,
    }



def forward_to_cobrother(
    db: Session,
    *,
    entity_id: str,
    request_type: str,
    cobrother_id: str | None,
    admin: AppUser,
) -> dict[str, Any]:
    if not cobrother_id or not str(cobrother_id).strip():
        return _error("coBrotherId is required")

    try:
        entity_uid = uuid.UUID(str(entity_id).strip())
        cobrother_uid = uuid.UUID(str(cobrother_id).strip())
    except ValueError:
        return _error("Invalid entity or HubRegistrar id")

    cobrother = (
        db.query(AppUser)
        .filter(
            AppUser.id == cobrother_uid,
            AppUser.role == UserRole.COBROTHER,
            AppUser.is_deleted.is_(False),
        )
        .first()
    )
    if cobrother is None:
        return _error("HubRegistrar not found")

    try:
        req_type = CoBrotherRequestType(request_type.strip().upper())
    except ValueError:
        return _error(f"Unsupported request type: {request_type}")

    now = datetime.now(timezone.utc)

    if req_type == CoBrotherRequestType.COCREATION:
        return _forward_cocreation(
            db,
            entity_uid=entity_uid,
            cobrother=cobrother,
            admin=admin,
            now=now,
        )

    if req_type == CoBrotherRequestType.DOMAIN_ENQUIRY:
        enquiry = db.query(DomainEnquiry).filter(DomainEnquiry.id == entity_uid).first()
        if enquiry is None:
            domain = db.query(DomainListing).filter(DomainListing.id == entity_uid).first()
            if domain is not None:
                if _already_assigned_to_cobrother(
                    db,
                    entity_id=entity_uid,
                    request_type=CoBrotherRequestType.DOMAIN,
                    cobrother_id=cobrother.id,
                ):
                    return _error("This HubRegistrar has already been assigned to this request.")

                if _active_request_exists(db, entity_id=entity_uid, request_type=CoBrotherRequestType.DOMAIN):
                    return _error("An active HubRegistrar request already exists for this domain listing.")

                return _forward_domain(db, entity_uid=entity_uid, cobrother=cobrother, admin=admin, now=now)

    if _already_assigned_to_cobrother(
        db,
        entity_id=entity_uid,
        request_type=req_type,
        cobrother_id=cobrother.id,
    ):
        return _error("This HubRegistrar has already been assigned to this request.")

    if _active_request_exists(db, entity_id=entity_uid, request_type=req_type):
        return _error(f"An active HubRegistrar request already exists for this {req_type.value}.")

    if req_type == CoBrotherRequestType.COVENTURE:
        return _forward_coventure(db, entity_uid=entity_uid, cobrother=cobrother, admin=admin, now=now)
    if req_type == CoBrotherRequestType.DOMAIN:
        return _forward_domain(db, entity_uid=entity_uid, cobrother=cobrother, admin=admin, now=now)
    if req_type == CoBrotherRequestType.DOMAIN_ENQUIRY:
        return _forward_domain_enquiry(db, entity_uid=entity_uid, cobrother=cobrother, admin=admin, now=now)

    return _error(f"Unsupported request type: {request_type}")


def _forward_coventure(
    db: Session,
    *,
    entity_uid: uuid.UUID,
    cobrother: AppUser,
    admin: AppUser,
    now: datetime,
) -> dict[str, Any]:
    cv = (
        db.query(CoVenture)
        .options(
            joinedload(CoVenture.venture).joinedload(Venture.brand_details),
            joinedload(CoVenture.applicant),
        )
        .filter(CoVenture.id == entity_uid)
        .first()
    )
    if cv is None or cv.venture is None:
        return _error("CoVenture not found")

    lister = cv.venture.listed_by
    if lister is None:
        return _error("Venture lister not found")

    brand = cv.venture.brand_details.brand_name if cv.venture.brand_details else "Venture"
    applicant = cv.applicant
    applicant_name = cv.full_name
    if not applicant_name and applicant:
        applicant_name = f"{applicant.firstname or ''} {applicant.lastname or ''}".strip() or None
    row = CoBrotherRequest(
        request_type=CoBrotherRequestType.COVENTURE,
        entity_id=entity_uid,
        entity_snapshot=_snapshot(
            type="CoVenture",
            title=brand,
            **_lister_snapshot_fields(lister),
            applicantName=applicant_name,
            applicantEmail=applicant.email if applicant else None,
            applicantPhone=cv.phone,
        ),
        assigned_cobrother_id=cobrother.id,
        admin_user_id=admin.id,
        lister_id=lister.id,
        status=CoBrotherRequestStatus.PAYMENT_PENDING,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    lister_name = f"{lister.firstname or ''} {lister.lastname or ''}".strip() or lister.email
    send_fee_request_email(lister=lister, entity_title=brand)
    return {
        "success": True,
        "requestId": str(row.id),
        "message": f"Payment request sent to {lister_name}",
    }


def _forward_domain(
    db: Session,
    *,
    entity_uid: uuid.UUID,
    cobrother: AppUser,
    admin: AppUser,
    now: datetime,
) -> dict[str, Any]:
    domain = (
        db.query(DomainListing)
        .options(joinedload(DomainListing.listed_by), joinedload(DomainListing.purchased_by))
        .filter(DomainListing.id == entity_uid)
        .first()
    )
    if domain is None:
        return _error("Domain not found")

    lister = domain.listed_by
    if lister is None:
        return _error("Domain lister not found")

    buyer = domain.purchased_by
    title = f"{domain.domain_name}{domain.domain_extension or ''}"
    buyer_name = None
    if buyer:
        buyer_name = f"{buyer.firstname or ''} {buyer.lastname or ''}".strip() or buyer.email
    row = CoBrotherRequest(
        request_type=CoBrotherRequestType.DOMAIN,
        entity_id=entity_uid,
        entity_snapshot=_snapshot(
            type="Domain",
            title=title,
            price=domain.asking_price,
            **_lister_snapshot_fields(lister),
            applicantName=buyer_name,
            applicantEmail=buyer.email if buyer else None,
            applicantPhone=buyer.phone_number if buyer else None,
        ),
        assigned_cobrother_id=cobrother.id,
        admin_user_id=admin.id,
        lister_id=lister.id,
        status=CoBrotherRequestStatus.PAYMENT_PENDING,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    lister_name = f"{lister.firstname or ''} {lister.lastname or ''}".strip() or lister.email
    send_fee_request_email(lister=lister, entity_title=title)
    return {
        "success": True,
        "requestId": str(row.id),
        "message": f"Payment request sent to {lister_name}",
    }


def _forward_domain_enquiry(
    db: Session,
    *,
    entity_uid: uuid.UUID,
    cobrother: AppUser,
    admin: AppUser,
    now: datetime,
) -> dict[str, Any]:
    enquiry = (
        db.query(DomainEnquiry)
        .options(joinedload(DomainEnquiry.domain_listing).joinedload(DomainListing.listed_by))
        .filter(DomainEnquiry.id == entity_uid)
        .first()
    )
    if enquiry is None or enquiry.domain_listing is None:
        return _error("Enquiry not found")

    domain = enquiry.domain_listing
    lister = domain.listed_by
    if lister is None:
        return _error("Domain lister not found")

    title = f"{domain.domain_name}{domain.domain_extension or ''}"
    row = CoBrotherRequest(
        request_type=CoBrotherRequestType.DOMAIN_ENQUIRY,
        entity_id=entity_uid,
        entity_snapshot=_snapshot(
            type="DomainEnquiry",
            title=title,
            message=enquiry.message,
            price=domain.asking_price,
            **_lister_snapshot_fields(lister),
            applicantName=enquiry.full_name,
            applicantEmail=enquiry.email,
            applicantPhone=enquiry.phone,
        ),
        assigned_cobrother_id=cobrother.id,
        admin_user_id=admin.id,
        lister_id=lister.id,
        status=CoBrotherRequestStatus.PAYMENT_PENDING,
    )
    enquiry.status = "FORWARDED"
    db.add(row)
    db.commit()
    db.refresh(row)
    lister_name = f"{lister.firstname or ''} {lister.lastname or ''}".strip() or lister.email
    send_fee_request_email(lister=lister, entity_title=title)
    return {
        "success": True,
        "requestId": str(row.id),
        "message": f"Payment request sent to {lister_name}",
    }


def _forward_cocreation(
    db: Session,
    *,
    entity_uid: uuid.UUID,
    cobrother: AppUser,
    admin: AppUser,
    now: datetime,
) -> dict[str, Any]:
    purchase = (
        db.query(SoftwarePurchase)
        .options(joinedload(SoftwarePurchase.software), joinedload(SoftwarePurchase.buyer))
        .filter(SoftwarePurchase.id == entity_uid)
        .first()
    )
    software_id: uuid.UUID | None = None
    if purchase is None:
        software = db.get(Software, entity_uid)
        if software is None:
            return _error("Software purchase or listing not found")
        software_id = software.id
        purchase = (
            db.query(SoftwarePurchase)
            .options(joinedload(SoftwarePurchase.software), joinedload(SoftwarePurchase.buyer))
            .filter(
                SoftwarePurchase.software_id == software.id,
                SoftwarePurchase.payment_status == SoftwarePaymentStatus.COMPLETED,
                SoftwarePurchase.co_brother_help_paid.is_(True),
            )
            .order_by(
                SoftwarePurchase.sold_at.desc().nullslast(),
                SoftwarePurchase.created_at.desc(),
            )
            .first()
        )
        if purchase is None:
            return _error(
                "No completed purchase with HubRegistrar addon paid was found for this listing."
            )
    else:
        software_id = purchase.software_id

    if purchase.payment_status != SoftwarePaymentStatus.COMPLETED:
        return _error("The buyer's software purchase is not yet completed.")
    if not purchase.co_brother_help_paid:
        return _error("The buyer has not paid the HubRegistrar addon (₹1,000) yet.")

    if _already_assigned_to_cobrother(
        db,
        entity_id=purchase.id,
        request_type=CoBrotherRequestType.COCREATION,
        cobrother_id=cobrother.id,
    ):
        return _error("This HubRegistrar has already been assigned to this request.")

    existing = _find_pending_cocreation_request(
        db,
        purchase_id=purchase.id,
        software_id=software_id,
    )
    if existing is None:
        return _error(
            "No pending HubRegistrar request found for this purchase. "
            "The addon may not have been paid yet."
        )

    title = existing.entity_snapshot or "Software"
    if purchase.software:
        title = purchase.software.name

    buyer = purchase.buyer
    buyer_name = purchase.buyer_full_name
    if not buyer_name and buyer:
        buyer_name = f"{buyer.firstname or ''} {buyer.lastname or ''}".strip() or buyer.email
    lister = purchase.buyer
    if lister:
        existing.entity_snapshot = _snapshot(
            type="CoCreation",
            title=title,
            **_lister_snapshot_fields(lister),
            applicantName=buyer_name,
            applicantEmail=purchase.buyer_email or (buyer.email if buyer else None),
            applicantPhone=purchase.buyer_phone or (buyer.phone_number if buyer else None),
        )

    existing.assigned_cobrother_id = cobrother.id
    existing.admin_user_id = admin.id
    existing.entity_id = purchase.id
    existing.status = CoBrotherRequestStatus.FORWARDED
    if purchase.buyer_id and existing.lister_id is None:
        existing.lister_id = purchase.buyer_id

    db.commit()
    db.refresh(existing)
    notify_cobrother_assigned(db, cobrother=cobrother, row=existing)
    return {
        "success": True,
        "requestId": str(existing.id),
        "message": "HubRegistrar notified directly — buyer had already paid the addon.",
    }
