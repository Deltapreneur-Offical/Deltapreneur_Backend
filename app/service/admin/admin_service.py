from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.entity.analytics.profile_view import ProfileView
from app.entity.analytics.venture_view import VentureView
from app.entity.cobrother.cobrother_request_entity import CoBrotherRequest
from app.entity.auction.auction_entity import Auction
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.cocreation.software_auction import SoftwareAuction
from app.entity.cocreation.software_entity import Software
from app.entity.community.community import Community
from app.entity.community.community_auction import CommunityAuction
from app.entity.virtual_assistant.virtual_assistant_entity import VirtualAssistantApplication
from app.entity.coventure.partner_entity import CoVenture
from app.entity.coventure.venture_acquisition_application_entity import (
    VentureAcquisitionApplication,
)
from app.entity.coventure.venture_entity import Venture
from app.utils.community_profile_completion import is_profile_complete
from app.utils.marketplace_enums import DomainListingVerificationStatus, SaleType
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.repository.user_repository import UserRepository
from app.utils.enums import AuctionStatus
from app.service.admin.admin_serializers import (
    serialize_cobrother_request,
    serialize_coventure,
    serialize_community_admin,
    serialize_domain,
    serialize_technology_listing,
    serialize_venture_admin,
)


def _fetch_non_deleted_communities(db: Session) -> list[Community]:
    return (
        db.execute(
            select(Community)
            .where(Community.is_deleted.is_(False))
            .options(joinedload(Community.app_user))
            .order_by(Community.created_at.desc())
        )
        .unique()
        .scalars()
        .all()
    )


def _count_listable_creators(db: Session) -> int:
    return sum(1 for community in _fetch_non_deleted_communities(db) if is_profile_complete(community))


async def get_all_cobrothers(db: Session):
    users = UserRepository.find_by_role(db=db, role=UserRole.COBROTHER)
    return {
        "success": True,
        "count": len(users),
        "data": [
            {
                "id": str(user.id),
                "firstname": user.firstname,
                "lastname": user.lastname,
                "email": user.email,
                "role": user.role.value,
            }
            for user in users
        ],
    }


async def get_admin_dashboard(db: Session):
    total_users = db.query(func.count(AppUser.id)).filter(AppUser.is_deleted.is_(False)).scalar()
    total_cobrothers = (
        db.query(func.count(AppUser.id))
        .filter(AppUser.role == UserRole.COBROTHER, AppUser.is_deleted.is_(False))
        .scalar()
    )
    total_venture_views = db.query(func.count(VentureView.id)).filter(VentureView.is_deleted.is_(False)).scalar()
    total_profile_views = db.query(func.count(ProfileView.id)).filter(ProfileView.is_deleted.is_(False)).scalar()
    total_ventures = (
        db.query(func.count(Venture.id))
        .filter(Venture.is_deleted.is_(False))
        .scalar()
    )
    total_domains = (
        db.query(func.count(DomainListing.id))
        .filter(DomainListing.is_deleted.is_(False))
        .scalar()
    )
    total_technologies = (
        db.query(func.count(Software.id))
        .filter(Software.is_deleted.is_(False))
        .scalar()
    )
    total_creators = _count_listable_creators(db)
    return {
        "success": True,
        "data": {
            "totalUsers": total_users,
            "totalCoBrothers": total_cobrothers,
            "totalVentureViews": total_venture_views,
            "totalProfileViews": total_profile_views,
            "totalVentures": total_ventures,
            "totalDomains": total_domains,
            "totalTechnologies": total_technologies,
            "totalCreators": total_creators,
        },
    }


async def get_all_coventures(db: Session):
    rows = (
        db.execute(
            select(CoVenture)
            .options(
                joinedload(CoVenture.venture).joinedload(Venture.brand_details),
                joinedload(CoVenture.venture).joinedload(Venture.listed_by),
                joinedload(CoVenture.applicant),
            )
            .order_by(CoVenture.created_at.desc())
        )
        .unique()
        .scalars()
        .all()
    )
    data = [serialize_coventure(r) for r in rows]
    return {"success": True, "count": len(data), "data": data}


