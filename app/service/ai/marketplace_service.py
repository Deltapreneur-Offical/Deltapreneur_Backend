from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import String, and_, cast, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entity.auction.auction_entity import Auction
from app.entity.auction.domain_entity import Domain
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.cocreation.software_entity import Software
from app.entity.community.community import Community
from app.entity.coventure.brand_details_entity import BrandDetails
from app.entity.coventure.venture_entity import Venture
from app.utils.enums import AuctionStatus
from app.entity.coventure.venture_acquisition_application_entity import (
    VentureAcquisitionApplication,
)
from app.utils.marketplace_enums import DomainListingStatus
from app.utils.venture_enums import VentureListingApprovalStatus
from app.utils.venture_visibility import ACTIVE_ACQUISITION_STATUSES

logger = logging.getLogger(__name__)


STOPWORDS = {
    "about",
    "analyze",
    "and",
    "auction",
    "auctions",
    "compare",
    "creator",
    "creators",
    "domain",
    "domains",
    "find",
    "for",
    "from",
    "ending",
    "ends",
    "listing",
    "listings",
    "live",
    "marketplace",
    "real",
    "recommend",
    "results",
    "search",
    "show",
    "soon",
    "the",
    "them",
    "than",
    "today",
    "under",
    "below",
    "upto",
    "use",
    "what",
    "which",
    "watching",
    "worth",
    "with",
}

SEMANTIC_EXPANSIONS = {
    "ai": ["ai", "artificial", "intelligence", "agent", "automation", "data", "tech", "cloud", "app"],
    "agent": ["agent", "ai", "automation", "assistant", "workflow"],
    "automation": ["automation", "agent", "ai", "workflow", "saas"],
    "startup": ["startup", "brand", "venture", "saas", "app", "labs"],
    "saas": ["saas", "software", "cloud", "app", "platform"],
    "fintech": ["fintech", "finance", "pay", "bank", "capital", "wealth"],
    "premium": ["premium", "brandable", "generic"],
    "brand": ["brand", "brandable", "premium", "studio"],
    "technology": ["technology", "software", "saas", "tech", "cloud"],
}


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _query_terms(query: str) -> list[str]:
    terms = []
    for term in re.findall(r"[a-z0-9.]+", query.lower()):
        cleaned = term.strip(".")
        if len(cleaned) < 3 or cleaned in STOPWORDS or cleaned.isdigit():
            continue
        expanded = SEMANTIC_EXPANSIONS.get(cleaned, [cleaned])
        for candidate in expanded:
            if candidate not in terms:
                terms.append(candidate)
    return terms[:12]


def _max_price(query: str) -> float | None:
    text = query.lower().replace(",", "").replace(chr(8377), "rs")
    match = re.search(r"(?:under|below|less than|upto|up to)\s*(?:rs\.?|inr)?\s*(\d+(?:\.\d+)?)\s*(k|lakh|lac|m)?", text)
    if not match:
        match = re.search(r"(?:inr|rs\.?|\$)\s*(\d+(?:\.\d+)?)\s*(k|lakh|lac|m)?", text)
    if not match:
        return None
    amount = float(match.group(1))
    suffix = match.group(2)
    if suffix == "k":
        amount *= 1000
    elif suffix in {"lakh", "lac"}:
        amount *= 100000
    elif suffix == "m":
        amount *= 1000000
    return amount


def _ending_today(query: str) -> bool:
    return bool(re.search(r"\b(ending today|ends today|today)\b", query.lower()))


def _normalize_domain(value: str) -> str:
    domain = value.lower().strip()
    domain = re.sub(r"^https?://", "", domain)
    domain = domain.split("/", 1)[0].split("?", 1)[0].strip(".,;:!?()[]{}\"'")
    return domain


