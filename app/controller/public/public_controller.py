from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
import uuid
from html import escape
from sqlalchemy import select

from app.core.config import settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_async_db, get_db
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.cocreation.software_entity import Software
from app.entity.coventure.venture_entity import Venture
from app.entity.user.app_user import AppUser
from app.entity.auction.auction_entity import Auction
from app.entity.community.community_auction import CommunityAuction
from app.entity.cocreation.software_auction import SoftwareAuction
from app.entity.coventure.venture_deal_transaction_entity import VentureDealTransaction
from app.utils.venture_enums import VentureListingApprovalStatus
from app.model.common.api_response import ApiResponse
from app.model.venture.venture_response import serialize_public_venture
from app.integrations.s3.supabase_storage import resolve_media_url
from app.service.community.community_service import CommunityService
from app.utils.cocreation_enums import SoftwareStatus
from app.utils.marketplace_enums import DomainListingStatus

router = APIRouter(prefix="/public/api/v1", tags=["Public"])
config_router = APIRouter(prefix="/api/v1/public", tags=["Public"])


@config_router.get("/bot-protection")
async def bot_protection_config():
    return {
        "turnstileEnabled": settings.turnstile_enabled(),
        "turnstileSiteKey": (
            settings.TURNSTILE_SITE_KEY if settings.turnstile_enabled() else ""
        ),
    }


@router.get("/domains")
async def get_public_domains(db: AsyncSession = Depends(get_async_db)):
    stmt = (
        select(DomainListing)
        .where(
            DomainListing.is_deleted.is_(False),
            DomainListing.taken_down.is_(False),
            DomainListing.domain_status.in_(
                (
                    DomainListingStatus.AVAILABLE,
                    DomainListingStatus.UNDER_REVIEW,
                )
            ),
        )
        .order_by(DomainListing.created_at.desc())
        .limit(50)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "domainName": r.domain_name,
            "domainExtension": r.domain_extension,
            "askingPrice": float(r.asking_price),
            "domainStatus": (
                r.domain_status.value if hasattr(r.domain_status, "value") else r.domain_status
            ),
            "logo": resolve_media_url(r.logo),
            "logoUrl": resolve_media_url(r.logo),
            "imageUrl": resolve_media_url(r.logo),
        }
        for r in rows
    ]


@router.get("/ventures")
async def get_public_ventures(db: AsyncSession = Depends(get_async_db)):
    stmt = (
        select(Venture)
        .where(
            Venture.is_deleted.is_(False),
            Venture.taken_down.is_(False),
            Venture.status.is_(True),
            Venture.listing_approval_status == VentureListingApprovalStatus.APPROVED,
        )
        .options(
            selectinload(Venture.brand_details),
            selectinload(Venture.listed_by),
            selectinload(Venture.roles),
        )
        .order_by(Venture.created_at.desc())
        .limit(50)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [serialize_public_venture(v).model_dump(by_alias=True) for v in rows]


@router.get("/softwares")
async def get_public_softwares(db: AsyncSession = Depends(get_async_db)):
    stmt = (
        select(Software)
        .where(
            Software.is_deleted.is_(False),
            Software.taken_down.is_(False),
            Software.status.is_(True),
            Software.software_status == SoftwareStatus.AVAILABLE,
        )
        .order_by(Software.created_at.desc())
        .limit(50)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "price": float(r.price),
            "imageUrl": resolve_media_url(r.image_url),
            "category": r.category.value if r.category else None,
        }
        for r in rows
    ]


@router.get("/communities", response_model=ApiResponse)
def get_public_communities(db: Session = Depends(get_db)):
    profiles = CommunityService.get_all_profiles(db)
    return ApiResponse(
        success=True,
        message="Creator profiles fetched successfully",
        data=profiles,
    )


@config_router.api_route("/share-preview/s/{token}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def get_share_token_preview(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_async_db)
):
    """Social/crawler preview for tokenized share links (``/s/{token}``).

    Serves Open Graph / Twitter meta tags and redirects real users to the SPA.
    Registered BEFORE the generic ``/share-preview/{listing_type}/{listing_id}``
    route so the literal ``s`` segment never falls through to UUID parsing.
    """
    from app.service.share.share_service import ShareService, frontend_share_base_for_request

    share = await ShareService(db).resolve_share(token)
    title = "HubRegistrar"
    description = "Check out this shared domain on HubRegistrar!"
    share_base = frontend_share_base_for_request(request)
    page_url = f"{share_base}/s/{token}"
    image_url = f"{share_base}/favicon.png"

    if share and share.domain:
        # Rich OG metadata uses the SAME live Standard/Premium classification
        # as the shared page (build_preview_payload + aftermarket probe). No
        # internal data is ever exposed — only the domain, search context and
        # premium wording.
        meta = await ShareService(db).build_og_meta(share)
        title = meta["title"]
        description = meta["description"]

    # Escape anything user-origin (share domain / original query / premium
    # wording) so a malicious query can never break out of the meta attributes.
    title = escape(title)
    description = escape(description)
    page_url = escape(page_url)
    image_url = escape(image_url)

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{page_url}">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:image" content="{image_url}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:site_name" content="HubRegistrar">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:url" content="{page_url}">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{description}">
  <meta name="twitter:image" content="{image_url}">
</head>
<body>
  <script type="text/javascript">
    window.location.href = "{page_url}";
  </script>
  <p>Redirecting you to HubRegistrar: <a href="{page_url}">{title}</a>...</p>