async def get_all_domains(db: Session):
    """All marketplace domain listings for admin (excludes soft-deleted rows)."""
    rows = (
        db.execute(
            select(DomainListing)
            .where(DomainListing.is_deleted.is_(False))
            .options(
                joinedload(DomainListing.listed_by),
                joinedload(DomainListing.verified_by),
            )
            .order_by(DomainListing.created_at.desc())
        )
        .unique()
        .scalars()
        .all()
    )
    purchaser_ids = [r.purchased_by_user_id for r in rows if r.purchased_by_user_id]
    purchasers: dict[str, AppUser] = {}
    if purchaser_ids:
        for user in db.query(AppUser).filter(AppUser.id.in_(purchaser_ids)).all():
            purchasers[str(user.id)] = user

    listing_ids = [r.id for r in rows]
    auctions_by_listing: dict = {}
    if listing_ids:
        auction_rows = (
            db.execute(
                select(Auction)
                .where(
                    Auction.domain_id.in_(listing_ids),
                    Auction.is_deleted.is_(False),
                )
                .order_by(Auction.created_at.desc())
            )
            .scalars()
            .all()
        )
        for auction in auction_rows:
            if auction.domain_id not in auctions_by_listing:
                auctions_by_listing[auction.domain_id] = auction

    data = [
        serialize_domain(
            r,
            purchasers=purchasers,
            auction=auctions_by_listing.get(r.id),
        )
        for r in rows
    ]
    return {"success": True, "count": len(data), "data": data, "items": data}


async def get_all_ventures_admin(db: Session):
    rows = (
        db.execute(
            select(Venture)
            .where(Venture.is_deleted.is_(False))
            .options(
                joinedload(Venture.brand_details),
                joinedload(Venture.listed_by),
                joinedload(Venture.company_profile),
                selectinload(Venture.co_venture_applications).selectinload(
                    CoVenture.applicant,
                ),
                selectinload(Venture.pitches).selectinload(
                    VentureAcquisitionApplication.buyer,
                ),
            )
            .order_by(Venture.created_at.desc())
        )
        .unique()
        .scalars()
        .all()
    )
    data = [serialize_venture_admin(r) for r in rows]
    return {"success": True, "count": len(data), "data": data, "items": data}


def admin_mark_domain_verified(db: Session, listing_id: UUID) -> dict:
    listing = db.query(DomainListing).filter(DomainListing.id == listing_id).first()
    if listing is None or listing.is_deleted:
        return {"success": False, "error": "Domain listing not found"}
    now = datetime.now(timezone.utc)
    listing.verified = True
    listing.verified_at = now
    listing.verification_token = None
    listing.updated_at = now
    if listing.sale_type != SaleType.AUCTION:
        listing.verification_status = DomainListingVerificationStatus.VERIFIED
    db.commit()

    if listing.listed_by_user_id:
        from app.entity.user.app_user import AppUser
        from app.entity.notification.notification_type import NotificationType
        from app.service.notification.notification_service import NotificationService

        owner = db.query(AppUser).filter(AppUser.id == listing.listed_by_user_id).first()
        if owner:
            label = f"{listing.domain_name}{listing.domain_extension}".strip()
            try:
                NotificationService.notify(
                    db=db,
                    user=owner,
                    notification_type=NotificationType.DOMAIN_VERIFIED,
                    title="Domain verified",
                    message=f"{label} is now verified and available for purchase.",
                    target_url=f"/domains?id={listing.id}",
                )
            except Exception:
                pass

    return {"success": True, "message": "Domain marked as verified."}


def admin_mark_domain_unverified(db: Session, listing_id: UUID) -> dict:
    from app.utils.marketplace_enums import DomainListingVerificationStatus, SaleType
    listing = db.query(DomainListing).filter(DomainListing.id == listing_id).first()
    if listing is None or listing.is_deleted:
        return {"success": False, "error": "Domain listing not found"}
    now = datetime.now(timezone.utc)
    listing.verified = False
    listing.verified_at = None
    listing.updated_at = now
    if listing.sale_type != SaleType.AUCTION:
        listing.verification_status = DomainListingVerificationStatus.PENDING
    db.commit()

    return {"success": True, "message": "Domain marked as unverified."}


