"""Generic share-link service.

Creates opaque, tokenized share records for DOMAIN_SEARCH / AI_BRAND_DOMAIN
(and later MARKETPLACE), resolves them by token, and builds a **sanitized**
preview payload that re-runs a live registrar check on every open. The referrer
is always the authenticated share owner — never client-supplied.
"""

from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from starlette.requests import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.core.frontend_origins import (
    allowed_frontend_return_origin,
    brand_for_hostname,
    request_hostname,
)
from app.entity.share.share_link import ShareLink, ShareStatus, ShareType
from app.entity.user.app_user import AppUser
from app.service.domain.domain_registration_service import DomainRegistrationService

logger = logging.getLogger(__name__)

_FQDN_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?))+$"
)
_TOKEN_LENGTH = 32
_MAX_QUERY_LENGTH = 300

# Aftermarket premium listings (Afternic/Sedo) only operate on common gTLDs —
# probing any other extension would add needless registrar calls for a domain
# that can never be an aftermarket premium.
_AFTERMARKET_PREMIUM_EXTS = {"com", "net", "org", "io", "co"}

# Fields from DomainCheckResponse that must NEVER reach the public preview.
_BLOCKED_PREVIEW_FIELDS = {
    "registrarSandbox",
    "registrarEnv",
    "registrarApiBaseUrl",
    "priceSource",
    "priceCurrency",
    "demoMode",
    "whoisPrivacyAllowed",
    "source",
    "message",
    "unitPrice",
}


def _item_key_for(share_type: ShareType, domain: str | None, listing_id: uuid.UUID | None) -> str:
    """Canonical shared-item identity used for dedupe.

    Domain shares (DOMAIN_SEARCH and AI_BRAND_DOMAIN) share the same key for
    the same domain, so a receiver can only ever earn one reward per sender per
    domain regardless of how many links or share types are involved.
    """
    if share_type == ShareType.MARKETPLACE:
        return f"marketplace:{listing_id}"
    return f"domain:{domain}"


def frontend_share_base_for_request(request: Request | None = None) -> str:
    """Resolve the public SPA origin that should own a generated share link."""
    for header in ("origin", "referer"):
        origin = allowed_frontend_return_origin(
            request.headers.get(header) if request is not None else None
        )
        if origin:
            return origin.rstrip("/")

    brand = brand_for_hostname(request_hostname(request))
    if brand == "deltapreneur":
        return "https://deltapreneur.com"

    base = (settings.FRONTEND_BASE_URL or "").rstrip("/")
    return base or "http://127.0.0.1:5173"


