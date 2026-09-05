"""OpenRouter integration for premium domain-name generation."""

from __future__ import annotations

import json
import logging
import re
import traceback
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.core.exceptions import AppException
from app.schemas.ai_domains import AIDomainCandidate

logger = logging.getLogger(__name__)
MAX_OPENROUTER_RETRIES = 2
GOOGLE_DATA_REDACTION_MESSAGE = "[redacted: Google API data omitted]"
GOOGLE_DATA_PATTERNS = (
    "google",
    "calendar",
    "meet",
    "oauth",
    "token",
    "attendee",
    "attendees",
    "conference",
    "refresh_token",
    "access_token",
    "id_token",
    "oauth2",
    "googleapis",
    "gmail",
    "drive",
    "calendar.v3",
)


class OpenRouterService:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def generate_business_names(self, idea: str) -> list[AIDomainCandidate]:
        return await self._generate(idea)

    async def generate_candidates(self, idea: str) -> list[AIDomainCandidate]:
        return await self.generate_business_names(idea)

    async def _generate(self, idea: str) -> list[AIDomainCandidate]:
        if settings.AI_PROVIDER.strip().lower() != "openrouter":
            raise AppException(
                "AI provider is not configured for OpenRouter.",
                status_code=503,
            )
        if not settings.OPENROUTER_API_KEY.strip():
            raise AppException(
                "OpenRouter is not configured. Set OPENROUTER_API_KEY.",
                status_code=503,
            )
        model = (settings.AI_MODEL.strip() or settings.OPENROUTER_MODEL.strip())
        if not model:
            raise AppException(
                "OpenRouter is not configured. Set AI_MODEL.",
                status_code=503,
            )

        payload = self._payload(idea)
        user_prompt = payload["messages"][1]["content"]
        logger.info(
            "OpenRouter request idea=%r model=%s provider=%s",
            idea,
            model,
            settings.AI_PROVIDER,
        )
        logger.info("OpenRouter user prompt:\n%s", user_prompt)
        last_error: Exception | None = None
        attempts = max(1, MAX_OPENROUTER_RETRIES + 1)
        for attempt in range(attempts):
            try:
                data = await self._request(payload)
                return self._validate_response(data, idea)
            except AppException:
                raise
            except (httpx.TimeoutException, ValueError, ValidationError) as exc:
                last_error = exc
                logger.warning(
                    "OpenRouter AI Domains attempt failed attempt=%s exception_type=%s exception_message=%s traceback=%s",
                    attempt + 1,
                    type(exc).__name__,
                    str(exc),
                    traceback.format_exc(),
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403):
                    logger.exception(
                        "OpenRouter AI Domains auth failure status=%s response_body=%s",
                        exc.response.status_code,
                        exc.response.text[:1000],
                    )
                    raise AppException(
                        "Invalid OpenRouter API key or provider access.",
                        status_code=503,
                    ) from exc
                if exc.response.status_code == 402:
                    logger.warning(
                        "OpenRouter AI Domains credits exhausted status=%s response_body=%s",
                        exc.response.status_code,
                        exc.response.text[:1000],
                    )
                    raise AppException(
                        "OpenRouter credits are low. Add credits at openrouter.ai/settings/credits.",
                        status_code=503,
                    ) from exc
                if exc.response.status_code == 429:
                    logger.exception(
                        "OpenRouter AI Domains rate limit status=%s response_body=%s",
                        exc.response.status_code,
                        exc.response.text[:1000],
                    )
                    raise AppException(
                        "OpenRouter rate limit reached. Please try again shortly.",
                        status_code=503,
                    ) from exc
                last_error = exc
                logger.warning(
                    "OpenRouter AI Domains HTTP failure attempt=%s status=%s response_body=%s traceback=%s",
                    attempt + 1,
                    exc.response.status_code,
                    exc.response.text[:1000],
                    traceback.format_exc(),
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "OpenRouter AI Domains transport failure attempt=%s exception_type=%s exception_message=%s traceback=%s",
                    attempt + 1,
                    type(exc).__name__,
                    str(exc),
                    traceback.format_exc(),
                )

        raise AppException(
            "Unable to generate names.",
            status_code=503,
        ) from last_error

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        endpoint = f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"
        model = (settings.AI_MODEL.strip() or settings.OPENROUTER_MODEL.strip())
        auth_configured = bool(settings.OPENROUTER_API_KEY.strip())
        logger.info(
            "OpenRouter request configured provider=%s model=%s endpoint=%s timeout_seconds=%s authorization_configured=%s",
            settings.AI_PROVIDER,
            model,
            endpoint,
            settings.AI_TIMEOUT_SECONDS,
            auth_configured,
        )
        client = self._get_client()
        response = await client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY.strip()}",
                "Content-Type": "application/json",
                "HTTP-Referer": settings.FRONTEND_BASE_URL,
                "X-Title": "Deltapreneur AI Domains",
            },
            json=payload,
        )
        logger.info(
            "OpenRouter response status=%s model=%s endpoint=%s authorization_configured=%s",
            response.status_code,
            model,
            endpoint,
            auth_configured,
        )
        response.raise_for_status()
        try:
            data = response.json()
        except Exception:
            logger.exception(
                "OpenRouter HTTP response JSON parse failed status=%s body_prefix=%s",
                response.status_code,
                response.text[:1000],
            )
            raise
        logger.info(
            "OpenRouter HTTP response JSON parsed keys=%s choices_count=%s",
            sorted(data.keys()) if isinstance(data, dict) else type(data).__name__,
            len(data.get("choices", [])) if isinstance(data, dict) else "unknown",
        )
        return data

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            timeout = httpx.Timeout(
                timeout=settings.AI_TIMEOUT_SECONDS,
                connect=min(5.0, settings.AI_TIMEOUT_SECONDS),
            )
            self._client = httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    def _sanitize_text(self, value: str | None) -> str:
        if not value:
            return ""
        lower = value.lower()
        if any(pattern in lower for pattern in GOOGLE_DATA_PATTERNS):
            return GOOGLE_DATA_REDACTION_MESSAGE
        return value

    def _payload(self, idea: str) -> dict[str, Any]:
        safe_idea = self._sanitize_text(idea)
        if safe_idea != idea:
            safe_idea = "Business idea provided by the user for naming support."
        system = (
            "You are a world-class brand naming expert.\n\n"
            "Your task is to generate highly relevant, memorable, premium business names "
            "based on the user's business description.\n\n"
            "CRITICAL RULES:\n"
            "1. Every name must feel directly connected to the business.\n"
            "2. Never use generic suffixes or prefixes such as: "
            "Hub, Pro, AI, Tech, Solutions, Digital, Global, Online, X, 24/7, Services, Corp.\n"
            "3. Avoid repeating patterns.\n"
            "4. Avoid names that sound machine-generated.\n"
            "5. Generate names as if they were real successful brands.\n"
            "6. Prioritize relevance over domain availability.\n"
            "7. Use industry concepts, emotions, customer outcomes, ingredients, culture, "
            "location themes, and unique brand storytelling.\n"
            "8. Each generated name must be significantly different from the others.\n"
            "9. Do not reuse structures across names.\n"
            "10. Generate creative invented brand words when appropriate.\n\n"
            "PROCESS:\n"
            "Step 1: Generate 100 candidate names internally.\n"
            "Step 2: Score each name on Relevance (0-100), Memorability (0-100), "
            "and Brandability (0-100). Final score = rounded average of the three.\n"
            "Step 3: Remove weak, generic, repetitive, and low-scoring names.\n"
            "Step 4: Return only the best 20 names.\n\n"
            "Use domain-friendly single tokens (VelvetRoast not Velvet Roast). No numbers or hyphens.\n"
            "Never glue an industry word to a random suffix (Coffexa, Coffily, Foodly).\n\n"
            "OUTPUT: valid JSON array only. No markdown. No commentary.\n"
            'Each item: {"name":"BrewNest","score":95,"reason":"Evokes craft brewing and a welcoming gathering place"}'
        )
        user = f"""
BUSINESS DESCRIPTION:
{safe_idea}

Return JSON array only with the best 20 names after your internal 100-candidate scoring and filtering.
""".strip()
        return {
            "model": settings.AI_MODEL.strip() or settings.OPENROUTER_MODEL.strip(),
            "temperature": 0.78,
            "max_tokens": max(800, settings.AI_DOMAIN_MAX_TOKENS),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

    def _validate_response(self, data: dict[str, Any], idea: str) -> list[AIDomainCandidate]:
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        raw_text = str(content or "")
        logger.info(
            "AI RAW RESPONSE idea=%r content_length=%s",
            idea,
            len(raw_text),
        )
        logger.info("AI RAW RESPONSE body:\n%s", raw_text[:8000])
        parsed = self._loads_json(content)
        raw_names = parsed if isinstance(parsed, list) else parsed.get("names")
        if not isinstance(raw_names, list) or not raw_names:
            raise ValueError("OpenRouter returned no names")

        candidates: list[AIDomainCandidate] = []
        seen: set[str] = set()
        validation_failures = 0
        default_category = str(parsed.get("category") or "Startup") if isinstance(parsed, dict) else "Startup"
        for raw in raw_names:
            if isinstance(raw, str):
                raw = {
                    "name": raw,
                    "category": default_category,
                    "score": self._fallback_score(raw),
                    "reason": "AI-suggested brand name",
                }
            if not isinstance(raw, dict):
                continue
            if not raw.get("name"):
                continue
            raw["score"] = self._normalize_score(raw)
            if raw["score"] is None:
                raw["score"] = self._fallback_score(str(raw.get("name", "")))
            raw.setdefault("category", default_category)
            raw.setdefault("style", "Premium Brand")
            raw.setdefault("reason", "Relevant, brandable name for this business idea")
            try:
                candidate = AIDomainCandidate.model_validate(raw)
            except ValidationError:
                validation_failures += 1
                continue
            key = candidate.name.lower()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)

        if len(candidates) < 5:
            raise ValueError(
                f"OpenRouter returned too few parseable names ({len(candidates)} valid items)",
            )
        logger.info(
            "PARSED NAMES (OpenRouter schema ok) idea=%r names=%s",
            idea,
            [item.name for item in candidates],
        )
        logger.info(
            "OpenRouter candidate validation succeeded raw_names_count=%s candidates_count=%s validation_failures=%s",
            len(raw_names),
            len(candidates),
            validation_failures,
        )
        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[:20]

    @staticmethod
    def _normalize_score(raw: dict[str, Any]) -> int | None:
        if raw.get("score") is not None:
            try:
                return max(0, min(100, int(raw["score"])))
            except (TypeError, ValueError):
                pass
        relevance = raw.get("relevance")
        memorability = raw.get("memorability")
        brandability = raw.get("brandability")
        parts: list[int] = []
        for value in (relevance, memorability, brandability):
            if value is None:
                continue
            try:
                parts.append(max(0, min(100, int(value))))
            except (TypeError, ValueError):
                continue
        if not parts:
            return None
        return round(sum(parts) / len(parts))

    @staticmethod
    def _fallback_score(name: str) -> int:
        clean = re.sub(r"[^A-Za-z]", "", str(name or ""))
        if not clean:
            return 70
        length_bonus = 12 if 5 <= len(clean) <= 10 else 7 if len(clean) <= 14 else 3
        vowel_bonus = 6 if re.search(r"[aeiou]", clean.lower()) else 0
        pronounce_bonus = 5 if not re.search(r"[^aeiou]{4,}", clean.lower()) else 0
        return max(70, min(92, 72 + length_bonus + vowel_bonus + pronounce_bonus))

    @staticmethod
    def _loads_json(content: str) -> dict[str, Any] | list[Any]:
        text = str(content or "").strip()
        if text.startswith("```"):
            match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()
        parsed = json.loads(text)
        if not isinstance(parsed, (dict, list)):
            raise ValueError("AI response must be JSON")
        logger.info(
            "OpenRouter AI content JSON parsed parsed_type=%s item_count=%s",
            type(parsed).__name__,
            len(parsed) if hasattr(parsed, "__len__") else "unknown",
        )
        return parsed


openrouter_service = OpenRouterService()
