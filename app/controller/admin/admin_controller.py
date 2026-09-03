import uuid

from fastapi import (
    APIRouter,
    Depends,
    status,
)
from fastapi.responses import JSONResponse

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_async_db, get_db

from app.core.dependencies import (
    require_role,
)

from app.entity.user.app_user import AppUser

from app.model.admin.admin_dashboard_response import (
    AdminDashboardResponse
)
from app.model.cocreation.cocreation_request import CreateSoftwareRequest
from app.model.cocreation.cocreation_response import SoftwareResponse
from app.model.cocreation.software_mapper import build_software_response
from app.service.admin.admin_forward_service import forward_to_cobrother
from app.model.marketplace.domain_listing_response import DomainVerificationResponse
from app.service.admin.admin_service import (
    admin_mark_domain_verified,
    admin_mark_domain_unverified,
    admin_mark_technology_verified,
    admin_mark_technology_unverified,
    get_admin_dashboard,
    get_all_cobrothers,
    get_all_cobrother_requests_admin,
    get_all_cocreations_admin,
    get_all_communities_admin,
    get_all_virtual_assistants_homepage_admin,
    get_all_coventures,
    get_all_domains,
    get_all_softwares_admin,
    get_all_ventures_admin,
    restore_listing,
    set_featured,
    take_down_listing,
    toggle_domain_homepage,
    toggle_software_homepage,
    toggle_venture_homepage,
)
from app.service.domain.domain_auction_verification_service import (
    DomainAuctionVerificationService,
)
from app.service.domain.verification_service import DomainVerificationService
from app.service.cocreation.cocreation_service import CocreationService
from app.service.domain.domain_enquiry_service import DomainEnquiryService
from app.service.venture.venture_service import VentureService
from app.model.venture.venture_response import serialize_owner_venture
from pydantic import BaseModel, Field


router = APIRouter(
    prefix="/api/v1/admin",
    tags=["Admin"]
)


@router.get("/cobrothers")
async def all_cobrothers(
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(
        require_role(["ADMIN"])
    ),
):

    return await get_all_cobrothers(
        db=db
    )


@router.get(
    "/dashboard",
    response_model=AdminDashboardResponse
)
async def admin_dashboard(
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(
        require_role(["ADMIN"])
    ),
):

    return await get_admin_dashboard(
        db=db
    )
class TakedownRequest(BaseModel):
    type: str
    entityId: str
    reason: str = ""


class RestoreRequest(BaseModel):
    type: str
    entityId: str


class FeatureRequest(BaseModel):
    type: str
    entityId: str
    featured: str


class ForwardRequest(BaseModel):
    entityId: str
    type: str
    coBrotherId: str | None = None


class DomainVerifyInitBody(BaseModel):
    method: str


class DomainVerifyCheckBody(BaseModel):
    token: str | None = None


async def get_domain_verification_service(
    db: AsyncSession = Depends(get_async_db),
) -> DomainVerificationService:
    return DomainVerificationService(db)


async def get_domain_auction_verification_service(
    db: AsyncSession = Depends(get_async_db),
) -> DomainAuctionVerificationService:
    return DomainAuctionVerificationService(db)


@router.get("/coventures")
async def all_coventures(
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await get_all_coventures(db=db)


@router.get("/domains")
async def all_domains(
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await get_all_domains(db=db)


@router.post("/domains/{listing_id}/mark-verified")
async def admin_mark_domain_verified_endpoint(
    listing_id: uuid.UUID,
    db: Session = Depends(get_db),
    async_db: AsyncSession = Depends(get_async_db),
    admin: AppUser = Depends(require_role(["ADMIN"])),
):
    from app.entity.cobranding.domain_listing_entity import DomainListing
    from app.utils.marketplace_enums import DomainListingVerificationStatus, SaleType

    listing = db.query(DomainListing).filter(DomainListing.id == listing_id).first()
    if listing is not None and not listing.is_deleted and listing.sale_type == SaleType.AUCTION:
        if listing.verification_status == DomainListingVerificationStatus.VERIFIED:
            return {"success": True, "message": "Domain auction is already verified and live."}
        auction_service = DomainAuctionVerificationService(async_db)
        try:
            payload = await auction_service.approve_and_go_live(listing_id, admin=admin)
            return {"success": True, "message": "Domain auction verified and published.", "data": payload}
        except Exception as exc:
            from app.core.exceptions import AppException
            if isinstance(exc, AppException):
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"success": False, "error": exc.message},
                )
            raise

    result = admin_mark_domain_verified(db, listing_id)
    if not result.get("success"):
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=result)
    return result


@router.post("/domains/{listing_id}/mark-unverified")
async def admin_mark_domain_unverified_endpoint(
    listing_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: AppUser = Depends(require_role(["ADMIN"])),
):
    result = admin_mark_domain_unverified(db, listing_id)
    if not result.get("success"):
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=result)
    return result