def admin_mark_technology_verified(db: Session, software_id: UUID) -> dict:
    software = db.query(Software).filter(Software.id == software_id).first()
    if software is None or software.is_deleted:
        return {"success": False, "error": "Technology listing not found"}
    now = datetime.now(timezone.utc)
    software.verified = True
    software.verified_at = now
    software.updated_at = now
    db.commit()

    if software.listed_by_user_id:
        from app.entity.user.app_user import AppUser
        from app.entity.notification.notification_type import NotificationType
        from app.service.notification.notification_service import NotificationService

        owner = db.query(AppUser).filter(AppUser.id == software.listed_by_user_id).first()
        if owner:
            try:
                NotificationService.notify(
                    db=db,
                    user=owner,
                    notification_type=NotificationType.TECHNOLOGY_VERIFIED,
                    title="Technology listing verified",
                    message=f"{software.name} is now verified and available for purchase.",
                    target_url=f"/technology?id={software.id}",
                )
            except Exception:
                pass

    return {"success": True, "message": "Technology listing marked as verified."}


def admin_mark_technology_unverified(db: Session, software_id: UUID) -> dict:
    software = db.query(Software).filter(Software.id == software_id).first()
    if software is None or software.is_deleted:
        return {"success": False, "error": "Technology listing not found"}
    now = datetime.now(timezone.utc)
    software.verified = False
    software.verified_at = None
    # Drop homepage pin so it leaves Featured Technologies immediately.
    software.featured = False
    software.updated_at = now
    db.commit()
    return {
        "success": True,
        "message": "Technology listing marked as unverified and removed from homepage features.",
        "featured": False,
        "verified": False,
    }


async def get_all_softwares_admin(db: Session):
    rows = (
        db.execute(
            select(Software)
            .where(Software.is_deleted.is_(False))
            .options(joinedload(Software.listed_by))
            .order_by(Software.created_at.desc())
        )
        .unique()
        .scalars()
        .all()
    )
    data = [serialize_technology_listing(r) for r in rows]
    return {"success": True, "count": len(data), "data": data, "items": data}


async def get_all_communities_admin(db: Session):
    rows = _fetch_non_deleted_communities(db)
    data = [serialize_community_admin(r) for r in rows if is_profile_complete(r)]
    return {"success": True, "count": len(data), "data": data, "items": data}


async def get_all_virtual_assistants_homepage_admin(db: Session):
    """Published, approved VA profiles eligible for homepage featuring."""
    from app.service.admin.virtual_assistant_admin_service import VirtualAssistantAdminService

    query = VirtualAssistantAdminService.apply_public_marketplace_filters(
        db.query(VirtualAssistantApplication)
    )
    rows = query.order_by(VirtualAssistantApplication.full_name.asc()).all()
    for row in rows:
        VirtualAssistantAdminService._ensure_roles(db, row)
    data = [VirtualAssistantAdminService._serialize_public(db, row) for row in rows]
    return {"success": True, "count": len(data), "data": data, "items": data}


async def get_all_cocreations_admin(db: Session):
    """All technology/software listings for admin Technology tab (Java findAll parity)."""
    return await get_all_softwares_admin(db=db)


async def get_all_cobrother_requests_admin(db: Session):
    rows = (
        db.execute(
            select(CoBrotherRequest)
            .options(
                joinedload(CoBrotherRequest.lister),
                joinedload(CoBrotherRequest.assigned_cobrother),
            )
            .order_by(CoBrotherRequest.created_at.desc())
        )
        .unique()
        .scalars()
        .all()
    )
    data = [serialize_cobrother_request(r, db) for r in rows]
    return {"success": True, "count": len(data), "data": data}