class MarketplaceService:
    """Read-only marketplace intelligence queries for Bro."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _safe_query(self, label: str, query) -> list[dict[str, Any]]:
        try:
            return await query
        except Exception as exc:
            logger.exception(
                "Bro marketplace query failed label=%s error_type=%s error=%s",
                label,
                exc.__class__.__name__,
                exc,
            )
            return []

    async def search_domains(self, query: str = "", limit: int = 6) -> list[dict[str, Any]]:
        stmt = (
            select(DomainListing)
            .options(selectinload(DomainListing.listed_by), selectinload(DomainListing.contact_info))
            .where(
                DomainListing.is_deleted.is_(False),
                DomainListing.status.is_(True),
                DomainListing.taken_down.is_(False),
                DomainListing.domain_status == DomainListingStatus.AVAILABLE,
            )
            .order_by(desc(DomainListing.featured), desc(DomainListing.views), desc(DomainListing.created_at))
            .limit(limit)
        )
        terms = _query_terms(query)
        max_price = _max_price(query)
        if terms:
            stmt = stmt.where(
                or_(
                    *[
                        condition
                        for term in terms
                        for condition in (
                            DomainListing.domain_name.ilike(f"%{term}%"),
                            DomainListing.domain_extension.ilike(f"%{term}%"),
                            cast(DomainListing.domain_category, String).ilike(f"%{term}%"),
                            cast(DomainListing.pricing_demand, String).ilike(f"%{term}%"),
                        )
                    ]
                )
            )
        if max_price is not None:
            stmt = stmt.where(DomainListing.asking_price <= max_price)
        rows = (await self.db.execute(stmt)).scalars().unique().all()
        return [self._domain_listing(row) for row in rows]

    async def lookup_domain(self, domain: str) -> dict[str, Any] | None:
        normalized = _normalize_domain(domain)
        if "." not in normalized:
            return None
        name, extension = normalized.rsplit(".", 1)
        if not name or not extension:
            return None
        extension = f".{extension}"
        stmt = (
            select(DomainListing)
            .options(selectinload(DomainListing.listed_by), selectinload(DomainListing.contact_info))
            .where(
                DomainListing.is_deleted.is_(False),
                DomainListing.status.is_(True),
                DomainListing.taken_down.is_(False),
                func.lower(DomainListing.domain_name) == name,
                func.lower(DomainListing.domain_extension) == extension,
            )
            .order_by(desc(DomainListing.created_at))
            .limit(1)
        )
        row = (await self.db.execute(stmt)).scalars().unique().one_or_none()
        return self._domain_listing(row) if row else None

    async def search_ventures(self, query: str = "", limit: int = 5) -> list[dict[str, Any]]:
        locked_ventures = (
            select(VentureAcquisitionApplication.venture_id)
            .where(
                VentureAcquisitionApplication.status.in_(ACTIVE_ACQUISITION_STATUSES),
            )
        )
        stmt = (
            select(Venture)
            .options(selectinload(Venture.brand_details), selectinload(Venture.contact_info))
            .where(
                Venture.is_deleted.is_(False),
                Venture.status.is_(True),
                Venture.taken_down.is_(False),
                Venture.listing_approval_status == VentureListingApprovalStatus.APPROVED,
                Venture.id.not_in(locked_ventures),
            )
            .order_by(desc(Venture.featured), desc(Venture.views), desc(Venture.created_at))
            .limit(limit)
        )
        terms = _query_terms(query)
        max_price = _max_price(query)
        if terms:
            stmt = stmt.where(
                or_(
                    *[
                        condition
                        for term in terms
                        for condition in (
                            Venture.current_problem.ilike(f"%{term}%"),
                            cast(Venture.stage, String).ilike(f"%{term}%"),
                            cast(Venture.sale_type, String).ilike(f"%{term}%"),
                            Venture.brand_details.has(BrandDetails.brand_name.ilike(f"%{term}%")),
                            Venture.brand_details.has(BrandDetails.description.ilike(f"%{term}%")),
                            Venture.brand_details.has(cast(BrandDetails.industry, String).ilike(f"%{term}%")),
                        )
                    ]
                )
            )
        if max_price is not None:
            stmt = stmt.where(Venture.brand_details.has(BrandDetails.deal_value <= max_price))
        rows = (await self.db.execute(stmt)).scalars().unique().all()
        return [self._venture(row) for row in rows]

    async def search_creators(self, query: str = "", limit: int = 5) -> list[dict[str, Any]]:
        stmt = (
            select(Community)
            .where(Community.is_deleted.is_(False), Community.is_approved.is_(True))
            .order_by(desc(Community.views), desc(Community.created_at))
            .limit(limit)
        )
        terms = _query_terms(query)
        if terms:
            stmt = stmt.where(
                or_(
                    *[
                        condition
                        for term in terms
                        for condition in (
                            Community.name.ilike(f"%{term}%"),
                            Community.role.ilike(f"%{term}%"),
                            Community.skills.ilike(f"%{term}%"),
                            Community.industry.ilike(f"%{term}%"),
                            Community.location.ilike(f"%{term}%"),
                        )
                    ]
                )
            )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self._creator(row) for row in rows]

    async def search_auctions(self, query: str = "", limit: int = 5) -> list[dict[str, Any]]:
        active_statuses = [AuctionStatus.ACTIVE, AuctionStatus.EXTENDED]
        stmt = (
            select(Auction)
            .join(Auction.domain)
            .options(selectinload(Auction.domain))
            .where(Auction.is_deleted.is_(False), Auction.status.in_(active_statuses))
            .order_by(Auction.end_time.asc())
            .limit(limit)
        )
        terms = _query_terms(query)
        max_price = _max_price(query)
        if _ending_today(query):
            now = datetime.now(timezone.utc)
            tomorrow = now + timedelta(days=1)
            stmt = stmt.where(Auction.end_time >= now, Auction.end_time < tomorrow)
        if terms:
            stmt = stmt.where(or_(*[Domain.domain_name.ilike(f"%{term}%") for term in terms]))
        if max_price is not None:
            stmt = stmt.where(
                or_(
                    and_(Auction.current_highest_bid > 0, Auction.current_highest_bid <= max_price),
                    Auction.min_bid_price <= max_price,
                )
            )
        domain_auctions = (await self.db.execute(stmt)).scalars().unique().all()
        return [self._domain_auction(row) for row in domain_auctions][:limit]

    async def search_software(self, query: str = "", limit: int = 5) -> list[dict[str, Any]]:
        stmt = (
            select(Software)
            .where(Software.is_deleted.is_(False), Software.status.is_(True), Software.taken_down.is_(False))
            .order_by(desc(Software.featured), desc(Software.views), desc(Software.created_at))
            .limit(limit)
        )
        terms = _query_terms(query)
        max_price = _max_price(query)
        if terms:
            stmt = stmt.where(
                or_(
                    *[
                        condition
                        for term in terms
                        for condition in (
                            Software.name.ilike(f"%{term}%"),
                            Software.description.ilike(f"%{term}%"),
                            Software.what_it_does.ilike(f"%{term}%"),
                            Software.how_it_helps.ilike(f"%{term}%"),
                            Software.tech_stack.ilike(f"%{term}%"),
                            cast(Software.category, String).ilike(f"%{term}%"),
                        )
                    ]
                )
            )
        if max_price is not None:
            stmt = stmt.where(Software.price <= max_price)
        rows = (await self.db.execute(stmt)).scalars().unique().all()
        return [self._software(row) for row in rows]

    async def featured_listings(self, limit: int = 8) -> dict[str, list[dict[str, Any]]]:
        return {
            "domains": await self._safe_query("domains", self.search_domains(limit=limit)),
            "ventures": await self._safe_query("ventures", self.search_ventures(limit=max(3, limit // 2))),
            "creators": await self._safe_query("creators", self.search_creators(limit=max(3, limit // 2))),
            "auctions": await self._safe_query("auctions", self.search_auctions(limit=max(3, limit // 2))),
            "software": await self._safe_query("software", self.search_software(limit=max(3, limit // 2))),
        }

    async def trending_listings(self, query: str = "", limit: int = 8) -> dict[str, list[dict[str, Any]]]:
        return {
            "domains": await self._safe_query("domains", self.search_domains(query=query, limit=limit)),
            "ventures": await self._safe_query("ventures", self.search_ventures(query=query, limit=max(3, limit // 2))),
            "creators": await self._safe_query("creators", self.search_creators(query=query, limit=max(3, limit // 2))),
            "auctions": await self._safe_query("auctions", self.search_auctions(query=query, limit=max(3, limit // 2))),
            "software": await self._safe_query("software", self.search_software(query=query, limit=max(3, limit // 2))),
        }

    def _domain_listing(self, row: DomainListing) -> dict[str, Any]:
        return {
            "type": "domain",
            "id": str(row.id),
            "name": f"{row.domain_name}{row.domain_extension or ''}",
            "price": row.asking_price,
            "category": _enum_value(row.domain_category) or "OTHER",
            "description": None,
            "seller": getattr(row.listed_by, "username", None) or getattr(row.listed_by, "email", None),
            "owner": getattr(row.listed_by, "username", None) or getattr(row.listed_by, "email", None),
            "tags": [tag for tag in [_enum_value(row.domain_category), _enum_value(row.pricing_demand)] if tag],
            "listing_status": _enum_value(row.domain_status),
            "status": "ACTIVE" if row.status and not row.taken_down else "INACTIVE",
            "views": int(row.views or 0),
            "is_featured": bool(row.featured),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "url": f"/domains?listing={row.id}",
        }

    def _venture(self, row: Venture) -> dict[str, Any]:
        brand = row.brand_details
        return {
            "type": "venture",
            "id": str(row.id),
            "name": _text(getattr(brand, "brand_name", None)) or "Unnamed venture",
            "price": getattr(brand, "deal_value", None),
            "category": _enum_value(getattr(brand, "industry", None)) or _enum_value(row.stage),
            "description": _text(getattr(brand, "description", None)) or row.current_problem,
            "seller": None,
            "tags": [tag for tag in [_enum_value(row.stage), _enum_value(row.sale_type)] if tag],
            "listing_status": "ACTIVE" if row.status and not row.taken_down else "INACTIVE",
            "status": "ACTIVE" if row.status and not row.taken_down else "INACTIVE",
            "views": int(row.views or 0),
            "is_featured": bool(row.featured),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "url": f"/ventures?venture={row.id}",
        }

    def _creator(self, row: Community) -> dict[str, Any]:
        return {
            "type": "creator",
            "id": str(row.id),
            "name": row.name or "HubRegistrar creator",
            "role": row.role,
            "category": row.industry,
            "description": row.why_im_here,
            "tags": [item.strip() for item in (row.skills or "").split(",") if item.strip()][:6],
            "location": row.location,
            "listing_status": "APPROVED" if row.is_approved and not row.is_deleted else "INACTIVE",
            "status": "APPROVED" if row.is_approved and not row.is_deleted else "INACTIVE",
            "views": int(row.views or 0),
            "is_featured": False,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "url": f"/community?creator={row.id}",
        }

    def _domain_auction(self, row: Auction) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        end_time = row.end_time
        seconds_left = max(0, int((end_time - now).total_seconds())) if end_time else None
        return {
            "type": "auction",
            "auction_type": "domain",
            "id": str(row.id),
            "name": row.domain.domain_name if row.domain else "Domain auction",
            "price": float(row.current_highest_bid or row.min_bid_price or 0),
            "min_bid_price": float(row.min_bid_price or 0),
            "total_bids": row.total_bids,
            "status": _enum_value(row.status),
            "listing_status": _enum_value(row.status),
            "ends_at": end_time.isoformat() if end_time else None,
            "seconds_left": seconds_left,
            "url": f"/auction/{row.id}",
        }

    def _software(self, row: Software) -> dict[str, Any]:
        return {
            "type": "software",
            "id": str(row.id),
            "name": row.name,
            "price": row.price,
            "category": _enum_value(row.category),
            "description": row.description or row.what_it_does,
            "tags": [tag for tag in [_enum_value(row.category), row.tech_stack] if tag],
            "listing_status": _enum_value(row.software_status),
            "status": "ACTIVE" if row.status and not row.taken_down else "INACTIVE",
            "views": int(row.views or 0),
            "is_featured": bool(row.featured),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "url": f"/cocreation?software={row.id}",
        }
