"""Isolated integration layer: OP Premium Showcase → existing Homepage Domains feed.

This module exists so the OpenProvider Showcase can be merged into the existing
Homepage domain marquee WITHOUT touching marketplace/listing logic. It is the
single place that knows how selected showcase rows become homepage feed cards.

Rules (read-only from the database — never writes):
- Only selected + available + not-deleted showcase rows, and only when the
  showcase is enabled (reuses ``ShowcaseDomainService.list_public()``).
- Rows are converted into the SAME public marketplace card shape the homepage
  already renders (``normalizeDomainRecord`` compatible), so the existing
  marquee/card UI works unchanged.
- Deduplication: if the same full domain already exists as a marketplace
  listing, the MARKETPLACE listing wins (existing public flow is never
  overridden); the showcase copy is dropped from the feed only.
- Ordering: merged feed is sorted by ``updated_at`` DESC (nulls last), matching
  the existing ``list_homepage_featured`` ordering so showcase cards interleave
  naturally with admin/user featured listings.

Removing or disabling this module simply removes showcase domains from the
homepage feed — nothing else is affected.
"""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.service.domain.showcase_domain_service import ShowcaseDomainService


def _normalize_name(value: Any) -> str:
    return str(value or "").strip().lower()


def _full_domain(row: dict[str, Any]) -> str:
    """Full normalized domain (label + extension) used as the dedup key.

    Marketplace rows store the label and extension separately; showcase rows
    carry the full domain in ``domain_name`` with an empty extension. Combine
    both so ``hustler.vip`` (showcase) and ``hustler`` + ``.vip`` (marketplace)
    collide and deduplicate correctly.
    """
    name = _normalize_name(row.get("domain_name") or row.get("domainName") or "")
    ext = _normalize_name(row.get("domain_extension") or row.get("domainExtension") or "")
    if ext and not ext.startswith("."):
        ext = f".{ext}"
    if name.endswith(ext):
        return name
    return f"{name}{ext}"


def _updated_at(value: dict[str, Any]) -> str:
    return str(value.get("updated_at") or value.get("created_at") or "")


class ShowcaseHomepageIntegration:
    """Fetches selected showcase domains and merges them into a homepage feed."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def fetch_homepage_rows(self) -> list[dict[str, Any]]:
        """Selected+available showcase rows, as homepage-feed cards.

        Returns [] when the table is missing, the showcase is disabled, or
        nothing is selected — never raises.
        """
        svc = ShowcaseDomainService(self._session)
        try:
            if not await svc.table_available():
                return []
            cfg = await svc._config.get()
            if not bool(cfg.get("enabled")):
                return []
            rows = await svc._repo.list_selected()
        except Exception:  # noqa: BLE001 - homepage must never break on showcase
            return []
        return [self._to_feed_card(r) for r in rows]

    @staticmethod
    def _to_feed_card(row: Any) -> dict[str, Any]:
        """Convert a selected showcase row into a homepage-feed card.

        The card carries BOTH shapes:
        - Premium-card shape (``name``/``tld``/``extension``/``priceInr``/…)
          consumed by the shared ``ShowcaseDomainCard`` → ``DomainCard`` premium
          card on the homepage marquee (single source of truth).
        - Marketplace-compat shape (``domainName`` + empty ``domainExtension``)
          so the legacy ``resolveDomainDisplay`` split path renders the full
          domain ONCE (name + TLD) — never ``hustler.vip.vip``.

        No internal provider/commission data is exposed — provider/source stays
        internal metadata only (``premiumProvider`` is never rendered).
        """
        name, dot, ext = row.domain_name.partition(".")
        extension = f".{ext}" if dot and ext else f".{row.tld or ''}"
        tld = extension.lstrip(".") or (row.tld or "").lstrip(".")
        updated_at = (
            row.updated_at.isoformat() if row.updated_at else None
        ) or (
            row.created_at.isoformat() if row.created_at else None
        )
        return {
            # stable unique key for marquee/list React keys (showcase-prefixed)
            "id": f"showcase-{row.id}",
            # source markers (internal routing only — never rendered to customers)
            "source": "openprovider_showcase",
            "showcaseId": str(row.id),
            "premiumProvider": (row.price_snapshot_json or {}).get("premiumProvider"),
            "managed_acquisition": bool(
                row.payable_inr and row.payable_inr > 500_000.0
            ),
            # premium-card shape (ShowcaseDomainCard / DomainCard adapter)
            "name": name,
            "tld": tld,
            "extension": extension,
            "priceInr": row.create_price_inr,
            "renewalPriceInr": row.renewal_price_inr,
            "payableInr": row.payable_inr,
            "isPremium": bool(row.is_premium),
            # marketplace-compat shape — extension intentionally EMPTY so the
            # legacy split path renders the full domain once (no .vip.vip)
            "domain_name": row.domain_name,
            "domainName": row.domain_name,
            "domain_extension": "",
            "domainExtension": "",
            "domain_status": "AVAILABLE",
            "status": True,
            "featured": True,
            "verified": True,
            "asking_price": row.create_price_inr,
            "askingPrice": row.create_price_inr,
            "listing_price": row.create_price_inr,
            "listingPrice": row.create_price_inr,
            "renewal_price_inr": row.renewal_price_inr,
            "payable_inr": row.payable_inr,
            "is_premium": row.is_premium,
            "pricing_demand": "Premium",
            "sale_type": "ONE_TIME",
            "created_at": (
                row.created_at.isoformat() if row.created_at else None
            ),
            "updated_at": updated_at,
            "likeCount": 0,
            "views": 0,
            "listed_by_user_id": None,
            "purchased_by_user_id": None,
            "taken_down": False,
            "is_deleted": False,
        }

    def merge_into_feed(
        self,
        marketplace_rows: Sequence[dict[str, Any]],
        showcase_rows: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge showcase rows into the homepage feed.

        - Marketplace listings win on duplicate full-domain names (showcase copy
          is dropped from the feed only; the showcase row is untouched).
        - Merged list is sorted by ``updated_at`` DESC (nulls last), matching the
          existing homepage ordering.
        """
        merged: dict[str, dict[str, Any]] = {}

        for row in marketplace_rows:
            key = _full_domain(row)
            if key:
                merged[key] = row

        for row in showcase_rows:
            key = _full_domain(row)
            if not key or key in merged:
                continue  # marketplace listing wins — never duplicate
            merged[key] = row

        return sorted(
            merged.values(),
            key=lambda r: _updated_at(r),
            reverse=True,
        )