def _venture_for_takedown(db: Session, entity_type: str, entity_id: UUID) -> Venture | None:
    """Resolve VENTURE or COVENTURE admin actions to the underlying venture row."""
    et = entity_type.upper()
    if et == "VENTURE":
        return db.query(Venture).filter(Venture.id == entity_id).first()
    if et == "COVENTURE":
        cv = db.query(CoVenture).filter(CoVenture.id == entity_id).first()
        if cv is None:
            return None
        return db.query(Venture).filter(Venture.id == cv.venture_id).first()
    return None


async def take_down_listing(db: Session, entity_type: str, entity_id: str, reason: str = ""):
    uid = UUID(entity_id)
    now = datetime.now(timezone.utc)
    et = entity_type.upper()

    venture = _venture_for_takedown(db, et, uid)
    if venture is not None:
        venture.taken_down = True
        venture.take_down_reason = reason or venture.take_down_reason
        venture.status = False
        venture.updated_at = now
        db.commit()
        return {"success": True}

    if et == "DOMAIN":
        row = db.query(DomainListing).filter(DomainListing.id == uid).first()
        if not row:
            return {"success": False, "error": "Entity not found"}
        row.taken_down = True
        row.take_down_reason = reason or row.take_down_reason
        row.status = False
        row.updated_at = now
        
        # Cancel active domain auction if it exists
        auction = db.query(Auction).filter(
            Auction.domain_id == uid,
            Auction.status.in_([AuctionStatus.ACTIVE, AuctionStatus.EXTENDED])
        ).first()
        if auction:
            auction.status = AuctionStatus.CANCELLED
            auction.end_time = now
            auction.updated_at = now

        db.commit()
        return {"success": True}

    if et in ("SOFTWARE", "COCREATION"):
        row = db.query(Software).filter(Software.id == uid).first()
        if not row:
            return {"success": False, "error": "Entity not found"}
        row.taken_down = True
        row.take_down_reason = reason or row.take_down_reason
        row.status = False
        row.updated_at = now
        
        # Cancel active software auction if it exists
        auction = db.query(SoftwareAuction).filter(
            SoftwareAuction.software_id == uid,
            SoftwareAuction.status.in_([AuctionStatus.ACTIVE, AuctionStatus.EXTENDED])
        ).first()
        if auction:
            auction.status = AuctionStatus.CANCELLED
            auction.end_time = now
            auction.updated_at = now

        db.commit()
        return {"success": True}

    if et in ("COMMUNITY_AUCTION", "CREATOR_AUCTION"):
        from app.service.community.community_auction_service import CommunityAuctionService
        row = db.query(CommunityAuction).filter(CommunityAuction.id == uid).first()
        if not row:
            return {"success": False, "error": "Entity not found"}
        row.status = "CLOSED"
        row.updated_at = now
        db.commit()
        try:
            CommunityAuctionService._broadcast_auction_event(
                row.id,
                CommunityAuctionService._build_auction_ended_event(
                    row,
                    event_type="AUCTION_CLOSED",
                    message="Auction closed by admin.",
                ),
            )
            CommunityAuctionService._broadcast_profile_sync(
                row,
                "creator_auction_ended",
            )
        except Exception:
            pass
        return {"success": True}

    return {"success": False, "error": f"Unsupported type: {entity_type}"}


async def restore_listing(db: Session, entity_type: str, entity_id: str):
    uid = UUID(entity_id)
    now = datetime.now(timezone.utc)
    et = entity_type.upper()

    venture = _venture_for_takedown(db, et, uid)
    if venture is not None:
        venture.taken_down = False
        venture.take_down_reason = None
        venture.status = True
        venture.updated_at = now
        db.commit()
        return {"success": True}

    if et == "DOMAIN":
        row = db.query(DomainListing).filter(DomainListing.id == uid).first()
        if not row:
            return {"success": False, "error": "Entity not found"}
        row.taken_down = False
        row.take_down_reason = None
        row.status = True
        row.updated_at = now
        db.commit()
        return {"success": True}

    if et in ("SOFTWARE", "COCREATION"):
        row = db.query(Software).filter(Software.id == uid).first()
        if not row:
            return {"success": False, "error": "Entity not found"}
        row.taken_down = False
        row.take_down_reason = None
        row.status = True
        row.updated_at = now
        db.commit()
        return {"success": True}

    if et in ("COMMUNITY_AUCTION", "CREATOR_AUCTION"):
        from app.service.community.community_auction_service import CommunityAuctionService
        row = db.query(CommunityAuction).filter(CommunityAuction.id == uid).first()
        if not row:
            return {"success": False, "error": "Entity not found"}
        row.status = "ACTIVE"
        row.updated_at = now
        db.commit()
        try:
            CommunityAuctionService._broadcast_profile_sync(
                row,
                "creator_auction_live",
            )
        except Exception:
            pass
        return {"success": True}

    return {"success": False, "error": f"Unsupported type: {entity_type}"}


