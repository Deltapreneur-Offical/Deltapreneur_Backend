"""Map DomainListing ORM rows to API responses."""

from __future__ import annotations

from app.entity.cobranding.domain_listing_entity import DomainListing
from app.integrations.s3.supabase_storage import resolve_media_url
from app.model.marketplace.domain_listing_response import DomainListingResponse
from app.model.user.public_user import to_public_user
from app.model.venture.venture_response import AgreementResponse, ContactInfoResponse
from app.utils.domain_gst import domain_price_breakdown
from app.utils.listing_commission import compute_listing_commission
from app.utils.marketplace_enums import DomainListingVerificationStatus

ADMIN_ROLES = {"ADMIN", "ROLE_ADMIN", "COBROTHER", "ROLE_COBROTHER", "SUPER_ADMIN", "ROLE_SUPER_ADMIN"}


def build_domain_listing_response(listing: DomainListing) -> DomainListingResponse:
    contact = None
    if listing.contact_info is not None:
        contact = ContactInfoResponse(
            id=listing.contact_info.id,
            email=listing.contact_info.email,
            phone_number=listing.contact_info.phone_number,
        )
    agreement = None
    if listing.agreement is not None:
        agreement = AgreementResponse(
            id=listing.agreement.id,
            terms=bool(listing.agreement.terms),
        )
    listed_by = (
        to_public_user(listing.listed_by) if listing.listed_by is not None else None
    )
    listed_by_role_raw = getattr(listing.listed_by, "role", None) if listing.listed_by is not None else None
    if hasattr(listed_by_role_raw, "value"):
        listed_by_role = str(listed_by_role_raw.value).upper()
    else:
        listed_by_role = str(listed_by_role_raw or "").upper()
    admin_listed = bool(
        listed_by is not None
        and (listed_by_role in ADMIN_ROLES or listed_by_role.replace("ROLE_", "") in ADMIN_ROLES)
    )
    listing_price = listing.asking_price
    seller_payout_amount = getattr(listing, "seller_payout_amount", None)
    commission_amount = getattr(listing, "commission_amount", None)
    commission_percent = getattr(listing, "commission_percentage", None)
    if seller_payout_amount is None and listing_price and listing_price > 0 and commission_percent is not None:
        seller_payout_amount, commission_amount, listing_price = compute_listing_commission(
            float(listing_price),
            float(commission_percent),
        )

    asking = float(listing.asking_price or 0)
    gst_payload = domain_price_breakdown(asking, years=1) if asking > 0 else None

    return DomainListingResponse(
        id=listing.id,
        domain_name=listing.domain_name,
        domain_extension=listing.domain_extension,
        domain_category=listing.domain_category,
        asking_price=listing_price,
        seller_price=seller_payout_amount,
        listing_price=listing_price,
        commission_percentage=commission_percent,
        commission_amount=commission_amount,
        seller_payout_amount=seller_payout_amount,
        platform_commission_percent=commission_percent,
        platform_commission_amount=commission_amount,
        final_listing_price=listing_price,
        gst_inr=float(gst_payload["gstInr"]) if gst_payload else None,
        gst_rate=gst_payload.get("gstRate") if gst_payload else None,
        gst_enabled=bool(gst_payload["gstEnabled"]) if gst_payload else False,
        buyer_payable_inr=float(gst_payload["totalInr"]) if gst_payload else None,
        pricing_demand=listing.pricing_demand,
        domain_status=listing.domain_status,
        logo=resolve_media_url(listing.logo),
        logo_text=getattr(listing, 'logo_text', None),
        status=listing.status,
        views=listing.views,
        payment_status=listing.payment_status,
        purchased_by_user_id=listing.purchased_by_user_id,
        sold_at=listing.sold_at,
        verified=listing.verified,
        verification_method=listing.verification_method,
        verified_at=listing.verified_at,
        whois_email=listing.whois_email,
        verification_status=getattr(listing, "verification_status", None)
        or DomainListingVerificationStatus.PENDING,
        sale_type=listing.sale_type,
        featured=listing.featured,
        admin_listed=admin_listed,
        taken_down=listing.taken_down,
        take_down_reason=listing.take_down_reason,
        created_at=listing.created_at,
        updated_at=listing.updated_at,
        contact_info=contact,
        agreement=agreement,
        listed_by=listed_by,
        listed_by_user_id=listing.listed_by_user_id,
    )
