"""Per-section cap for Admin → Homepage Features (not global, not Showcase)."""

from __future__ import annotations

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.entity.auction.auction_entity import Auction
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.cocreation.software_auction import SoftwareAuction
from app.entity.cocreation.software_entity import Software
from app.entity.community.community import Community
from app.entity.community.community_auction import CommunityAuction
from app.entity.coventure.venture_entity import Venture
from app.entity.virtual_assistant.virtual_assistant_entity import VirtualAssistantApplication
from app.utils.venture_enums import VentureListingMode

HOMEPAGE_FEATURE_MAX = 8
HOMEPAGE_FEATURE_MAX_MESSAGE = (
    "Maximum 8 featured items allowed. Please unfeature one item before featuring another."
)

_AUCTION_TYPES = {
    "DOMAIN_AUCTION",
    "COMMUNITY_AUCTION",
    "CREATOR_AUCTION",
    "SOFTWARE_AUCTION",
}


def should_block_homepage_feature(current_count: int, currently_featured: bool, want_featured: bool) -> bool:
    if not want_featured or currently_featured:
        return False
    return int(current_count or 0) >= HOMEPAGE_FEATURE_MAX


def is_homepage_feature_limit_error(result: dict | None) -> bool:
    return bool(result) and result.get("success") is False and result.get("error") == HOMEPAGE_FEATURE_MAX_MESSAGE


def homepage_feature_limit_payload() -> dict:
    return {
        "success": False,
        "error": HOMEPAGE_FEATURE_MAX_MESSAGE,
        "featured": False,
    }


def _is_co_venture(row) -> bool:
    mode = getattr(row, "listing_mode", None)
    value = getattr(mode, "value", mode)
    return str(value or "").upper() == VentureListingMode.CO_VENTURE.value


def _alive_filters(model):
    filters = []
    if hasattr(model, "is_deleted"):
        filters.append(model.is_deleted.is_(False))
    if hasattr(model, "taken_down"):
        filters.append(model.taken_down.is_(False))
    return filters


def _featured_query(db: Session, model, extra=()):
    return db.query(model).filter(model.featured.is_(True), *_alive_filters(model), *extra)


def _count_featured(db: Session, model, extra=()) -> int:
    query = db.query(func.count(model.id)).filter(model.featured.is_(True), *_alive_filters(model), *extra)
    return int(query.scalar() or 0)


def _lock_featured(db: Session, model, extra=()) -> None:
    _featured_query(db, model, extra).with_for_update().all()


def _venture_mode_filters(row):
    if _is_co_venture(row):
        return (Venture.listing_mode == VentureListingMode.CO_VENTURE,)
    return (
        or_(
            Venture.listing_mode != VentureListingMode.CO_VENTURE,
            Venture.listing_mode.is_(None),
        ),
    )


def count_section_featured(db: Session, entity_type: str, row=None) -> int:
    et = str(entity_type or "").upper()
    if et == "DOMAIN":
        return _count_featured(db, DomainListing)
    if et == "VENTURE":
        return _count_featured(db, Venture, extra=_venture_mode_filters(row))
    if et in ("SOFTWARE", "COCREATION"):
        return _count_featured(db, Software)
    if et in ("COMMUNITY", "CREATOR"):
        return _count_featured(db, Community)
    if et in ("VIRTUAL_ASSISTANT", "VA"):
        return _count_featured(db, VirtualAssistantApplication)
    if et in _AUCTION_TYPES:
        return (
            _count_featured(db, Auction)
            + _count_featured(db, CommunityAuction)
            + _count_featured(db, SoftwareAuction)
        )
    return 0


def _lock_section(db: Session, entity_type: str, row=None) -> None:
    et = str(entity_type or "").upper()
    if et == "DOMAIN":
        _lock_featured(db, DomainListing)
    elif et == "VENTURE":
        _lock_featured(db, Venture, extra=_venture_mode_filters(row))
    elif et in ("SOFTWARE", "COCREATION"):
        _lock_featured(db, Software)
    elif et in ("COMMUNITY", "CREATOR"):
        _lock_featured(db, Community)
    elif et in ("VIRTUAL_ASSISTANT", "VA"):
        _lock_featured(db, VirtualAssistantApplication)
    elif et in _AUCTION_TYPES:
        _lock_featured(db, Auction)
        _lock_featured(db, CommunityAuction)
        _lock_featured(db, SoftwareAuction)


def enforce_homepage_feature_limit(db: Session, entity_type: str, row, featured: bool) -> dict | None:
    """Block a 9th ON for this Homepage Features section. Unfeature is always allowed."""
    if not featured:
        return None
    if bool(getattr(row, "featured", False)):
        return None
    _lock_section(db, entity_type, row)
    current = count_section_featured(db, entity_type, row)
    if should_block_homepage_feature(current, currently_featured=False, want_featured=True):
        db.rollback()
        return homepage_feature_limit_payload()
    return None