class ShareService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── create ────────────────────────────────────────────────────────────────

    async def create_share(
        self,
        *,
        share_type: ShareType,
        domain: str | None,
        original_query: str | None,
        listing_id: uuid.UUID | None,
        referrer: AppUser | None = None,
        referrer_visitor_key: str | None = None,
    ) -> ShareLink:
        """Create a shareable link.

        ``referrer`` is the authenticated sender; when ``None`` (logged-out
        sender) the share carries no referrer and can never earn Edge Points.
        """
        share_type_value = share_type.value if hasattr(share_type, "value") else str(share_type)

        if share_type_value not in (
            ShareType.DOMAIN_SEARCH.value,
            ShareType.AI_BRAND_DOMAIN.value,
        ):
            raise AppException(
                "Marketplace shares are not enabled yet.",
                status_code=400,
            )

        if not domain or not isinstance(domain, str):
            raise AppException(
                "A domain is required for this share type.",
                status_code=400,
            )
        domain = domain.strip().lower()
        if not _FQDN_RE.fullmatch(domain):
            raise AppException(
                "Invalid domain format. Use name.tld e.g. example.com",
                status_code=400,
            )

        query = (original_query or "").strip()
        if len(query) > _MAX_QUERY_LENGTH:
            raise AppException(
                "Search context is too long.",
                status_code=400,
            )

        share = ShareLink(
            token=secrets.token_urlsafe(24)[:_TOKEN_LENGTH],
            share_type=ShareType(share_type_value),
            referrer_id=referrer.id if referrer else None,
            domain=domain,
            original_query=query or None,
            listing_id=None,
            referrer_visitor_key=referrer_visitor_key or None,
            status=ShareStatus.ACTIVE,
            expires_at=None,
        )
        self._session.add(share)
        await self._session.commit()
        await self._session.refresh(share)
        return share

    def share_url(self, share: ShareLink, request: Request | None = None) -> str:
        base = frontend_share_base_for_request(request)
        return f"{base}/s/{share.token}"

    # ── resolve ───────────────────────────────────────────────────────────────

    async def resolve_share(self, token: str) -> ShareLink | None:
        if not token or not isinstance(token, str):
            return None
        stmt = select(ShareLink).where(
            ShareLink.token == token.strip(),
            ShareLink.status == ShareStatus.ACTIVE,
        )
        res = await self._session.execute(stmt)
        share = res.scalar_one_or_none()
        if share is None:
            return None
        if share.expires_at is not None and share.expires_at.tzinfo is None:
            share.expires_at = share.expires_at.replace(tzinfo=timezone.utc)
        if share.expires_at is not None and share.expires_at < datetime.now(timezone.utc):
            return None
        return share

    async def load_referrer(self, share: ShareLink) -> AppUser | None:
        res = await self._session.execute(
            select(AppUser).where(AppUser.id == share.referrer_id)
        )
        return res.scalar_one_or_none()

    # ── preview ───────────────────────────────────────────────────────────────

    async def build_preview_payload(self, share: ShareLink) -> dict[str, Any]:
        """Sanitized preview payload.

        Always re-runs a **live** registrar availability/pricing check — the
        share record stores no price and no availability. Internal registrar /
        commission / payout fields are never exposed.
        """
        availability: dict[str, Any] = {
            "status": "check_failed",
            "is_premium": False,
            "price_inr": None,
            "total_inr": None,
            "renewal_price_inr": None,
            "min_period_years": None,
            "currency": "INR",
            "checked_at": None,
        }

        if share.domain:
            try:
                check = await DomainRegistrationService(self._session).check_openprovider_domain(
                    share.domain
                )
                availability = {
                    "status": check.status if check.status in ("available", "taken", "marketplace") else "taken",
                    "is_premium": bool(check.isPremium),
                    "price_inr": (
                        round(float(check.unitPrice), 2)
                        if check.unitPrice is not None
                        else None
                    ),
                    "total_inr": (
                        round(float(check.totalInr), 2)
                        if check.totalInr is not None
                        else None
                    ),
                    "renewal_price_inr": (
                        round(float(check.renewalPriceInr), 2)
                        if check.renewalPriceInr is not None
                        else None
                    ),
                    "min_period_years": check.minPeriodYears,
                    "currency": "INR",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }

                # Aftermarket premium classification: a registry "taken" domain
                # can still be a premium Afternic/Sedo listing (e.g. premium
                # marketplace domains like batterify.com). Probe the
                # aftermarket-inclusive check so the shared page shows the
                # correct Standard/Premium classification while preserving the
                # live availability state (status stays "taken"). Only common
                # gTLDs are aftermarket-capable, so the probe is skipped for
                # extensions Afternic/Sedo never serve.
                tld = share.domain.rsplit(".", 1)[-1].lower() if "." in share.domain else ""
                if (
                    availability["status"] == "taken"
                    and not availability["is_premium"]
                    and tld in _AFTERMARKET_PREMIUM_EXTS
                ):
                    try:
                        probe = await DomainRegistrationService(self._session).check_openprovider_domain(
                            share.domain,
                            include_aftermarket=True,
                        )
                        if probe.isPremium:
                            availability["is_premium"] = True
                            # The aftermarket-inclusive check reports premium
                            # listings as available-to-buy (same semantics as
                            # the storefront Premium tab: AVAILABLE + PREMIUM
                            # badges together, Add to Cart enabled).
                            availability["status"] = "available"
                            if probe.unitPrice is not None:
                                availability["price_inr"] = round(float(probe.unitPrice), 2)
                            if probe.totalInr is not None:
                                availability["total_inr"] = round(float(probe.totalInr), 2)
                            if probe.renewalPriceInr is not None:
                                availability["renewal_price_inr"] = round(float(probe.renewalPriceInr), 2)
                            if probe.minPeriodYears is not None:
                                availability["min_period_years"] = probe.minPeriodYears
                            logger.info(
                                "Share preview aftermarket premium classified domain=%s token=%s",
                                share.domain,
                                share.token,
                            )
                    except Exception as probe_exc:
                        logger.warning(
                            "Share preview aftermarket premium probe failed domain=%s token=%s: %s",
                            share.domain,
                            share.token,
                            probe_exc,
                        )
            except Exception as exc:
                logger.warning(
                    "Share preview live check failed domain=%s token=%s: %s",
                    share.domain,
                    share.token,
                    exc,
                )
                availability["checked_at"] = datetime.now(timezone.utc).isoformat()

        return {
            "share_type": share.share_type.value,
            "domain": share.domain,
            "original_query": share.original_query,
            "availability": availability,
            "notice": "Price and availability are subject to change.",
            "listing": None,
        }

    @staticmethod
    def sanitize_domain_check(check) -> dict[str, Any]:
        """(Kept for tests) map a DomainCheckResponse to the public shape."""
        if not check:
            return {}
        return {
            k: v
            for k, v in check.model_dump(mode="json", by_alias=False).items()
            if k not in _BLOCKED_PREVIEW_FIELDS
        }

    # ── social OG meta ─────────────────────────────────────────────────────────

    async def build_og_meta(self, share: ShareLink) -> dict[str, Any]:
        """Rich Open Graph metadata for a tokenized share, for social crawlers.

        Uses the SAME live classification as the shared page (including the
        aftermarket premium probe), so LinkedIn / Facebook / WhatsApp / X etc.
        show the current Standard vs Premium state. Never exposes internal IDs,
        registrar data, referrer identity, commission or Edge Point internals.
        """
        title = f"{share.domain} | Deltapreneur" if share.domain else "Deltapreneur"
        description = (
            f"Shared on Deltapreneur: {share.domain}" if share.domain else "Check out this shared domain on Deltapreneur!"
        )
        query = (share.original_query or "").strip()
        if query:
            description += f" · Search: {query}"
        meta: dict[str, Any] = {
            "title": title,
            "description": description,
            "is_premium": False,
            "status": "available",
            "price_inr": None,
        }
        if not share.domain:
            return meta

        try:
            payload = await self.build_preview_payload(share)
            availability = payload.get("availability") or {}
            is_premium = bool(availability.get("is_premium"))
            status = availability.get("status", "available")
            price_inr = availability.get("price_inr")
            meta["is_premium"] = is_premium
            meta["status"] = status
            meta["price_inr"] = price_inr
            meta["title"] = (
                f"{share.domain} | Premium Domain | Deltapreneur"
                if is_premium
                else f"{share.domain} | Deltapreneur"
            )

            # Live state summary — mirrors the shared page's presentation:
            #   Standard Domain • Available • ₹1,151.82/yr
            #   Premium Domain • Available • ₹33,03,50,008.66 (1st Year)
            #   Domain • Currently unavailable
            state_parts: list[str] = []
            if is_premium:
                state_parts.append("Premium Domain")
            elif status == "available":
                state_parts.append("Standard Domain")
            else:
                state_parts.append("Domain")
            if status == "available":
                state_parts.append("Available")
            elif status == "taken":
                state_parts.append("Currently unavailable")
            if price_inr is not None and price_inr > 0:
                formatted = f"₹{price_inr:,.2f}"
                state_parts.append(f"{formatted}/yr" if not is_premium else f"{formatted} (1st Year)")

            description = " • ".join(state_parts)
            if query:
                description += f" · Search: {query}"
            meta["description"] = description
        except Exception as exc:
            logger.warning(
                "Share OG live classification failed domain=%s token=%s: %s",
                share.domain,
                share.token,
                exc,
            )
        return meta
