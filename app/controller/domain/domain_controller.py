"""Domain REST controller."""

from __future__ import annotations

import uuid
import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_async_db, get_db
from app.core.dependencies import get_current_user, get_optional_current_user
from app.core.exceptions import AppException
from app.core.route_logging import log_route_exception, request_payload_for_logging
from app.entity.user.app_user import AppUser
from app.model.domain.domain_request import CreateDomainRequest, UpdateDomainRequest
from app.model.domain.domain_response import DomainListResponse, DomainResponse
from app.model.marketplace.domain_listing_request import (
    CreateDomainListingRequest,
    DomainVerificationCheckRequest,
    DomainVerificationInitRequest,
    UpdateDomainListingRequest,
)
from app.model.marketplace.domain_listing_mapper import build_domain_listing_response
from app.model.marketplace.domain_listing_response import (
    DomainListingListResponse,
    DomainListingResponse,
    DomainVerificationOptionsResponse,
    DomainVerificationResponse,
)
from app.service.domain.domain_service import DomainService
from app.service.domain.marketplace_domain_service import MarketplaceDomainService
from app.service.domain.verification_service import DomainVerificationService
from app.service.domain.marketplace_payment_service import MarketplacePaymentService
from app.service.domain.domain_registration_service import DomainRegistrationService
from app.service.domain.showcase_domain_service import ShowcaseDomainService
from app.service.domain.showcase_homepage_integration import ShowcaseHomepageIntegration
from app.service.auction.auction_service import AuctionService
from app.entity.likes.like_type import LikeType
from app.service.likes.like_service import LikeService
from app.model.common.payment_request import RazorpayVerifyRequest
from app.integrations.s3.upload_service import upload_image
from app.integrations.s3.media_helpers import client_media_urls
from app.model.domain.domain_check_response import DomainCheckResponse

router = APIRouter(prefix="/api/v1/domain", tags=["Domains"])
logger = logging.getLogger(__name__)

_ADDON_PRICES = {
    "GST_REGISTRATION": 3000,
    "UDYAM_REGISTRATION": 1500,
    "IEC_REGISTRATION": 2000,
    "DIGITAL_SIGNATURE": 3000,
    "PROFESSIONAL_TAX": 2500,
    "STARTUP_INDIA": 3000,
    "VA_ENTRY_ECOMMERCE": 499,
    "VA_MID_ECOMMERCE": 999,
    "VA_EXPERT_ECOMMERCE": 1999,
}


def _parse_addon_services(services: list) -> tuple[float, str]:
    keys: list[str] = []
    addon_amount = 0.0
    for entry in services or []:
        if isinstance(entry, str):
            keys.append(entry)
            addon_amount += float(_ADDON_PRICES.get(entry, 0))
        elif isinstance(entry, dict):
            key = str(entry.get("key") or entry.get("service") or "")
            if key:
                keys.append(key)
            addon_amount += float(entry.get("price", _ADDON_PRICES.get(key, 0)))
    return addon_amount, ",".join(keys)


def _listing_list_payload(listings: list) -> dict:
    serialized = [
        build_domain_listing_response(d).model_dump(mode="json", by_alias=False)
        for d in listings
    ]
    return {"success": True, "items": serialized, "data": serialized}


async def get_domain_service(
    db: AsyncSession = Depends(get_async_db),
) -> DomainService:
    return DomainService(db)


async def get_marketplace_service(
    db: AsyncSession = Depends(get_async_db),
) -> MarketplaceDomainService:
    return MarketplaceDomainService(db)


async def get_domain_verification_service(
    db: AsyncSession = Depends(get_async_db),
) -> DomainVerificationService:
    return DomainVerificationService(db)


async def get_marketplace_payment_service(
    db: AsyncSession = Depends(get_async_db),
) -> MarketplacePaymentService:
    return MarketplacePaymentService(db)


async def get_registration_service(
    db: AsyncSession = Depends(get_async_db),
) -> DomainRegistrationService:
    return DomainRegistrationService(db)


