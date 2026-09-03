"""Serialize admin list rows for the React AdminDashboardPage (Java-shaped payloads)."""

from __future__ import annotations

import json
from typing import Any

from app.entity.community.community import Community
from app.entity.cobrother.cobrother_request_entity import CoBrotherRequest
from app.entity.cobranding.domain_enquiry_entity import DomainEnquiry
from app.entity.auction.auction_entity import Auction
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.coventure.partner_entity import CoVenture
from app.entity.user.app_user import AppUser
from app.utils.domain_listing_utils import listing_type_for
from app.utils.equity_percent import normalize_equity_percent
from app.utils.money import round_inr


def user_brief(user: AppUser | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": str(user.id),
        "firstname": user.firstname,
        "lastname": user.lastname,
        "email": user.email,
        "phoneNumber": user.phone_number,
    }


def serialize_coventure(cv: CoVenture) -> dict[str, Any]:
    venture = cv.venture
    brand_name = None
    website = None
    listed_by = None
    taken_down = False
    take_down_reason = None
    venture_id = None
    verified = False
    gstin_verified = False
    sale_type = None
    if venture is not None:
        venture_id = str(venture.id)
        if venture.brand_details is not None:
            brand_name = venture.brand_details.brand_name
            website = venture.brand_details.website
        listed_by = user_brief(venture.listed_by)
        taken_down = bool(venture.taken_down)
        take_down_reason = venture.take_down_reason
        verified = bool(venture.verified)
        gstin_verified = bool(venture.gstin_verified)
        sale_type = (
            venture.sale_type.value
            if venture.sale_type is not None and hasattr(venture.sale_type, "value")
            else venture.sale_type
        )

    status = cv.status.value if hasattr(cv.status, "value") else cv.status
    return {
        "id": str(cv.id),
        "status": status,
        "venture": {
            "id": venture_id,
            "brandDetails": {"brandName": brand_name, "website": website},
            "listedBy": listed_by,
            "verified": verified,
            "gstinVerified": gstin_verified,
            "saleType": sale_type,
        },
        "applicant": user_brief(cv.applicant),
        "takenDown": taken_down,
        "takeDownReason": take_down_reason,
    }


def _serialize_auction_brief(auction: Auction | None) -> dict[str, Any] | None:
    if auction is None:
        return None
    duration = auction.duration
    duration_val = duration.value if hasattr(duration, "value") else duration
    status_val = auction.status.value if hasattr(auction.status, "value") else auction.status
    return {
        "id": str(auction.id),
        "status": status_val,
        "minBidPrice": float(auction.min_bid_price),
        "duration": duration_val,
        "startTime": auction.start_time.isoformat() if auction.start_time else None,
        "endTime": auction.end_time.isoformat() if auction.end_time else None,
        "totalBids": int(auction.total_bids or 0),
        "currentHighestBid": (
            float(auction.current_highest_bid)
            if auction.current_highest_bid is not None
            else None
        ),
    }


def serialize_domain(
    listing: DomainListing,
    *,
    purchasers: dict[str, AppUser],
    auction: Auction | None = None,
) -> dict[str, Any]:
    purchaser = None
    if listing.purchased_by_user_id is not None:
        purchaser = purchasers.get(str(listing.purchased_by_user_id))
    domain_status = (
        listing.domain_status.value
        if listing.domain_status is not None and hasattr(listing.domain_status, "value")
        else listing.domain_status
    )
    sale_type = (
        listing.sale_type.value
        if listing.sale_type is not None and hasattr(listing.sale_type, "value")
        else listing.sale_type
    )
    verification_method = (
        listing.verification_method.value
        if listing.verification_method is not None
        and hasattr(listing.verification_method, "value")
        else listing.verification_method
    )
    verification_status = (
        listing.verification_status.value
        if listing.verification_status is not None
        and hasattr(listing.verification_status, "value")
        else listing.verification_status
    )
    listing_type = listing_type_for(listing.sale_type)
    payload: dict[str, Any] = {
        "id": str(listing.id),
        "domainName": listing.domain_name,
        "domainExtension": listing.domain_extension or "",
        "askingPrice": listing.asking_price,
        "domainStatus": domain_status,
        "saleType": sale_type,
        "listingType": listing_type,
        "featured": listing.featured,
        "verified": bool(listing.verified),
        "verifiedAt": listing.verified_at.isoformat() if listing.verified_at else None,
        "verificationMethod": verification_method,
        "verificationStatus": verification_status,
        "verificationRejectionReason": listing.verification_rejection_reason,
        "verificationAdminNote": listing.verification_admin_note,
        "verifiedBy": user_brief(getattr(listing, "verified_by", None)),
        "takenDown": listing.taken_down,
        "takeDownReason": listing.take_down_reason,
        "listedBy": user_brief(listing.listed_by),
        "purchasedBy": user_brief(purchaser),
        "views": int(listing.views or 0),
        "createdAt": listing.created_at.isoformat() if listing.created_at else None,
        "updatedAt": listing.updated_at.isoformat() if listing.updated_at else None,
        "soldAt": listing.sold_at.isoformat() if listing.sold_at else None,
    }
    if listing_type == "domain_auction":
        payload["auction"] = _serialize_auction_brief(auction)
    return payload