</body>
</html>
"""
    if request.method == "HEAD":
        return HTMLResponse(
            content="",
            status_code=200,
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "Content-Length": str(len(html_content.encode("utf-8"))),
            },
        )
    return HTMLResponse(content=html_content, status_code=200)


@config_router.api_route("/share-preview/{listing_type}/{listing_id}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def get_share_preview(
    listing_type: str,
    listing_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_db)
):
    try:
        uuid_id = uuid.UUID(listing_id)
    except ValueError:
        return HTMLResponse(content="<h1>Invalid listing ID</h1>", status_code=400)

    title = "HubRegistrar"
    description = "Check out this premium listing on HubRegistrar!"
    image_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/favicon.png"
    page_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/"

    listing_type = listing_type.lower()

    if listing_type == "domains":
        stmt = select(DomainListing).where(DomainListing.id == uuid_id)
        res = (await db.execute(stmt)).scalar_one_or_none()
        if res:
            title = f"{res.domain_name}{res.domain_extension} | HubRegistrar"
            description = "Check out this premium Domain listed on HubRegistrar!"
            page_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/domains/{listing_id}"

    elif listing_type == "ventures":
        stmt = (
            select(Venture)
            .where(Venture.id == uuid_id)
            .options(selectinload(Venture.brand_details))
        )
        res = (await db.execute(stmt)).scalar_one_or_none()
        if res:
            brand_name = res.brand_details.brand_name if res.brand_details else "Venture"
            title = f"{brand_name} | HubRegistrar"
            desc = res.brand_details.description if res.brand_details else ""
            type_lbl = "Co-Venture" if res.sale_type.value == "CO_VENTURE" else "Venture"
            description = f"Check out this exciting {type_lbl} opportunity on HubRegistrar! {desc}".strip()
            if res.brand_details and res.brand_details.venture_image_url:
                image_url = resolve_media_url(res.brand_details.venture_image_url)
            page_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/ventures/{listing_id}"

    elif listing_type == "technology":
        stmt = select(Software).where(Software.id == uuid_id)
        res = (await db.execute(stmt)).scalar_one_or_none()
        if res:
            title = f"{res.name} | HubRegistrar"
            description = f"Check out this premium Technology listed on HubRegistrar! {res.description or ''}".strip()
            if res.image_url:
                image_url = resolve_media_url(res.image_url)
            page_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/technology/{listing_id}"

    elif listing_type == "auction":
        stmt = (
            select(Auction)
            .where(Auction.id == uuid_id)
            .options(selectinload(Auction.domain))
        )
        res = (await db.execute(stmt)).scalar_one_or_none()
        if res and res.domain:
            title = f"{res.domain.domain_name} | HubRegistrar"
            description = f"Check out this domain Auction on HubRegistrar! {res.domain.description or ''}".strip()
            page_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/auction/{listing_id}"

    elif listing_type in ("creator-auction", "community-auction"):
        stmt = (
            select(CommunityAuction)
            .where(CommunityAuction.id == uuid_id)
            .options(selectinload(CommunityAuction.community))
        )
        res = (await db.execute(stmt)).scalar_one_or_none()
        if res:
            title = f"{res.auction_title} | HubRegistrar"
            description = f"Check out this Creator Auction on HubRegistrar! {res.additional_info or ''}".strip()
            if res.community and res.community.image_url:
                image_url = resolve_media_url(res.community.image_url)
            page_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/creator-auction/{listing_id}"

    elif listing_type in ("technology-auction", "software-auction"):
        stmt = (
            select(SoftwareAuction)
            .where(SoftwareAuction.id == uuid_id)
            .options(selectinload(SoftwareAuction.software))
        )
        res = (await db.execute(stmt)).scalar_one_or_none()
        if res and res.software:
            title = f"{res.software.name} | HubRegistrar"
            description = f"Check out this Technology Auction on HubRegistrar! {res.software.description or ''}".strip()
            if res.software.image_url:
                image_url = resolve_media_url(res.software.image_url)
            page_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/technology/auction/{listing_id}"

    elif listing_type in ("deals", "venture-deals"):
        stmt = (
            select(VentureDealTransaction)
            .where(VentureDealTransaction.id == uuid_id)
            .options(selectinload(VentureDealTransaction.venture).selectinload(Venture.brand_details))
        )
        res = (await db.execute(stmt)).scalar_one_or_none()
        if res and res.venture:
            brand_name = res.venture.brand_details.brand_name if res.venture.brand_details else "Venture Deal"
            title = f"{brand_name} Deal | HubRegistrar"
            desc = res.venture.brand_details.description if res.venture.brand_details else ""
            description = f"Check out this Venture Deal transaction on HubRegistrar! {desc}".strip()
            if res.venture.brand_details and res.venture.brand_details.venture_image_url:
                image_url = resolve_media_url(res.venture.brand_details.venture_image_url)
            page_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/ventures/deals/{listing_id}"

    if image_url.startswith("/"):
        image_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}{image_url}"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <meta name="description" content="{description}">
  
  <!-- Open Graph / Facebook -->
  <meta property="og:type" content="website">
  <meta property="og:url" content="{page_url}">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:image" content="{image_url}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:site_name" content="HubRegistrar">

  <!-- Twitter -->
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:url" content="{page_url}">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{description}">
  <meta name="twitter:image" content="{image_url}">

</head>
<body>
  <!-- Automatically redirect real users to the frontend listing page -->
  <script type="text/javascript">
    window.location.href = "{page_url}";
  </script>
  <p>Redirecting you to HubRegistrar listing: <a href="{page_url}">{title}</a>...</p>
</body>
</html>
"""
    if request.method == "HEAD":
        return HTMLResponse(
            content="",
            status_code=200,
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "Content-Length": str(len(html_content.encode("utf-8"))),
            }
        )
    return HTMLResponse(content=html_content, status_code=200)