async def toggle_domain_homepage(db: Session, entity_id: str):
    row = db.query(DomainListing).filter(DomainListing.id == UUID(entity_id)).first()
    if not row:
        return {"success": False, "error": "Domain not found"}
    row.featured = not row.featured
    db.commit()
    return {"success": True, "featured": row.featured}


async def toggle_venture_homepage(db: Session, entity_id: str):
    row = db.query(Venture).filter(Venture.id == UUID(entity_id)).first()
    if not row:
        return {"success": False, "error": "Venture not found"}
    row.featured = not row.featured
    db.commit()
    return {"success": True, "featured": row.featured}


async def toggle_software_homepage(db: Session, entity_id: str):
    row = db.query(Software).filter(Software.id == UUID(entity_id)).first()
    if not row:
        return {"success": False, "error": "Software not found"}
    next_featured = not row.featured
    if next_featured and not bool(row.verified):
        return {
            "success": False,
            "error": "Technology must be verified by an admin before it can be featured on the homepage",
        }
    row.featured = next_featured
    db.commit()
    return {"success": True, "featured": row.featured}


async def set_featured(db: Session, entity_type: str, entity_id: str, featured: bool):
    et = entity_type.upper()
    if et == "DOMAIN":
        row = db.query(DomainListing).filter(DomainListing.id == UUID(entity_id)).first()
    elif et == "VENTURE":
        row = db.query(Venture).filter(Venture.id == UUID(entity_id)).first()
    elif et in ("SOFTWARE", "COCREATION"):
        row = db.query(Software).filter(Software.id == UUID(entity_id)).first()
    elif et in ("COMMUNITY", "CREATOR"):
        row = db.query(Community).filter(Community.id == UUID(entity_id)).first()
    elif et in ("VIRTUAL_ASSISTANT", "VA"):
        row = (
            db.query(VirtualAssistantApplication)
            .filter(
                VirtualAssistantApplication.id == UUID(entity_id),
                VirtualAssistantApplication.is_deleted.is_(False),
            )
            .first()
        )
    elif et == "DOMAIN_AUCTION":
        row = db.query(Auction).filter(Auction.id == UUID(entity_id), Auction.is_deleted.is_(False)).first()
    elif et in ("COMMUNITY_AUCTION", "CREATOR_AUCTION"):
        row = (
            db.query(CommunityAuction)
            .filter(CommunityAuction.id == UUID(entity_id), CommunityAuction.is_deleted.is_(False))
            .first()
        )
    elif et == "SOFTWARE_AUCTION":
        row = db.query(SoftwareAuction).filter(SoftwareAuction.id == UUID(entity_id)).first()
    else:
        return {"success": False, "error": f"Unsupported type: {entity_type}"}
    if not row:
        return {"success": False, "error": "Entity not found"}
    if featured and et in ("VIRTUAL_ASSISTANT", "VA"):
        from app.service.admin.virtual_assistant_admin_service import VirtualAssistantAdminService

        if not VirtualAssistantAdminService.is_publicly_listable(db, row):
            return {
                "success": False,
                "error": "Virtual Assistant must be published, approved, active, and have a public price before featuring",
            }
    if featured and et in ("SOFTWARE", "COCREATION") and not bool(getattr(row, "verified", False)):
        return {
            "success": False,
            "error": "Technology must be verified by an admin before it can be featured on the homepage",
        }
    row.featured = featured
    db.commit()
    return {"success": True, "featured": row.featured}