async def get_auction_service(
    db: AsyncSession = Depends(get_async_db),
) -> AuctionService:
    return AuctionService(db)


# --- Marketplace listings (Java /api/v1/domain parity) -----------------------

@router.get("/all")
async def list_all_domain_listings(
    page: int = Query(1, ge=1),
    page_size: int | None = Query(
        None,
        ge=1,
        le=200,
        description="Omit to return all listings (legacy). Set to paginate.",
    ),
    featured_only: bool = Query(
        False,
        description="When true, return only admin-featured homepage listings.",
    ),
    service: MarketplaceDomainService = Depends(get_marketplace_service),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Public marketplace browse — also returns ``data`` for frontend ``extractDomainList``."""
    total, listings = await service.list_public_page(
        page=page,
        page_size=page_size,
        featured_only=featured_only,
    )
    serialized = [
        build_domain_listing_response(d).model_dump(mode="json", by_alias=False)
        for d in listings
    ]
    for row in serialized:
        row.setdefault("likeCount", 0)
    if featured_only:
        # Isolated OP Showcase → homepage merge (read-only). Selected showcase
        # domains join the existing homepage feed; marketplace listings win on
        # duplicates. Unselected/deleted/unavailable rows are excluded inside.
        integration = ShowcaseHomepageIntegration(db)
        showcase_rows = await integration.fetch_homepage_rows()
        if showcase_rows:
            serialized = integration.merge_into_feed(serialized, showcase_rows)
            total = len(serialized)
    return {
        "success": True,
        "items": serialized,
        "data": serialized,
        "total": total,
        "page": page,
        "page_size": page_size if page_size is not None else total,
    }


@router.get("/showcase")
async def list_openprovider_showcase(
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Public OpenProvider Premium Showcase feed.

    Returns ONLY selected + available showcase rows, and only when the admin
    has enabled the showcase. Never returns candidates. Rows carry
    ``source="openprovider_showcase"`` so the frontend routes purchases through
    the DOMAIN_REGISTRATION flow (never marketplace escrow). No internal
    OpenProvider/commission data is exposed.
    """
    svc = ShowcaseDomainService(db)
    read_only = svc.read_only_mode() or not await svc.table_available()
    items, enabled = await svc.list_public()
    return {
        "success": True,
        "enabled": enabled,
        "readOnly": read_only,
        "items": items,
        "data": items,
        "total": len(items),
    }


@router.get("/check", response_model=DomainCheckResponse)
async def check_domain_availability(
    request: Request,
    domain: str | None = Query(
        None,
        description="Full domain e.g. example.com (new registration)",
    ),
    name: str | None = Query(
        None,
        description="Alias for domain (frontend compat: ?name=example.com)",
    ),
    domain_name: str | None = Query(
        None,
        description="Legacy: label only; requires extension",
    ),
    extension: str = Query(".com", description="Used with domain_name only"),
    mode: Literal["new", "registration"] | None = Query(
        None,
                description="Homepage search mode. mode=new checks new registrations only.",
    ),
    registration_service: DomainRegistrationService = Depends(get_registration_service),
) -> DomainCheckResponse:
    request_payload = await request_payload_for_logging(request)
    try:
        full = (domain or name or "").strip()
        logger.info(
            "Domain check payload received full=%s domain_name=%s extension=%s mode=%s",
            full,
            domain_name,
            extension,
            mode,
        )
        if full:
            if mode == "new":
                response = await registration_service.check_openprovider_domain(full)
            else:
                # Search UX: skip Afternic/Sedo so Standard results stay fast.
                # Checkout/cart still call check_registration_domain with aftermarket.
                response = await registration_service.check_registration_domain(
                    full,
                    include_aftermarket=False,
                )
            logger.info(
                "Domain check response schema ok domain=%s status=%s available=%s",
                response.domain,
                response.status,
                response.status == "available",
            )
            return response
        if domain_name:
            ext = extension if extension.startswith(".") else f".{extension}"
            fqdn = f"{domain_name.strip().lower()}{ext}"
            if mode == "new":
                response = await registration_service.check_openprovider_domain(fqdn)
            else:
                response = await registration_service.check_registration_domain(
                    fqdn,
                    include_aftermarket=False,
                )
            logger.info(
                "Domain check response schema ok domain=%s status=%s available=%s",
                response.domain,
                response.status,
                response.status == "available",
            )
            return response
        raise AppException(
            "Query param 'domain' or 'name' is required (e.g. ?domain=example.com).",
            status_code=400,
        )
    except Exception as exc:
        await log_route_exception(logger, "Domain Check", request, exc, payload=request_payload)
        raise


@router.get("/search")
async def search_homepage_domains(
    mode: Literal["new", "premium", "auction"] = Query(
        ...,
        description="Homepage search source: new, premium, or auction.",
    ),
    query: str | None = Query(None, description="Search text."),
    q: str | None = Query(None, description="Alias for query."),
    name: str | None = Query(None, description="Alias for query."),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    marketplace_service: MarketplaceDomainService = Depends(get_marketplace_service),
    auction_service: AuctionService = Depends(get_auction_service),
    registration_service: DomainRegistrationService = Depends(get_registration_service),
) -> dict:
    search_text = (query or q or name or "").strip()
    if not search_text:
        return {"success": True, "mode": mode, "items": [], "data": []}

    if mode == "new":
        full = search_text.lower()
        if "." not in full:
            full = f"{full}.com"
        result = await registration_service.check_openprovider_domain(full)
        item = result.model_dump(mode="json", by_alias=False)
        return {"success": True, "mode": mode, "items": [item], "data": [item]}

    if mode == "premium":
        listings = await marketplace_service.search_listed_non_auction(search_text)
        serialized = [
            build_domain_listing_response(d).model_dump(mode="json", by_alias=False)
            for d in listings
        ]
        return {"success": True, "mode": mode, "items": serialized, "data": serialized}

    auctions = await auction_service.search_active_enriched(
        search_text,
        page=page,
        page_size=page_size,
    )
    return {"success": True, "mode": mode, "items": auctions, "data": auctions}


@router.get("/search-tlds")
async def search_openprovider_tlds(
    name: str | None = Query(None, description="Bare label e.g. drymotorjosjkm (no extension)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=2000),
    chunk: int | None = Query(
        None,
        ge=0,
        description="Optional 0-based first-page wave for progressive Homepage loading",
    ),
    chunk_size: int = Query(12, ge=1, le=60),
    registration_service: DomainRegistrationService = Depends(get_registration_service),
) -> dict:
    """Return the cheapest available extensions for a label, with pricing."""
    if not name:
        raise AppException("Query param 'name' is required.", status_code=400)
    return await registration_service.search_openprovider_tlds(
        name,
        page=page,
        page_size=page_size,
        chunk=chunk,
        chunk_size=chunk_size,
    )


@router.get("/search-premium")
async def search_premium_marketplace(
    name: str | None = Query(None, description="Bare label e.g. batterify (no extension)"),
    registration_service: DomainRegistrationService = Depends(get_registration_service),
) -> dict:
    """Afternic/Sedo premium marketplace lookup (cached; for background Premium tab)."""
    if not name:
        raise AppException("Query param 'name' is required.", status_code=400)
    return await registration_service.search_premium_marketplace(name)


@router.get("/tlds")
async def list_all_active_tlds(
    registration_service: DomainRegistrationService = Depends(get_registration_service),
) -> dict:
    """Return the complete list of active TLD extensions."""
    from app.integrations.openprovider.client import list_active_tlds
    all_tlds = []
    offset = 0
    while True:
        page = await list_active_tlds(limit=1000, offset=offset)
        all_tlds.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    return {"tlds": [f".{t}" for t in all_tlds]}


@router.get("/my-listings")
async def list_my_domain_listings(
    service: MarketplaceDomainService = Depends(get_marketplace_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return _listing_list_payload(await service.list_my_listings(current_user))


@router.get("/my-purchases")
async def list_my_domain_purchases(
    service: MarketplaceDomainService = Depends(get_marketplace_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    items = await service.list_my_purchases(current_user)
    serialized = [
        build_domain_listing_response(d).model_dump(mode="json", by_alias=False)
        for d in items
    ]
    logger.info(
        "purchases.summary.domain_marketplace user=%s count=%s items=%s",
        current_user.id,
        len(serialized),
        [{"id": str(x.get("id")), "domain_name": x.get("domain_name"), "domain_extension": x.get("domain_extension"), "payment_status": x.get("payment_status"), "domain_status": x.get("domain_status"), "purchased_by_user_id": x.get("purchased_by_user_id")} for x in serialized],
    )
    return {"success": True, "items": serialized, "data": serialized}


@router.post(
    "/listings",
    response_model=DomainListingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_domain_listing(
    payload: CreateDomainListingRequest,
    service: MarketplaceDomainService = Depends(get_marketplace_service),
    current_user: AppUser = Depends(get_current_user),
) -> DomainListingResponse:
    listing = await service.create_listing(payload, lister=current_user)
    return build_domain_listing_response(listing)


from fastapi import APIRouter, Depends, Query, Request

@router.get("/listings/{listing_id}", response_model=DomainListingResponse)
async def get_domain_listing(
    listing_id: uuid.UUID,
    request: Request,
    service: MarketplaceDomainService = Depends(get_marketplace_service),
    current_user: AppUser | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> DomainListingResponse:
    listing = await service.get_listing_and_record_view(
        listing_id,
        viewer=current_user,
        client_ip=request.client.host if request.client else None,
        db=db,
    )
    return build_domain_listing_response(listing)

@router.put("/listings/{listing_id}", response_model=DomainListingResponse)
async def update_domain_listing(
    listing_id: uuid.UUID,
    payload: UpdateDomainListingRequest,
    service: MarketplaceDomainService = Depends(get_marketplace_service),
    current_user: AppUser = Depends(get_current_user),
) -> DomainListingResponse:
    listing = await service.update_listing(listing_id, payload, actor=current_user)
    return build_domain_listing_response(listing)


@router.delete(
    "/listings/{listing_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_domain_listing(
    listing_id: uuid.UUID,
    service: MarketplaceDomainService = Depends(get_marketplace_service),
    current_user: AppUser = Depends(get_current_user),
) -> Response:
    await service.delete_listing(listing_id, actor=current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/verification/options",
    response_model=DomainVerificationOptionsResponse,
)
async def get_domain_verification_options() -> DomainVerificationOptionsResponse:
    return DomainVerificationOptionsResponse(
        whois_email_enabled=settings.domain_verification_whois_email_enabled(),
        recommended_methods=["DNS", "META_TAG"],
    )


@router.post(
    "/listings/{listing_id}/verification/init",
    response_model=DomainVerificationResponse,
)
async def init_domain_verification(
    listing_id: uuid.UUID,
    payload: DomainVerificationInitRequest,
    service: DomainVerificationService = Depends(get_domain_verification_service),
    current_user: AppUser = Depends(get_current_user),
) -> DomainVerificationResponse:
    return await service.init_verification(
        listing_id, payload.method, actor=current_user,
    )


@router.post(
    "/listings/{listing_id}/verification/check",
    response_model=DomainVerificationResponse,
)
async def check_domain_verification(
    listing_id: uuid.UUID,
    payload: DomainVerificationCheckRequest,
    service: DomainVerificationService = Depends(get_domain_verification_service),
    current_user: AppUser = Depends(get_current_user),
) -> DomainVerificationResponse:
    return await service.check_verification(
        listing_id, token=payload.token, actor=current_user,
    )


@router.get("/listings/{listing_id}/verification/confirm")
async def confirm_domain_verification_email(
    listing_id: uuid.UUID,
    token: str = Query(..., min_length=10),
    service: DomainVerificationService = Depends(get_domain_verification_service),
):
    """Email link target — marks listing verified when token matches."""
    await service.confirm_with_token(listing_id, token=token)
    return RedirectResponse(
        url=(
            f"{settings.FRONTEND_BASE_URL.rstrip('/')}"
            "/domains/listings?domainVerified=1"
        ),
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/listings/{listing_id}/purchase/create-order")
async def create_listing_purchase_order(
    listing_id: uuid.UUID,
    body: dict | None = None,
    redeem_points: bool = False,
    service: MarketplacePaymentService = Depends(get_marketplace_payment_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    body = body or {}
    addon_amount, service_keys = _parse_addon_services(body.get("services") or [])
    return await service.create_purchase_order(
        listing_id,
        buyer=current_user,
        buyer_name=str(body.get("buyerName") or body.get("buyerFullName", "")),
        buyer_email=str(body.get("buyerEmail", "")),
        buyer_phone=str(body.get("buyerPhone", "") or current_user.phone_number or ""),
        addon_amount=addon_amount,
        selected_addon_services=service_keys,
        currency=str(body.get("currency") or "INR"),
        redeem_points=redeem_points,
    )


@router.post("/listings/{listing_id}/purchase/verify")
async def verify_listing_purchase(
    listing_id: uuid.UUID,
    body: RazorpayVerifyRequest,
    service: MarketplacePaymentService = Depends(get_marketplace_payment_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.verify_payment(
        listing_id,
        razorpay_payment_id=body.razorpay_payment_id,
        razorpay_order_id=body.razorpay_order_id,
        razorpay_signature=body.razorpay_signature,
        buyer=current_user,
    )


@router.post("/listings/{listing_id}/purchase/failure")
async def listing_purchase_failure(
    listing_id: uuid.UUID,
    service: MarketplacePaymentService = Depends(get_marketplace_payment_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.handle_payment_failure(listing_id)


# --- Auction-eligible owned domains ------------------------------------------


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_domain_unified(
    request: Request,
    marketplace: MarketplaceDomainService = Depends(get_marketplace_service),
    domain_service: DomainService = Depends(get_domain_service),
    current_user: AppUser = Depends(get_current_user),
):
    """Marketplace listing create (body has askingPrice) or auction-domain create."""
    data = await request.json()
    if not isinstance(data, dict):
        raise AppException("JSON body required.", status_code=400)
    if "askingPrice" in data or "asking_price" in data:
        payload = CreateDomainListingRequest.model_validate(data)
        listing = await marketplace.create_listing(payload, lister=current_user)
        return build_domain_listing_response(listing)
    payload = CreateDomainRequest.model_validate(data)
    domain = await domain_service.create_domain(payload, owner=current_user)
    return DomainResponse.model_validate(domain)


@router.get("/my", response_model=DomainListResponse)
async def list_my_domains(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    service: DomainService = Depends(get_domain_service),
    current_user: AppUser = Depends(get_current_user),
) -> DomainListResponse:
    total, items = await service.list_my_domains(
        owner=current_user, page=page, page_size=page_size,
    )
    return DomainListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[DomainResponse.model_validate(d) for d in items],
    )


@router.post("/{listing_id}/image")
async def upload_domain_listing_image(
    listing_id: uuid.UUID,
    file: UploadFile = File(...),
    service: MarketplaceDomainService = Depends(get_marketplace_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    image_url = await upload_image(file=file, folder="domain-logos")
    listing = await service.update_listing_logo(
        listing_id=listing_id,
        logo_url=image_url,
        actor=current_user,
    )
    media = client_media_urls(image_url)
    return {
        "success": True,
        **media,
        "listingId": str(listing.id),
    }


@router.post("/{listing_id}/verify/init", response_model=DomainVerificationResponse)
async def alias_init_verify(
    listing_id: uuid.UUID,
    payload: DomainVerificationInitRequest,
    service: DomainVerificationService = Depends(get_domain_verification_service),
    current_user: AppUser = Depends(get_current_user),
) -> DomainVerificationResponse:
    return await service.init_verification(listing_id, payload.method, actor=current_user)


@router.post("/{listing_id}/verify/check", response_model=DomainVerificationResponse)
async def alias_check_verify(
    listing_id: uuid.UUID,
    payload: DomainVerificationCheckRequest,
    service: DomainVerificationService = Depends(get_domain_verification_service),
    current_user: AppUser = Depends(get_current_user),
) -> DomainVerificationResponse:
    return await service.check_verification(listing_id, token=payload.token, actor=current_user)


@router.post("/{listing_id}/purchase/create-order")
async def alias_purchase_create(
    listing_id: uuid.UUID,
    body: dict | None = None,
    redeem_points: bool = False,
    service: MarketplacePaymentService = Depends(get_marketplace_payment_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    body = body or {}
    addon_amount, service_keys = _parse_addon_services(body.get("services") or [])
    return await service.create_purchase_order(
        listing_id,
        buyer=current_user,
        buyer_name=str(body.get("buyerName") or body.get("buyerFullName", "")),
        buyer_email=str(body.get("buyerEmail", "")),
        buyer_phone=str(body.get("buyerPhone", "") or current_user.phone_number or ""),
        addon_amount=addon_amount,
        selected_addon_services=service_keys,
        redeem_points=redeem_points,
    )


@router.post("/{listing_id}/purchase/verify")
async def alias_purchase_verify(
    listing_id: uuid.UUID,
    body: RazorpayVerifyRequest,
    service: MarketplacePaymentService = Depends(get_marketplace_payment_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.verify_payment(
        listing_id,
        razorpay_payment_id=body.razorpay_payment_id,
        razorpay_order_id=body.razorpay_order_id,
        razorpay_signature=body.razorpay_signature,
        buyer=current_user,
    )


@router.post("/{listing_id}/purchase/failure")
async def alias_purchase_failure(
    listing_id: uuid.UUID,
    service: MarketplacePaymentService = Depends(get_marketplace_payment_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.handle_payment_failure(listing_id)


@router.get("/{domain_id}", response_model=DomainResponse | DomainListingResponse)
async def get_domain_unified(
    domain_id: uuid.UUID,
    request: Request,
    marketplace: MarketplaceDomainService = Depends(get_marketplace_service),
    domain_service: DomainService = Depends(get_domain_service),
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        listing = await marketplace.get_listing_and_record_view(
            domain_id,
            viewer=current_user,
            client_ip=request.client.host if request.client else None,
            db=db,
        )
        return build_domain_listing_response(listing)
    except AppException as exc:
        if exc.status_code != 404:
            raise
    domain = await domain_service.get_domain(domain_id, actor=current_user)
    return DomainResponse.model_validate(domain)


@router.put("/{domain_id}", response_model=DomainResponse | DomainListingResponse)
async def update_domain_unified(
    domain_id: uuid.UUID,
    request: Request,
    marketplace: MarketplaceDomainService = Depends(get_marketplace_service),
    domain_service: DomainService = Depends(get_domain_service),
    current_user: AppUser = Depends(get_current_user),
):
    data = await request.json()
    if not isinstance(data, dict):
        raise AppException("JSON body required.", status_code=400)
    try:
        await marketplace.get_listing(domain_id)
        payload = UpdateDomainListingRequest.model_validate(data)
        listing = await marketplace.update_listing(domain_id, payload, actor=current_user)
        return build_domain_listing_response(listing)
    except AppException as exc:
        if exc.status_code != 404:
            raise
    payload = UpdateDomainRequest.model_validate(data)
    domain = await domain_service.update_domain(domain_id, payload, actor=current_user)
    return DomainResponse.model_validate(domain)


@router.delete(
    "/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_domain_unified(
    domain_id: uuid.UUID,
    marketplace: MarketplaceDomainService = Depends(get_marketplace_service),
    domain_service: DomainService = Depends(get_domain_service),
    current_user: AppUser = Depends(get_current_user),
) -> Response:
    try:
        await marketplace.get_listing(domain_id)
        await marketplace.delete_listing(domain_id, actor=current_user)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except AppException as exc:
        if exc.status_code != 404:
            raise
    await domain_service.soft_delete_domain(domain_id, actor=current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