def serialize_technology_listing(software: Any) -> dict[str, Any]:
    return {
        "id": str(software.id),
        "name": software.name,
        "githubLink": software.github_link,
        "liveDemoLink": software.live_demo_link,
        "listedBy": user_brief(software.listed_by),
        "takenDown": bool(software.taken_down),
        "takeDownReason": software.take_down_reason,
        "official": bool(software.official),
        "featured": bool(software.featured),
        "verified": bool(getattr(software, "verified", False)),
        "verifiedAt": software.verified_at.isoformat() if getattr(software, "verified_at", None) else None,
        "views": int(getattr(software, "views", 0) or 0),
        "category": (
            software.category.value
            if getattr(software, "category", None) is not None
            and hasattr(software.category, "value")
            else getattr(software, "category", None)
        ),
    }


def serialize_cocreation_purchase_row(
    *,
    software_id: str,
    purchase_id: str,
    name: str,
    lister: AppUser | None,
    buyer: AppUser | None,
    taken_down: bool,
    take_down_reason: str | None,
    github_link: str | None = None,
    live_demo_link: str | None = None,
) -> dict[str, Any]:
    return {
        "id": software_id,
        "purchaseId": purchase_id,
        "name": name,
        "githubLink": github_link,
        "liveDemoLink": live_demo_link,
        "listedBy": user_brief(lister),
        "purchasedBy": user_brief(buyer),
        "takenDown": taken_down,
        "takeDownReason": take_down_reason,
    }


def serialize_coventure_application(cv: CoVenture) -> dict[str, Any]:
    status = cv.status.value if hasattr(cv.status, "value") else cv.status
    return {
        "id": str(cv.id),
        "status": status,
        "fullName": cv.full_name,
        "phone": cv.phone,
        "location": cv.location,
        "description": cv.description,
        "videoIntroductionUrl": cv.video_introduction_url,
        "applicant": user_brief(cv.applicant),
    }


def serialize_acquisition_application(app: Any) -> dict[str, Any]:
    status = app.status.value if hasattr(app.status, "value") else app.status
    buyer = getattr(app, "buyer", None)
    buyer_name = None
    if buyer:
        buyer_name = f"{buyer.firstname or ''} {buyer.lastname or ''}".strip() or buyer.email
    return {
        "id": str(app.id),
        "status": status,
        "offeredAmount": app.offer_amount,
        "requestedEquityPercent": normalize_equity_percent(app.equity_percent_sought),
        "investmentProposal": app.investment_proposal,
        "additionalNotes": app.additional_notes,
        "buyerName": buyer_name,
        "buyerEmail": buyer.email if buyer else None,
        "buyer": user_brief(buyer),
        "createdAt": app.created_at.isoformat() if getattr(app, "created_at", None) else None,
    }


