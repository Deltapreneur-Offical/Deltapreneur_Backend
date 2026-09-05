"""Domain ownership verification (DNS TXT / META TAG / WHOIS email)."""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.entity.user.app_user import AppUser
from app.integrations.domain.dns_verify import domain_has_verification_txt
from app.integrations.domain.html_verify import (
    build_meta_tag,
    domain_has_meta_verification,
    domain_has_verification_file,
)
from app.integrations.whois.rdap import lookup_registrant_email
from app.model.marketplace.domain_listing_response import DomainVerificationResponse
from app.repository.domain_listing_repository import DomainListingRepository
from app.service.auth.mail_service import MailService
from app.utils.email_mask import mask_email
from app.utils.marketplace_enums import VerificationMethod

logger = logging.getLogger(__name__)

_VERIFICATION_PREFIX = "cobrother-verify-"
_FILE_PATH = "/.well-known/cobrother-domain-verification.txt"


class DomainVerificationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DomainListingRepository(session)

    async def _get_owned_listing(
        self,
        listing_id: uuid.UUID,
        *,
        actor: AppUser | None = None,
        admin: bool = False,
    ):
        listing = await self._repo.get_by_id(listing_id)
        if listing is None:
            raise AppException("Domain listing not found.", status_code=404)
        if not admin and actor is not None and listing.listed_by_user_id != actor.id:
            raise AppException("Not authorized.", status_code=403)
        return listing

    async def _resolve_whois_email(self, fqdn: str) -> str:
        override = (settings.DOMAIN_VERIFICATION_WHOIS_EMAIL_OVERRIDE or "").strip()
        if override:
            return override.lower()
        email = await lookup_registrant_email(fqdn)
        if not email:
            raise AppException(
                "Could not find a registrant email for this domain. "
                "WHOIS may be privacy-protected — use DNS verification instead.",
                status_code=400,
            )
        return email

    async def _persist_listing(self, listing) -> None:
        try:
            await self._repo.save(listing)
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "verification persist failed listing_id=%s method=%s",
                listing.id,
                listing.verification_method,
            )
            err = str(exc).lower()
            if "meta_tag" in err or "verification_method_enum" in err:
                raise AppException(
                    "HTML meta/file verification is not enabled on the database yet. "
                    "Use DNS TXT verification, or run: alembic upgrade head on the server.",
                    status_code=503,
                ) from exc
            raise AppException(
                "Could not save verification state. Try again or contact support.",
                status_code=500,
            ) from exc

    async def _mark_verified(self, listing) -> DomainVerificationResponse:
        listing.verified = True
        listing.verified_at = datetime.now(timezone.utc)
        listing.verification_token = None
        listing.updated_at = datetime.now(timezone.utc)
        await self._persist_listing(listing)
        return DomainVerificationResponse(
            success=True,
            message="Domain ownership verified.",
        )

    async def init_verification(
        self,
        listing_id: uuid.UUID,
        method: str,
        *,
        actor: AppUser | None = None,
        admin: bool = False,
    ) -> DomainVerificationResponse:
        listing = await self._get_owned_listing(listing_id, actor=actor, admin=admin)

        method_upper = method.upper()
        try:
            verification_method = VerificationMethod(method_upper)
        except ValueError:
            raise AppException(
                "Invalid verification method. Use DNS, META_TAG, or WHOIS_EMAIL.",
                status_code=400,
            )

        if (
            verification_method == VerificationMethod.WHOIS_EMAIL
            and not settings.mail_configured()
        ):
            raise AppException(
                "WHOIS email verification is unavailable because email is not configured "
                "on the server. Use DNS TXT or HTML meta/file verification instead.",
                status_code=503,
            )

        if (
            verification_method == VerificationMethod.WHOIS_EMAIL
            and not settings.domain_verification_whois_email_enabled()
        ):
            raise AppException(
                "WHOIS email verification is unavailable. "
                "Use DNS TXT or HTML meta/file verification instead.",
                status_code=503,
            )

        token = secrets.token_urlsafe(32)
        listing.verification_token = token
        listing.verification_method = verification_method
        listing.updated_at = datetime.now(timezone.utc)

        fqdn = f"{listing.domain_name}{listing.domain_extension}"

        if verification_method == VerificationMethod.DNS:
            record = f"{_VERIFICATION_PREFIX}{token}"
            await self._persist_listing(listing)
            return DomainVerificationResponse(
                success=True,
                message=f"Add a TXT record on {fqdn} with value: {record}",
                verification_token=token,
                dns_record=record,
                instructions=[
                    f"Open your DNS provider for {fqdn}.",
                    "Add a TXT record on the root domain (@).",
                    f"Set TXT value to: {record}",
                    "Wait for DNS propagation, then click Check Verification.",
                ],
            )

        if verification_method == VerificationMethod.META_TAG:
            value = f"{_VERIFICATION_PREFIX}{token}"
            meta_tag = build_meta_tag(value)
            await self._persist_listing(listing)
            return DomainVerificationResponse(
                success=True,
                message="Add either the meta tag in <head> OR upload verification file.",
                verification_token=token,
                meta_tag=meta_tag,
                file_path=_FILE_PATH,
                file_content=value,
                instructions=[
                    "Open your website source deployed on this domain.",
                    "Option A: Add the meta tag in the <head> of the homepage.",
                    "Option B: Host a text file at the exact file path shown.",
                    "For file option, keep file content exactly as provided.",
                    "Deploy changes, then click Check Verification.",
                ],
            )

        registrant_email = await self._resolve_whois_email(fqdn)
        listing.whois_email = mask_email(registrant_email)

        try:
            await MailService.send_domain_verification_email(
                to_email=registrant_email,
                fqdn=fqdn,
                listing_id=str(listing_id),
                verification_token=token,
            )
        except Exception as exc:
            logger.exception(
                "Failed to send domain verification email listing_id=%s",
                listing_id,
            )
            raise AppException(
                "Could not send verification email. "
                "Use DNS TXT or HTML meta/file verification instead, "
                "or fix MAIL_* settings on the server.",
                status_code=503,
            ) from exc

        await self._persist_listing(listing)
        return DomainVerificationResponse(
            success=True,
            message=(
                f"Verification email sent to {listing.whois_email}. "
                "Open the link in that inbox to complete verification."
            ),
            instructions=[
                f"Open mailbox: {listing.whois_email}",
                "Find verification mail from Deltapreneur.",
                "Click verification link in that email.",
                "Come back and click Check Verification.",
            ],
        )

    async def check_verification(
        self,
        listing_id: uuid.UUID,
        *,
        token: str | None = None,
        actor: AppUser | None = None,
        admin: bool = False,
    ) -> DomainVerificationResponse:
        listing = await self._get_owned_listing(listing_id, actor=actor, admin=admin)

        if listing.verified:
            return DomainVerificationResponse(
                success=True,
                message="Domain is already verified.",
            )

        if listing.verification_method == VerificationMethod.DNS:
            expected = listing.verification_token
            if not expected:
                return DomainVerificationResponse(
                    success=False,
                    message="Start DNS verification first.",
                )
            fqdn = f"{listing.domain_name}{listing.domain_extension}"
            record = f"{_VERIFICATION_PREFIX}{expected}"
            if domain_has_verification_txt(fqdn, record):
                return await self._mark_verified(listing)
            if token and secrets.compare_digest(token, expected):
                return await self._mark_verified(listing)
            return DomainVerificationResponse(
                success=False,
                message="DNS TXT record not found yet. Add the TXT record and try again.",
            )

        if listing.verification_method == VerificationMethod.META_TAG:
            expected = listing.verification_token
            if not expected:
                return DomainVerificationResponse(
                    success=False,
                    message="Start META_TAG verification first.",
                )
            fqdn = f"{listing.domain_name}{listing.domain_extension}"
            value = f"{_VERIFICATION_PREFIX}{expected}"
            if domain_has_meta_verification(fqdn, value):
                return await self._mark_verified(listing)
            if domain_has_verification_file(fqdn, value, file_path=_FILE_PATH):
                return await self._mark_verified(listing)
            if token and secrets.compare_digest(token, expected):
                return await self._mark_verified(listing)
            return DomainVerificationResponse(
                success=False,
                message=(
                    "Meta tag/file not found yet. Publish the meta tag or verification file "
                    "and try again."
                ),
            )

        if listing.verification_method == VerificationMethod.WHOIS_EMAIL:
            expected = listing.verification_token
            if token and expected and secrets.compare_digest(token, expected):
                return await self._mark_verified(listing)
            return DomainVerificationResponse(
                success=False,
                message="Invalid or missing verification token.",
            )

        return DomainVerificationResponse(
            success=False,
            message="Verification failed.",
        )

    async def confirm_with_token(
        self,
        listing_id: uuid.UUID,
        *,
        token: str,
    ) -> DomainVerificationResponse:
        """Public confirm via email link (token proves inbox access)."""
        listing = await self._get_owned_listing(listing_id, actor=None)
        if listing.verification_method != VerificationMethod.WHOIS_EMAIL:
            raise AppException(
                "Email confirmation is only for WHOIS_EMAIL verification.",
                status_code=400,
            )
        expected = listing.verification_token
        if not expected or not secrets.compare_digest(token.strip(), expected):
            raise AppException("Invalid or expired verification link.", status_code=400)
        return await self._mark_verified(listing)
