"""Orchestrates AI names, scoring, category detection, availability, and caching."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone

from app.core.config import settings
from app.core.exceptions import AppException
from app.schemas.ai_domains import AIDomainCandidate, AIDomainGenerateResponse, AIDomainResult
from app.service.domain.domain_registration_service import DomainRegistrationService
from app.services.cache_service import ai_domain_cache
from app.services.domain_checker import AIDomainChecker, DEFAULT_AI_DOMAIN_TLDS
from app.services.ai_name_quality import exceeds_structure_cap, passes_name_quality, record_structure
from app.services.openrouter_service import openrouter_service

logger = logging.getLogger(__name__)

CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Hospitality", ("coffee", "cafe", "espresso", "roast", "barista", "tea", "bakery")),
    ("Logistics", ("water", "delivery", "courier", "shipping", "logistics", "supply")),
    ("Fashion", ("fashion", "apparel", "clothing", "wear", "boutique", "style", "garment")),
    ("Entertainment", ("movie", "ticket", "cinema", "film", "show", "music", "stream")),
    ("FoodTech", ("food", "meal", "restaurant", "kitchen", "grocery", "chef")),
    ("EdTech", ("education", "learn", "school", "course", "student", "teacher", "study")),
    ("Artificial Intelligence", ("ai", "artificial", "machine learning", "automation", "agent")),
    ("FinTech", ("finance", "payment", "bank", "money", "invest", "wealth", "loan")),
    ("HealthTech", ("health", "fitness", "doctor", "clinic", "wellness", "medical")),
    ("TravelTech", ("travel", "hotel", "flight", "trip", "tour", "booking")),
    ("PropTech", ("property", "real estate", "rent", "home", "housing")),
    ("SaaS", ("saas", "software", "platform", "workflow", "dashboard", "crm")),
    ("Construction", ("construction", "builder", "building", "contractor", "renovation", "infrastructure")),
)


class AIDomainEngine:
    def __init__(self, registration_service: DomainRegistrationService) -> None:
        self._checker = AIDomainChecker(registration_service)

    async def generate(self, idea: str, *, request_id: str | None = None) -> AIDomainGenerateResponse:
        logger.info("INPUT IDEA: %s", idea)
        cache_key = self._cache_key(idea)
        cached = await ai_domain_cache.get_json(cache_key)
        if cached:
            cached["cached"] = True
            cached["request_id"] = request_id
            response = AIDomainGenerateResponse.model_validate(cached)
            all_unknown = bool(response.results) and all(
                item.com_status == "unknown" and item.in_status == "unknown"
                for item in response.results
            )
            if not all_unknown:
                logger.info(
                    "FINAL RETURNED NAMES (cache hit): %s",
                    [item.name for item in response.results],
                )
                return response
            logger.info(
                "Skipping AI cache with unknown OpenProvider availability idea=%s",
                idea,
            )

        candidates = await self._generate_candidates(idea)
        category = self._detect_category(idea, candidates[0].category if candidates else None)
        filtered = self._quality_filter(candidates, idea, category)
        if not filtered:
            logger.error(
                "Quality filter removed all AI names idea=%s parsed=%s",
                idea,
                [candidate.name for candidate in candidates],
            )
            raise AppException(
                "AI returned no relevant names for this idea. Please try again.",
                status_code=503,
            )

        top_candidates = filtered[:20]
        logger.info("PARSED NAMES (after quality filter): %s", [c.name for c in top_candidates])

        checks = await asyncio.gather(
            *[
                self._checker.check_many(candidate.name, DEFAULT_AI_DOMAIN_TLDS)
                for candidate in top_candidates
            ]
        )

        results: list[AIDomainResult] = []
        for candidate, availability in zip(top_candidates, checks):
            com = availability["com"]
            in_domain = availability["in"]
            score = self._score(candidate.name, candidate.score, category, com.available, in_domain.available)
            results.append(
                AIDomainResult(
                    name=candidate.name,
                    domain_com=com.domain,
                    com_available=com.available,
                    com_status=com.status,
                    com_price_inr=com.price_inr,
                    domain_in=in_domain.domain,
                    in_available=in_domain.available,
                    in_status=in_domain.status,
                    in_price_inr=in_domain.price_inr,
                    score=score,
                    brand_category=candidate.style,
                    style=candidate.style,
                    reason=candidate.reason,
                )
            )

        if not results:
            raise AppException(
                "AI names did not pass quality scoring. Please try again.",
                status_code=503,
            )

        results.sort(key=self._sort_key, reverse=True)
        final_results = results[:20]
        logger.info(
            "FINAL RETURNED NAMES (openrouter): %s",
            [item.name for item in final_results],
        )
        response = AIDomainGenerateResponse(
            idea=idea,
            category=category,
            cached=False,
            results=final_results,
            generated_at=datetime.now(timezone.utc),
            request_id=request_id,
        )
        all_unknown = bool(final_results) and all(
            item.com_status == "unknown" and item.in_status == "unknown"
            for item in final_results
        )
        if not all_unknown:
            await ai_domain_cache.set_json(
                cache_key,
                response.model_dump(mode="json"),
                settings.AI_DOMAIN_CACHE_TTL_SECONDS,
            )
        return response

    @staticmethod
    def _cache_key(idea: str) -> str:
        normalized = " ".join(idea.lower().strip().split())
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return f"ai_domains:generate:v8:{digest}"

    @staticmethod
    def _detect_category(idea: str, fallback: str | None) -> str:
        text = idea.lower()
        for category, terms in CATEGORY_KEYWORDS:
            if any(term in text for term in terms):
                return category
        return fallback or "Startup"

    async def _generate_candidates(self, idea: str) -> list[AIDomainCandidate]:
        logger.info(
            "Calling OpenRouter for idea=%r model=%s timeout_seconds=%s",
            idea,
            settings.AI_MODEL,
            settings.AI_TIMEOUT_SECONDS,
        )
        try:
            candidates = await openrouter_service.generate_business_names(idea)
        except AppException:
            raise
        except Exception as exc:
            logger.exception("OpenRouter generation failed idea=%s", idea)
            raise AppException(
                "Unable to generate names from AI. Please try again.",
                status_code=503,
            ) from exc

        logger.info(
            "PARSED NAMES (from OpenRouter): %s",
            [candidate.name for candidate in candidates],
        )
        if not candidates:
            raise AppException(
                "AI returned no names. Please try again.",
                status_code=503,
            )
        return candidates

    def _quality_filter(
        self,
        candidates: list[AIDomainCandidate],
        idea: str,
        category: str,
    ) -> list[AIDomainCandidate]:
        seen: set[str] = set()
        structure_roots: dict[str, int] = {}
        filtered: list[AIDomainCandidate] = []
        rejected: list[str] = []

        for candidate in candidates:
            lower = candidate.name.lower()
            if lower in seen:
                rejected.append(f"{candidate.name}:duplicate")
                continue
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{2,23}", candidate.name):
                rejected.append(f"{candidate.name}:invalid_format")
                continue
            if exceeds_structure_cap(candidate.name, structure_roots):
                rejected.append(f"{candidate.name}:repeated_structure")
                continue
            if not passes_name_quality(
                candidate.name,
                idea,
                ai_score=candidate.score,
                min_score=80,
                from_ai=True,
            ):
                rejected.append(f"{candidate.name}:quality_gate")
                continue
            seen.add(lower)
            record_structure(candidate.name, structure_roots)
            candidate.category = category
            if not candidate.reason:
                candidate.reason = f"Brandable name aligned with {category.lower()} positioning"
            filtered.append(candidate)

        if rejected:
            logger.info(
                "Quality filter rejections idea=%s rejected=%s kept=%s",
                idea,
                rejected[:30],
                [item.name for item in filtered],
            )
        filtered.sort(key=lambda item: item.score, reverse=True)
        return filtered

    @staticmethod
    def _score(name: str, ai_score: int, category: str, com_available: bool, in_available: bool) -> int:
        length = len(name)
        length_score = 18 if 5 <= length <= 10 else 12 if length <= 14 else 6
        vowel_score = 10 if re.search(r"[aeiou]", name.lower()) else 3
        pronounce_score = 12 if not re.search(r"[^aeiou]{4,}", name.lower()) else 5
        domain_score = (8 if com_available else 0) + (4 if in_available else 0)
        category_score = 6 if category and category != "Startup" else 3
        blended = int((ai_score * 0.48) + length_score + vowel_score + pronounce_score + domain_score + category_score)
        return max(55, min(98, blended))

    @staticmethod
    def _sort_key(item: AIDomainResult) -> tuple[int, int, int]:
        availability_rank = (2 if item.com_status == "available" else 0) + (
            1 if item.in_status == "available" else 0
        )
        certainty_rank = (
            1
            if item.com_status in {"available", "taken"}
            or item.in_status in {"available", "taken"}
            else 0
        )
        return availability_rank, certainty_rank, item.score


def build_ai_domain_engine(registration_service: DomainRegistrationService) -> AIDomainEngine:
    return AIDomainEngine(registration_service)