def serialize_venture_admin(venture: Any) -> dict[str, Any]:
    """Full venture row for admin Ventures tab (includes co-venture applications)."""
    brand = venture.brand_details
    sale_type = (
        venture.sale_type.value
        if venture.sale_type is not None and hasattr(venture.sale_type, "value")
        else venture.sale_type
    )
    applications = [
        serialize_coventure_application(cv)
        for cv in (getattr(venture, "co_venture_applications", None) or [])
    ]
    pitches = [
        serialize_acquisition_application(app)
        for app in (
            getattr(venture, "pitches", None)
            or getattr(venture, "acquisition_applications", None)
            or []
        )
    ]
    def _enum_value(value: Any) -> Any:
        return value.value if value is not None and hasattr(value, "value") else value

    company_profile = getattr(venture, "company_profile", None)
    profile_complete = bool(company_profile.is_complete) if company_profile else False
    profile_payload = None
    if company_profile:
        profile_payload = {
            "isComplete": profile_complete,
            "currentYearRevenueInr": company_profile.current_year_revenue_inr,
            "previousYearRevenueInr": company_profile.previous_year_revenue_inr,
            "twoYearsAgoRevenueInr": company_profile.two_years_ago_revenue_inr,
            "teamMembers": company_profile.team_members or [],
        }
    verification_docs = [
        {
            "id": str(doc.id),
            "fileUrl": doc.file_url,
            "fileName": doc.file_name,
        }
        for doc in (getattr(venture, "verification_documents", None) or [])
    ]
    return {
        "id": str(venture.id),
        "saleType": sale_type,
        "listingMode": _enum_value(getattr(venture, "listing_mode", None)),
        "dealType": _enum_value(getattr(venture, "deal_type", None)),
        "acquisitionFlow": _enum_value(getattr(venture, "acquisition_flow", None)),
        "listingApprovalStatus": _enum_value(
            getattr(venture, "listing_approval_status", None)
        ),
        "ventureListingStatus": _enum_value(
            getattr(venture, "venture_listing_status", None)
        ),
        "companyProfileComplete": profile_complete,
        "companyProfile": profile_payload,
        "ownershipLiquidationPercent": normalize_equity_percent(
            getattr(venture, "equity_percent_offered", None)
        ),
        "verificationRequested": bool(getattr(venture, "verification_requested", False)),
        "verificationStatus": _enum_value(getattr(venture, "verification_status", None)),
        "verificationVideoUrl": getattr(venture, "verification_video_url", None),
        "verificationDocuments": verification_docs,
        "verified": bool(venture.verified),
        "gstinVerified": bool(venture.gstin_verified),
        "gstin": venture.gstin,
        "featured": venture.featured,
        "takenDown": venture.taken_down,
        "takeDownReason": venture.take_down_reason,
        "applicationCount": len(applications),
        "pitchCount": len(pitches),
        "bidCount": len(pitches),
        "coVentureApplicationCount": len(applications),
        "coVentureApplications": applications,
        "pitches": pitches,
        "acquisitionApplications": pitches,
        "bids": pitches,
        "equityPercentOffered": normalize_equity_percent(
            getattr(venture, "equity_percent_offered", None)
        ),
        "brandDetails": {
            "brandName": brand.brand_name if brand else None,
            "website": brand.website if brand else None,
            "dealValue": round_inr(brand.deal_value) if brand and brand.deal_value else None,
            "industry": (
                brand.industry.value
                if brand and brand.industry is not None and hasattr(brand.industry, "value")
                else (brand.industry if brand else None)
            ),
        },
        "listedBy": user_brief(venture.listed_by),
        "views": int(getattr(venture, "views", 0) or 0),
    }


def serialize_community_admin(community: Community) -> dict[str, Any]:
    from app.utils.community_profile_completion import evaluate_profile_completion

    completion = evaluate_profile_completion(community)
    return {
        "id": str(community.id),
        "name": community.name,
        "role": community.role,
        "industry": community.industry,
        "views": int(community.views or 0),
        "featured": bool(getattr(community, "featured", False)),
        "profileComplete": completion["is_complete"],
        "listedBy": user_brief(getattr(community, "app_user", None)),
        "appUserId": str(community.app_user_id) if community.app_user_id else None,
    }


def _snapshot_title(snapshot: str | None) -> str | None:
    if not snapshot:
        return None
    try:
        data = json.loads(snapshot)
        if isinstance(data, dict):
            return data.get("title") or data.get("type") or data.get("name")
    except (json.JSONDecodeError, TypeError):
        pass
    # snapshot may be a plain string (e.g. software name)
    text = str(snapshot).strip()
    return text if text else None


