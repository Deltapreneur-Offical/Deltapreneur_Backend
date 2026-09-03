from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.service.ai.marketplace_service import MarketplaceService


class SemanticSearchService:
    """Keyword-scored semantic facade, ready to swap to pgvector embeddings."""

    def __init__(self, db: AsyncSession):
        self.marketplace = MarketplaceService(db)

    async def search(self, query: str, limit: int = 8) -> dict[str, list[dict[str, Any]]]:
        candidates = await self.marketplace.trending_listings(query=query, limit=limit)
        if not any(candidates.values()) and self._allow_discovery_fallback(query):
            candidates = await self.marketplace.featured_listings(limit=limit)
        return {
            key: self._rank(query, rows)[:limit]
            for key, rows in candidates.items()
        }

    def _allow_discovery_fallback(self, query: str) -> bool:
        text = query.lower().strip()
        if not text:
            return True
        return bool(
            re.search(
                r"\b(featured|trending|popular|top|best|opportunities|discover|recommend|suggest|ending soon|live auctions)\b",
                text,
            )
        )

    def _rank(self, query: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        terms = set(re.findall(r"[a-z0-9]+", query.lower()))
        if not terms:
            return rows

        def score(row: dict[str, Any]) -> int:
            haystack = " ".join(
                str(part or "")
                for part in [
                    row.get("name"),
                    row.get("category"),
                    row.get("description"),
                    " ".join(row.get("tags") or []),
                ]
            ).lower()
            return sum(3 if term in haystack else 0 for term in terms) + int(row.get("is_featured") or 0)

        return sorted(rows, key=score, reverse=True)
