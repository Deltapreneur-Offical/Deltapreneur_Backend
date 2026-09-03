"""Domain listing verification (WHOIS email + DNS + META_TAG)."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.integrations.whois.rdap import (
    _emails_from_vcard,
    pick_registrant_email,
)
from app.core.exceptions import AppException
from app.service.domain.verification_service import DomainVerificationService
from app.utils.email_mask import mask_email
from app.utils.marketplace_enums import VerificationMethod


def test_mask_email() -> None:
    assert mask_email("owner@novabridge.com") == "o***@novabridge.com"


def test_emails_from_vcard() -> None:
    vcard = [
        "vcard",
        [
            ["version", {}, "text", "4.0"],
            ["email", {}, "text", "admin@Example.COM"],
        ],
    ]
    assert _emails_from_vcard(vcard) == ["admin@example.com"]


def test_pick_registrant_email_prefers_registrant() -> None:
    by_role = {
        "registrant": ["reg@x.com"],
        "administrative": ["admin@x.com"],
    }
    assert pick_registrant_email(by_role) == "reg@x.com"


def test_pick_registrant_email_ignores_abuse_only() -> None:
    by_role = {"abuse": ["abuse@unstoppabledomains.com"]}
    assert pick_registrant_email(by_role) is None


@pytest.mark.asyncio
async def test_init_meta_tag_returns_instructions() -> None:
    listing_id = uuid4()
    user_id = uuid4()
    listing = MagicMock()
    listing.id = listing_id
    listing.listed_by_user_id = user_id
    listing.domain_name = "novabridge"
    listing.domain_extension = ".com"
    listing.verification_token = None
    listing.verification_method = None
    listing.verified = False

    session = AsyncMock()
    session.commit = AsyncMock()
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=listing)
    repo.save = AsyncMock(side_effect=lambda x: x)

    actor = MagicMock()
    actor.id = user_id

    service = DomainVerificationService(session)
    service._repo = repo

    result = await service.init_verification(listing_id, "META_TAG", actor=actor)

    assert result.success is True
    assert result.meta_tag is not None
    assert "cobrother-domain-verification" in result.meta_tag
    assert result.file_path == "/.well-known/cobrother-domain-verification.txt"
    assert result.file_content is not None
    assert result.instructions
    assert listing.verification_method == VerificationMethod.META_TAG


@pytest.mark.asyncio
async def test_check_meta_tag_marks_verified_from_meta() -> None:
    listing_id = uuid4()
    user_id = uuid4()
    listing = MagicMock()
    listing.id = listing_id
    listing.listed_by_user_id = user_id
    listing.domain_name = "novabridge"
    listing.domain_extension = ".com"
    listing.verification_token = "tok123"
    listing.verification_method = VerificationMethod.META_TAG
    listing.verified = False

    session = AsyncMock()
    session.commit = AsyncMock()
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=listing)
    repo.save = AsyncMock(side_effect=lambda x: x)

    actor = MagicMock()
    actor.id = user_id

    service = DomainVerificationService(session)
    service._repo = repo

    with (
        patch(
            "app.service.domain.verification_service.domain_has_meta_verification",
            return_value=True,
        ),
        patch(
            "app.service.domain.verification_service.domain_has_verification_file",
            return_value=False,
        ),
    ):
        result = await service.check_verification(listing_id, actor=actor)

    assert result.success is True
    assert listing.verified is True
    assert listing.verification_token is None


@pytest.mark.asyncio
async def test_init_whois_email_blocked_when_disabled() -> None:
    listing_id = uuid4()
    user_id = uuid4()
    listing = MagicMock()
    listing.id = listing_id
    listing.listed_by_user_id = user_id

    session = AsyncMock()
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=listing)

    actor = MagicMock()
    actor.id = user_id

    service = DomainVerificationService(session)
    service._repo = repo

    mock_settings = MagicMock()
    mock_settings.domain_verification_whois_email_enabled.return_value = False
    with patch(
        "app.service.domain.verification_service.settings",
        mock_settings,
    ):
        with pytest.raises(AppException) as exc_info:
            await service.init_verification(
                listing_id,
                "WHOIS_EMAIL",
                actor=actor,
            )
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_init_whois_email_sends_mail() -> None:
    listing_id = uuid4()
    user_id = uuid4()
    listing = MagicMock()
    listing.id = listing_id
    listing.listed_by_user_id = user_id
    listing.domain_name = "novabridge"
    listing.domain_extension = ".com"
    listing.verification_token = None
    listing.verification_method = None
    listing.whois_email = None
    listing.verified = False

    session = AsyncMock()
    session.commit = AsyncMock()
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=listing)
    repo.save = AsyncMock(side_effect=lambda x: x)

    actor = MagicMock()
    actor.id = user_id

    service = DomainVerificationService(session)
    service._repo = repo

    with (
        patch(
            "app.service.domain.verification_service.lookup_registrant_email",
            new_callable=AsyncMock,
            return_value="admin@novabridge.com",
        ),
        patch(
            "app.service.domain.verification_service.MailService.send_domain_verification_email",
            new_callable=AsyncMock,
        ) as send_mail,
    ):
        result = await service.init_verification(
            listing_id,
            "WHOIS_EMAIL",
            actor=actor,
        )

    assert result.success is True
    assert "a***@novabridge.com" in result.message
    assert result.verification_token is None
    send_mail.assert_awaited_once()
    assert listing.whois_email == "a***@novabridge.com"


@pytest.mark.asyncio
async def test_confirm_with_token_marks_verified() -> None:
    listing_id = uuid4()
    token = "secret-token-value"
    listing = MagicMock()
    listing.id = listing_id
    listing.listed_by_user_id = uuid4()
    listing.verification_method = VerificationMethod.WHOIS_EMAIL
    listing.verification_token = token
    listing.verified = False

    session = AsyncMock()
    session.commit = AsyncMock()
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=listing)
    repo.save = AsyncMock(side_effect=lambda x: x)

    service = DomainVerificationService(session)
    service._repo = repo

    result = await service.confirm_with_token(listing_id, token=token)

    assert result.success is True
    assert listing.verified is True
    assert listing.verification_token is None