def _derive_cobrother_request_status(req: CoBrotherRequest, db) -> str:
    """Derive display status from the actual purchase/subscription state.

    Priority order:
    1. CANCELLED / REJECTED  : stored workflow status is terminal
    2. PURCHASED  : purchase confirmed (SoftwarePurchase CONFIRMED or
                    TechnologySubscription ACTIVE)
    3. PENDING    : purchase exists but not yet confirmed/active,
                    OR no purchase record exists at all
    4. FAILED     : payment/registration explicitly failed
    """
    from app.entity.cocreation.software_purchase_entity import SoftwarePurchase
    from app.entity.technology_services.technology_service_entity import (
        TechnologyServiceEntity,
    )
    from app.entity.technology_services.technology_subscription_entity import (
        TechnologySubscriptionEntity,
    )
    from sqlalchemy import or_ as sa_or

    if db is None:
        return req.status.value

    # ── If stored status is already terminal, use it directly ──
    if req.status and req.status.value in ("CANCELLED", "REJECTED"):
        return req.status.value

    entity_id = req.entity_id

    # ── 1) SoftwarePurchase path ──
    #    entity_id = purchase.id  OR  entity_id = software listing ID
    sp = (
        db.query(SoftwarePurchase)
        .filter(
            sa_or(
                SoftwarePurchase.id == entity_id,
                SoftwarePurchase.software_id == entity_id,
            )
        )
        .first()
    )
    if sp is not None:
        payment_val = (
            sp.payment_status.value if hasattr(sp.payment_status, "value")
            else sp.payment_status
        )
        completion_val = (
            sp.completion_status.value if hasattr(sp.completion_status, "value")
            else sp.completion_status
        )
        if payment_val == "COMPLETED" and completion_val == "CONFIRMED":
            return "PURCHASED"
        if payment_val == "FAILED":
            return "FAILED"
        # Payment exists but not yet fully completed — pending
        return "PENDING"

    # ── 2) TechnologySubscription path ──
    #    Try to find the TechnologyServiceEntity by entity_id.
    #    Then match subscription by user_id + service_slug.
    #    If the tech entity was deleted, fall back to user_id + service_name.
    tech = (
        db.query(TechnologyServiceEntity)
        .filter(TechnologyServiceEntity.id == entity_id)
        .first()
    )
    service_slug = getattr(tech, "slug", None) if tech is not None else None

    # Try direct slug match first
    ts = None
    if service_slug and req.lister_id:
        ts = (
            db.query(TechnologySubscriptionEntity)
            .filter(
                TechnologySubscriptionEntity.user_id == str(req.lister_id),
                TechnologySubscriptionEntity.service_slug == service_slug,
            )
            .order_by(TechnologySubscriptionEntity.created_at.desc())
            .first()
        )

    # Fallback: match by service_name from snapshot (for deleted tech entities)
    if ts is None and req.entity_snapshot and req.lister_id:
        snapshot_name = req.entity_snapshot.strip()
        if snapshot_name:
            ts = (
                db.query(TechnologySubscriptionEntity)
                .filter(
                    TechnologySubscriptionEntity.user_id == str(req.lister_id),
                    TechnologySubscriptionEntity.service_name == snapshot_name,
                )
                .order_by(TechnologySubscriptionEntity.created_at.desc())
                .first()
            )

    if ts is not None:
        if ts.status == "ACTIVE" and ts.payment_status == "CAPTURED":
            return "PURCHASED"
        if ts.status in ("CANCELLED", "SUSPENDED"):
            return "FAILED"
        # Subscription exists but not yet active — pending
        return "PENDING"

    # ── 3) No purchase, no subscription found ──
    #    Check if the technology entity still exists in the catalogue.
    #    If NOT found → technology was deleted → CANCELLED.
    #    If found but no subscription → request is still PENDING.
    if tech is None and service_slug is None:
        # Entity not in catalogue — verify it was truly removed
        # (not just a different entity_id type)
        return "CANCELLED"

    return "PENDING"


def serialize_cobrother_request(req: CoBrotherRequest, db=None) -> dict[str, Any]:
    lister = req.lister
    title = _snapshot_title(req.entity_snapshot) or str(req.entity_id)

    status = _derive_cobrother_request_status(req, db)

    return {
        "id": str(req.id),
        "requestType": req.request_type.value,
        "entityId": str(req.entity_id),
        "status": status,
        "entityTitle": title,
        "listerName": (
            f"{lister.firstname or ''} {lister.lastname or ''}".strip() or lister.email
            if lister
            else "—"
        ),
        "listerEmail": lister.email if lister else "—",
        "assignedCoBrother": user_brief(req.assigned_cobrother),
    }


def _iso_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def serialize_domain_enquiry(enquiry: DomainEnquiry) -> dict[str, Any]:
    domain = enquiry.domain_listing
    domain_map: dict[str, Any] | None = None
    if domain is not None:
        domain_map = {
            "domainName": domain.domain_name,
            "domainExtension": domain.domain_extension,
            "askingPrice": domain.asking_price,
            "domainStatus": (
                domain.domain_status.value
                if domain.domain_status is not None and hasattr(domain.domain_status, "value")
                else domain.domain_status
            ),
            "listedBy": user_brief(domain.listed_by),
        }
    return {
        "id": str(enquiry.id),
        "domainListingId": str(enquiry.domain_listing_id),
        "fullName": enquiry.full_name,
        "email": enquiry.email,
        "phone": enquiry.phone,
        "message": enquiry.message,
        "status": enquiry.status,
        "adminNotes": getattr(enquiry, "admin_notes", None),
        "inProgressAt": _iso_datetime(getattr(enquiry, "in_progress_at", None)),
        "completedAt": _iso_datetime(getattr(enquiry, "completed_at", None)),
        "declinedAt": _iso_datetime(getattr(enquiry, "declined_at", None)),
        "createdAt": _iso_datetime(enquiry.created_at),
        "domain": domain_map,
        "isVirtual": False,
    }