@router.post("/softwares/{software_id}/mark-verified")
async def admin_mark_technology_verified_endpoint(
    software_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    result = admin_mark_technology_verified(db, software_id)
    if not result.get("success"):
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=result)
    return result


@router.post("/softwares/{software_id}/mark-unverified")
async def admin_mark_technology_unverified_endpoint(
    software_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    result = admin_mark_technology_unverified(db, software_id)
    if not result.get("success"):
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=result)
    return result


@router.post(
    "/domains/{listing_id}/verification/init",
    response_model=DomainVerificationResponse,
)
async def admin_init_domain_verification(
    listing_id: uuid.UUID,
    body: DomainVerifyInitBody,
    service: DomainVerificationService = Depends(get_domain_verification_service),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> DomainVerificationResponse:
    return await service.init_verification(
        listing_id, body.method, actor=None, admin=True
    )


@router.post(
    "/domains/{listing_id}/verification/check",
    response_model=DomainVerificationResponse,
)
async def admin_check_domain_verification(
    listing_id: uuid.UUID,
    body: DomainVerifyCheckBody,
    service: DomainVerificationService = Depends(get_domain_verification_service),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> DomainVerificationResponse:
    return await service.check_verification(
        listing_id, token=body.token, actor=None, admin=True
    )


class DomainVerificationRejectBody(BaseModel):
    reason: str = Field(default="", max_length=2000)


class DomainVerificationRequestInfoBody(BaseModel):
    message: str = Field(default="", max_length=2000)


@router.get("/domains/{listing_id}/verification-review")
async def admin_domain_verification_review(
    listing_id: uuid.UUID,
    service: DomainAuctionVerificationService = Depends(
        get_domain_auction_verification_service
    ),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await service.get_review_payload(listing_id)





@router.post("/domains/{listing_id}/verification/reject")
async def admin_reject_domain_verification(
    listing_id: uuid.UUID,
    body: DomainVerificationRejectBody,
    service: DomainAuctionVerificationService = Depends(
        get_domain_auction_verification_service
    ),
    admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await service.reject_verification(
        listing_id, admin=admin, reason=body.reason
    )


@router.post("/domains/{listing_id}/verification/request-info")
async def admin_request_domain_verification_info(
    listing_id: uuid.UUID,
    body: DomainVerificationRequestInfoBody,
    service: DomainAuctionVerificationService = Depends(
        get_domain_auction_verification_service
    ),
    admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await service.request_more_information(
        listing_id, admin=admin, message=body.message
    )


@router.get("/ventures")
async def all_ventures(
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await get_all_ventures_admin(db=db)


class VentureRejectBody(BaseModel):
    reason: str = Field(default="", max_length=2000)


@router.get("/ventures/pending")
async def pending_ventures(
    db: AsyncSession = Depends(get_async_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    service = VentureService(db)
    ventures = await service.list_pending_approval()
    return [
        serialize_owner_venture(v).model_dump(mode="json", by_alias=True)
        for v in ventures
    ]


@router.post("/ventures/{venture_id}/approve")
async def approve_venture_listing(
    venture_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    service = VentureService(db)
    venture = await service.approve_listing(venture_id, admin=_admin)
    return serialize_owner_venture(venture).model_dump(mode="json", by_alias=True)


@router.post("/ventures/{venture_id}/reject")
async def reject_venture_listing(
    venture_id: uuid.UUID,
    body: VentureRejectBody,
    db: AsyncSession = Depends(get_async_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    service = VentureService(db)
    venture = await service.reject_listing(
        venture_id, admin=_admin, reason=body.reason
    )
    return serialize_owner_venture(venture).model_dump(mode="json", by_alias=True)


@router.post("/ventures/{venture_id}/verification/approve")
async def approve_venture_verification(
    venture_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    service = VentureService(db)
    venture = await service.approve_verification(venture_id, admin=_admin)
    return serialize_owner_venture(venture).model_dump(mode="json", by_alias=True)


@router.post("/ventures/{venture_id}/verification/reject")
async def reject_venture_verification(
    venture_id: uuid.UUID,
    body: VentureRejectBody,
    db: AsyncSession = Depends(get_async_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    service = VentureService(db)
    venture = await service.reject_verification(
        venture_id, admin=_admin, reason=body.reason,
    )
    return serialize_owner_venture(venture).model_dump(mode="json", by_alias=True)


@router.get("/softwares")
async def all_softwares(
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await get_all_softwares_admin(db=db)


@router.get("/communities")
async def all_communities(
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await get_all_communities_admin(db=db)


@router.get("/virtual-assistants")
async def all_virtual_assistants_homepage(
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await get_all_virtual_assistants_homepage_admin(db=db)


@router.get("/technologies")
@router.get("/cocreations")
async def all_cocreations(
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await get_all_cocreations_admin(db=db)


@router.get("/cobrother-requests")
async def all_cobrother_requests(
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await get_all_cobrother_requests_admin(db=db)


@router.post("/takedown")
async def takedown(
    body: TakedownRequest,
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await take_down_listing(db, body.type, body.entityId, body.reason)


@router.post("/restore")
async def restore(
    body: RestoreRequest,
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await restore_listing(db, body.type, body.entityId)


@router.post("/domain/{entity_id}/toggle-homepage")
async def toggle_domain(
    entity_id: str,
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await toggle_domain_homepage(db, entity_id)


@router.post("/venture/{entity_id}/toggle-homepage")
async def toggle_venture(
    entity_id: str,
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await toggle_venture_homepage(db, entity_id)


@router.post("/software/{entity_id}/toggle-homepage")
async def toggle_software(
    entity_id: str,
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await toggle_software_homepage(db, entity_id)


@router.post("/feature")
async def feature_toggle(
    body: FeatureRequest,
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await set_featured(
        db=db,
        entity_type=body.type,
        entity_id=body.entityId,
        featured=str(body.featured).lower() == "true",
    )


@router.get("/domain-enquiries")
async def domain_enquiries_admin(
    db: AsyncSession = Depends(get_async_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    """Java GET /api/v1/admin/domain-enquiries (alias for domain-enquiry/all)."""
    service = DomainEnquiryService(db)
    rows = await service.list_all_admin()
    return {"success": True, "data": rows, "count": len(rows)}


@router.post("/forward")
async def forward_to_cobrother_endpoint(
    body: ForwardRequest,
    db: Session = Depends(get_db),
    admin: AppUser = Depends(require_role(["ADMIN"])),
):
    result = forward_to_cobrother(
        db,
        entity_id=body.entityId,
        request_type=body.type,
        cobrother_id=body.coBrotherId,
        admin=admin,
    )
    if not result.get("success"):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "success": False,
                "error": result.get("error") or "Forward failed",
            },
        )
    return result


@router.post("/cocreation", response_model=SoftwareResponse, status_code=status.HTTP_201_CREATED)
async def create_official_cocreation(
    body: CreateSoftwareRequest,
    db: AsyncSession = Depends(get_async_db),
    admin: AppUser = Depends(require_role(["ADMIN"])),
):
    """Admin-listed official technology / cocreation catalog entry."""
    service = CocreationService(db)
    software = await service.create_official_software(body, admin=admin)
    return build_software_response(software, is_owner=True)


# ─── Permanent Domain Delete (Admin-only) ─────────────────────────────────────

class PermanentDeleteDomainsRequest(BaseModel):
    """Body for permanent domain deletion. Accepts one or more domain IDs."""
    ids: list[str] = Field(..., min_length=1)


@router.post("/domains/permanent-delete")
async def permanent_delete_domains(
    body: PermanentDeleteDomainsRequest,
    db: AsyncSession = Depends(get_async_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    """
    Permanently (hard) delete one or more domain listings from the database.
    Only domains that are currently taken_down=True may be permanently deleted.
    """
    from sqlalchemy import select, delete as sa_delete
    from app.entity.cobranding.domain_listing_entity import DomainListing
    from app.entity.analytics.domain_listing_view import DomainListingView
    from app.entity.user.referral_track import ReferralTrack

    parsed_ids: list[uuid.UUID] = []
    for raw_id in body.ids:
        try:
            parsed_ids.append(uuid.UUID(str(raw_id)))
        except ValueError:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"success": False, "error": f"Invalid domain ID: {raw_id}"},
            )

    # Verify all requested domains are taken down before deleting
    result = await db.execute(
        select(DomainListing).where(DomainListing.id.in_(parsed_ids))
    )
    domains = result.scalars().all()

    not_taken_down = [str(d.id) for d in domains if not d.taken_down]
    if not_taken_down:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "success": False,
                "error": f"The following domain(s) are not taken down and cannot be permanently deleted: {', '.join(not_taken_down)}",
            },
        )

    not_found = len(parsed_ids) - len(domains)
    if not_found > 0:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"success": False, "error": f"{not_found} domain(s) not found."},
        )

    # Explicitly remove dependent records that lack database-level FK cascades.
    await db.execute(
        sa_delete(DomainListingView).where(
            DomainListingView.domain_listing_id.in_(parsed_ids)
        )
    )
    await db.execute(
        sa_delete(ReferralTrack).where(
            ReferralTrack.listing_id.in_(parsed_ids),
            ReferralTrack.listing_type == "domain",
        )
    )

    # Hard delete domain listings (DB cascades remove transactions, enquiries, etc.)
    await db.execute(
        sa_delete(DomainListing).where(DomainListing.id.in_(parsed_ids))
    )
    await db.commit()

    return {"success": True, "deleted": len(parsed_ids)}
