"""Mock-based tests for the share system (share_links, visitor cookie,
sanitized preview, atomic referral tracking, schema-missing fallback).

These tests never touch a real database — they exercise the service contracts
with mocked sessions, mirroring the project's unit-test style.
"""

import uuid

import pytest
from starlette.requests import Request
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.exceptions import AppException
from app.entity.share.share_link import ShareLink, ShareStatus, ShareType
from app.entity.user.app_user import AppUser
from app.entity.user.edge_points_history import EdgePointsHistory
from app.entity.user.referral_track import ReferralTrack
from app.service.share.share_service import ShareService, frontend_share_base_for_request
from app.service.share.visitor_cookie import (
    create_visitor_value,
    parse_visitor_value,
)
from app.service.user.edge_points_service import EdgePointsService
from app.model.domain.domain_check_response import DomainCheckResponse

from app.tests.entity_registry import ensure_entities_imported

ensure_entities_imported()


# ── helpers ───────────────────────────────────────────────────────────────────

def _mock_scalar(val):
    mock_res = MagicMock()
    mock_res.scalar.return_value = val
    mock_res.scalar_one_or_none.return_value = val
    return mock_res


class _SchemaMissingError(Exception):
    """Simulates the ProgrammingError raised pre-migration (SQLSTATE 42703)."""

    class _Orig:
        sqlstate = "42703"

    def __init__(self):
        super().__init__("column referral_tracks.item_key does not exist")
        self.orig = self._Orig()


def _share(**overrides):
    share = ShareLink(
        token="a" * 32,
        share_type=ShareType.DOMAIN_SEARCH,
        referrer_id=uuid.uuid4(),
        domain="tidebrew.com",
        original_query="a coffee shop near beach",
        status=ShareStatus.ACTIVE,
    )
    for k, v in overrides.items():
        setattr(share, k, v)
    return share


def _referrer():
    return AppUser(id=uuid.uuid4(), edge_points=100)


def _request_with_headers(**headers):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [
                (name.lower().encode("latin-1"), value.encode("latin-1"))
                for name, value in headers.items()
            ],
        }
    )


# ── visitor cookie ────────────────────────────────────────────────────────────

def test_visitor_cookie_roundtrip():
    value = create_visitor_value()
    parsed = parse_visitor_value(value)
    assert parsed is not None
    uuid.UUID(parsed)  # must be a valid uuid


def test_visitor_cookie_tampered():
    value = create_visitor_value()
    tampered = value[:-1] + ("0" if value[-1] != "0" else "1")
    assert parse_visitor_value(tampered) is None


def test_visitor_cookie_missing_or_malformed():
    assert parse_visitor_value(None) is None
    assert parse_visitor_value("") is None
    assert parse_visitor_value("not-a-cookie") is None


# ── share creation ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_share_invalid_domain():
    session = AsyncMock()
    service = ShareService(session)
    with pytest.raises(AppException):
        await service.create_share(
            share_type=ShareType.DOMAIN_SEARCH,
            domain="not a domain",
            original_query=None,
            listing_id=None,
            referrer=_referrer(),
        )


@pytest.mark.asyncio
async def test_create_share_marketplace_not_enabled():
    session = AsyncMock()
    service = ShareService(session)
    with pytest.raises(AppException, match="not enabled"):
        await service.create_share(
            share_type=ShareType.MARKETPLACE,
            domain=None,
            original_query=None,
            listing_id=uuid.uuid4(),
            referrer=_referrer(),
        )


@pytest.mark.asyncio
async def test_create_share_query_too_long():
    session = AsyncMock()
    service = ShareService(session)
    with pytest.raises(AppException):
        await service.create_share(
            share_type=ShareType.AI_BRAND_DOMAIN,
            domain="tidebrew.com",
            original_query="x" * 500,
            listing_id=None,
            referrer=_referrer(),
        )


@pytest.mark.asyncio
async def test_create_share_success():
    session = AsyncMock()
    referrer = _referrer()
    service = ShareService(session)
    share = await service.create_share(
        share_type=ShareType.DOMAIN_SEARCH,
        domain="POOLOO.IN",
        original_query="  pooolo  ",
        listing_id=None,
        referrer=referrer,
        referrer_visitor_key="cookie-123",
    )
    assert share.domain == "pooloo.in"  # normalized lowercase
    assert share.original_query == "pooolo"  # trimmed
    assert len(share.token) == 32
    assert share.referrer_id == referrer.id
    assert share.referrer_visitor_key == "cookie-123"
    assert share.status == ShareStatus.ACTIVE
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_share_anonymous_no_referrer():
    """Logged-out senders can still create a share, but it carries NO referrer."""
    session = AsyncMock()
    service = ShareService(session)
    share = await service.create_share(
        share_type=ShareType.AI_BRAND_DOMAIN,
        domain="tidebrew.com",
        original_query="a coffee shop near beach",
        listing_id=None,
        referrer=None,  # logged-out sender
    )
    assert share.domain == "tidebrew.com"
    assert len(share.token) == 32
    assert share.referrer_id is None  # no fake/anonymous referrer
    assert share.status == ShareStatus.ACTIVE
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


def test_share_url_uses_deltapreneur_origin():
    session = AsyncMock()
    service = ShareService(session)
    request = _request_with_headers(origin="https://deltapreneur.com")

    assert service.share_url(_share(token="deltaToken123"), request) == "https://deltapreneur.com/s/deltaToken123"


def test_share_url_uses_deltapreneur_host_when_origin_missing():
    session = AsyncMock()
    service = ShareService(session)
    request = _request_with_headers(host="api.deltapreneur.com")

    assert service.share_url(_share(token="deltaToken123"), request) == "https://deltapreneur.com/s/deltaToken123"


def test_share_url_rejects_cobrother_origin(monkeypatch):
    monkeypatch.setattr(
        "app.service.share.share_service.settings.FRONTEND_BASE_URL",
        "https://deltapreneur.com",
    )
    session = AsyncMock()
    service = ShareService(session)
    request = _request_with_headers(origin="https://cobrother.com")

    assert service.share_url(_share(token="coToken123"), request) == "https://deltapreneur.com/s/coToken123"


def test_share_base_ignores_untrusted_origin(monkeypatch):
    monkeypatch.setattr(
        "app.service.share.share_service.settings.FRONTEND_BASE_URL",
        "https://deltapreneur.com",
    )
    request = _request_with_headers(origin="https://evil.example")

    assert frontend_share_base_for_request(request) == "https://deltapreneur.com"


# ── sanitized preview ─────────────────────────────────────────────────────────

async def _mock_check_response():
    return DomainCheckResponse(
        status="available",
        domain="tidebrew.com",
        unitPrice=1151.82,
        subtotalInr=1151.82,
        gstInr=207.33,
        totalInr=1359.15,
        priceCurrency="INR",
        priceSource="registrar_check",
        minPeriodYears=1,
        source="registrar",
        registrarSandbox=True,
        registrarEnv="sandbox",
        registrarApiBaseUrl="https://api.sandbox.openprovider.nl:8480",
        demoMode=False,
        isPremium=False,
        renewalPriceInr=1151.82,
    )


@pytest.mark.asyncio
@patch("app.service.share.share_service.DomainRegistrationService")
async def test_preview_payload_is_sanitized(mock_reg_service):
    mock_reg_service.return_value.check_openprovider_domain = AsyncMock(
        return_value=await _mock_check_response()
    )
    session = AsyncMock()
    service = ShareService(session)
    payload = await service.build_preview_payload(_share())

    avail = payload["availability"]
    assert avail["status"] == "available"
    assert avail["price_inr"] == 1151.82
    assert avail["total_inr"] == 1359.15
    assert avail["renewal_price_inr"] == 1151.82
    assert avail["currency"] == "INR"
    assert payload["domain"] == "tidebrew.com"
    assert payload["original_query"] == "a coffee shop near beach"
    assert payload["notice"]

    # Internal registrar / commission / sandbox data must never leak.
    raw = payload.get("availability", {})
    for blocked in (
        "registrarSandbox",
        "registrarEnv",
        "registrarApiBaseUrl",
        "priceSource",
        "priceCurrency",
        "demoMode",
        "source",
        "unitPrice",
    ):
        assert blocked not in raw, f"blocked field leaked: {blocked}"


@pytest.mark.asyncio
@patch("app.service.share.share_service.DomainRegistrationService")
async def test_preview_check_failed_never_raises(mock_reg_service):
    async def _boom(*args, **kwargs):
        raise RuntimeError("OpenProvider unavailable")

    mock_reg_service.return_value.check_openprovider_domain = _boom
    session = AsyncMock()
    service = ShareService(session)
    payload = await service.build_preview_payload(_share())
    assert payload["availability"]["status"] == "check_failed"
    assert payload["availability"]["price_inr"] is None
    assert payload["domain"] == "tidebrew.com"  # context preserved


@pytest.mark.asyncio
@patch("app.service.share.share_service.DomainRegistrationService")
async def test_preview_taken_standard_never_classified_premium(mock_reg_service):
    """A plain taken domain (no aftermarket premium listing) stays standard."""

    mock_check = AsyncMock(
        side_effect=lambda *args, **kwargs: DomainCheckResponse(
            status="taken",
            domain="plainname.com",
            price=None,
            source="registrar",
            isPremium=False,
        )
    )
    mock_reg_service.return_value.check_openprovider_domain = mock_check
    session = AsyncMock()
    service = ShareService(session)
    payload = await service.build_preview_payload(
        _share(domain="plainname.com", original_query="plainname")
    )
    avail = payload["availability"]
    assert avail["status"] == "taken"
    assert avail["is_premium"] is False
    # plain check + aftermarket probe ran (taken .com is aftermarket-capable)
    assert mock_reg_service.return_value.check_openprovider_domain.await_count == 2


@pytest.mark.asyncio
@patch("app.service.share.share_service.DomainRegistrationService")
async def test_preview_taken_non_aftermarket_tld_no_probe(mock_reg_service):
    """Taken domains on non-aftermarket TLDs skip the premium probe entirely."""

    mock_check = AsyncMock(
        side_effect=lambda *args, **kwargs: DomainCheckResponse(
            status="taken",
            domain="plainname.xyz",
            price=None,
            source="registrar",
            isPremium=False,
        )
    )
    mock_reg_service.return_value.check_openprovider_domain = mock_check
    session = AsyncMock()
    service = ShareService(session)
    payload = await service.build_preview_payload(
        _share(domain="plainname.xyz", original_query="plainname")
    )
    avail = payload["availability"]
    assert avail["status"] == "taken"
    assert avail["is_premium"] is False
    # only the plain check ran — no aftermarket probe for .xyz
    assert mock_reg_service.return_value.check_openprovider_domain.await_count == 1


@pytest.mark.asyncio
@patch("app.service.share.share_service.DomainRegistrationService")
async def test_preview_taken_aftermarket_premium_classified_premium(mock_reg_service):
    """A registry-taken domain with a live Afternic/Sedo premium listing is
    classified premium and becomes available-to-buy (same semantics as the
    storefront Premium tab: AVAILABLE + PREMIUM badges, Add to Cart enabled)."""

    async def _check(domain, **kwargs):
        if kwargs.get("include_aftermarket"):
            return DomainCheckResponse(
                status="available",
                domain=domain,
                unitPrice=330350008.66,
                subtotalInr=330350008.66,
                gstInr=0.0,
                totalInr=389813010.22,
                priceCurrency="INR",
                minPeriodYears=1,
                source="openprovider",
                isPremium=True,
                renewalPriceInr=1047.11,
            )
        return DomainCheckResponse(
            status="taken",
            domain=domain,
            price=None,
            source="registrar",
            isPremium=False,
        )

    mock_reg_service.return_value.check_openprovider_domain = _check
    session = AsyncMock()
    service = ShareService(session)
    payload = await service.build_preview_payload(
        _share(domain="batterify.com", original_query="batterify")
    )
    avail = payload["availability"]
    # registry says taken, but the aftermarket probe found the premium listing
    # → available-to-buy + premium, matching the storefront Premium tab
    assert avail["status"] == "available"
    assert avail["is_premium"] is True
    assert avail["price_inr"] == 330350008.66
    assert avail["renewal_price_inr"] == 1047.11


@pytest.mark.asyncio
@patch("app.service.share.share_service.DomainRegistrationService")
async def test_preview_available_premium_from_registry(mock_reg_service):
    """An available registry premium is classified premium without a probe."""

    mock_check = AsyncMock(
        return_value=DomainCheckResponse(
            status="available",
            domain="premium.ai",
            unitPrice=8809.33,
            totalInr=10394.0,
            priceCurrency="INR",
            minPeriodYears=2,
            source="openprovider",
            isPremium=True,
            renewalPriceInr=8008.49,
        )
    )
    mock_reg_service.return_value.check_openprovider_domain = mock_check
    session = AsyncMock()
    service = ShareService(session)
    payload = await service.build_preview_payload(
        _share(domain="premium.ai", original_query="premium")
    )
    avail = payload["availability"]
    assert avail["status"] == "available"
    assert avail["is_premium"] is True
    assert avail["price_inr"] == 8809.33
    # no aftermarket probe needed for an available premium
    assert mock_reg_service.return_value.check_openprovider_domain.await_count == 1


# ── atomic referral tracking ──────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("app.service.user.edge_points_service.notification_connection_manager")
async def test_track_share_referral_awards_once(mock_ws_manager):
    session = AsyncMock()
    session.add = MagicMock()
    referrer = _referrer()
    share = _share(referrer_id=referrer.id)

    inserted_result = MagicMock()
    inserted_result.first.return_value = (uuid.uuid4(),)
    session.execute.side_effect = [_mock_scalar(referrer), inserted_result]

    result = await EdgePointsService.track_share_referral(
        session, share=share, visitor_ip="203.0.113.5"
    )
    assert result["success"] is True
    assert result["points_awarded"] == 20
    assert referrer.edge_points == 120
    session.add.assert_any_call(referrer)
    # history row added
    added_types = [a.args[0] for a in session.add.call_args_list if a.args]
    assert any(isinstance(x, EdgePointsHistory) and x.points == 20 for x in added_types)


@pytest.mark.asyncio
async def test_track_share_referral_duplicate_no_reward():
    session = AsyncMock()
    session.add = MagicMock()
    referrer = _referrer()
    share = _share(referrer_id=referrer.id)

    dup_result = MagicMock()
    dup_result.first.return_value = None  # DB rejected the insert (duplicate)
    session.execute.side_effect = [_mock_scalar(referrer), dup_result]

    result = await EdgePointsService.track_share_referral(
        session, share=share, visitor_ip="203.0.113.5"
    )
    assert result["points_awarded"] == 0
    assert referrer.edge_points == 100


@pytest.mark.asyncio
async def test_track_share_referral_schema_missing_clean_error():
    session = AsyncMock()
    referrer = _referrer()
    share = _share(referrer_id=referrer.id)

    session.execute.side_effect = [_mock_scalar(referrer), _SchemaMissingError()]

    result = await EdgePointsService.track_share_referral(
        session, share=share, visitor_ip="203.0.113.5"
    )
    assert result["success"] is False
    assert "migration" in result["message"].lower()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_track_share_referral_self_referral_cookie():
    session = AsyncMock()
    referrer = _referrer()
    share = _share(referrer_id=referrer.id, referrer_visitor_key="sender-cookie")

    result = await EdgePointsService.track_share_referral(
        session,
        share=share,
        visitor_ip="203.0.113.9",
        visitor_key_from_cookie="sender-cookie",
    )
    assert result["success"] is False
    assert "Self-referrals" in result["message"]


@pytest.mark.asyncio
async def test_track_share_referral_logged_in_self_referral():
    session = AsyncMock()
    referrer = _referrer()
    share = _share(referrer_id=referrer.id)

    result = await EdgePointsService.track_share_referral(
        session, share=share, visitor_ip="203.0.113.9", visitor_user=referrer
    )
    assert result["success"] is False
    assert "Self-referrals" in result["message"]


@pytest.mark.asyncio
async def test_track_share_referral_anonymous_share_no_reward():
    """A share created by a logged-out sender has NO referrer — never a reward,
    and the server never fabricates an anonymous referrer."""
    session = AsyncMock()
    share = _share(referrer_id=None)
    session.execute.return_value = _mock_scalar(None)  # no referrer exists

    result = await EdgePointsService.track_share_referral(
        session, share=share, visitor_ip="203.0.113.10"
    )
    assert result["success"] is False
    assert "no referrer" in result["message"]
    session.execute.assert_awaited_once()  # only the referrer lookup ran
    session.commit.assert_not_awaited()


# ── legacy path: pre-migration fallback ───────────────────────────────────────

@pytest.mark.asyncio
async def test_legacy_track_schema_missing_falls_back_to_legacy_logic():
    session = AsyncMock()
    session.add = MagicMock()
    referrer = _referrer()

    # execute 1: referrer lookup. execute 2: atomic insert raises (no schema).
    # execute 3: legacy duplicate check returns None (no duplicate) → award 20.
    # execute 4: legacy raw INSERT (result unused).
    no_dup = MagicMock()
    no_dup.scalar_one_or_none.return_value = None
    session.execute.side_effect = [
        _mock_scalar(referrer),
        _SchemaMissingError(),
        no_dup,
        MagicMock(),
    ]

    result = await EdgePointsService.track_referral(
        session, referrer_id=referrer.id, listing_id=uuid.uuid4(), listing_type="domain", visitor_ip="127.0.0.1"
    )
    assert result["success"] is True
    assert result["points_awarded"] == 20
    assert referrer.edge_points == 120
    # legacy raw insert executed with only legacy columns
    executed_args = [c.args for c in session.execute.call_args_list if c.args]
    assert any("INSERT INTO referral_tracks" in str(c.args[0]) for c in session.execute.call_args_list if c.args)


@pytest.mark.asyncio
async def test_legacy_track_schema_missing_duplicate_no_points():
    session = AsyncMock()
    session.add = MagicMock()
    referrer = _referrer()

    dup = MagicMock()
    dup.scalar_one_or_none.return_value = ReferralTrack(points_awarded=20)
    session.execute.side_effect = [
        _mock_scalar(referrer),
        _SchemaMissingError(),
        dup,
        MagicMock(),
    ]

    result = await EdgePointsService.track_referral(
        session, referrer_id=referrer.id, listing_id=uuid.uuid4(), listing_type="domain", visitor_ip="127.0.0.1"
    )
    assert result["points_awarded"] == 0
    assert referrer.edge_points == 100


# ── concurrency contract: two identical requests → exactly one reward ─────────

@pytest.mark.asyncio
async def test_concurrent_identical_requests_single_reward():
    """The DB serializes the guarded INSERT; the service only awards on success."""
    referrer = _referrer()
    share = _share(referrer_id=referrer.id)
    results = []

    async def run_once(session):
        return await EdgePointsService.track_share_referral(
            session, share=share, visitor_ip="203.0.113.5"
        )

    # Request 1: insert succeeds. Request 2: same (referrer, item, visitor) → conflict.
    s1, s2 = AsyncMock(), AsyncMock()
    s1.add = MagicMock()
    s2.add = MagicMock()
    ins1 = MagicMock(); ins1.first.return_value = (uuid.uuid4(),)
    ins2 = MagicMock(); ins2.first.return_value = None
    s1.execute.side_effect = [_mock_scalar(referrer), ins1]
    s2.execute.side_effect = [_mock_scalar(referrer), ins2]

    r1 = await run_once(s1)
    r2 = await run_once(s2)

    assert r1["points_awarded"] == 20
    assert r2["points_awarded"] == 0
    total_awarded = sum(r["points_awarded"] for r in (r1, r2))
    assert total_awarded == 20  # never 40


# ── social OG metadata (rich preview for LinkedIn / Facebook / X / WhatsApp) ──


async def _og_meta_with_availability(is_premium=False, status="available", price_inr=550.0):
    session = AsyncMock()
    service = ShareService(session)
    availability = {
        "status": status,
        "is_premium": is_premium,
        "price_inr": price_inr,
        "total_inr": price_inr,
        "renewal_price_inr": 550.0,
        "min_period_years": 1,
        "currency": "INR",
        "checked_at": "2026-01-01T00:00:00Z",
    }
    with patch.object(
        ShareService,
        "build_preview_payload",
        new=AsyncMock(return_value={"availability": availability}),
    ):
        return await service.build_og_meta(_share())


@pytest.mark.asyncio
async def test_og_meta_standard_domain():
    meta = await _og_meta_with_availability(is_premium=False)
    assert meta["title"] == "tidebrew.com | HubRegistrar"
    assert "Standard Domain" in meta["description"]
    assert "Available" in meta["description"]
    assert "₹550.00/yr" in meta["description"]
    assert "Premium" not in meta["title"]
    assert meta["is_premium"] is False
    assert meta["status"] == "available"


@pytest.mark.asyncio
async def test_og_meta_premium_domain():
    meta = await _og_meta_with_availability(is_premium=True, price_inr=330702616.17)
    assert meta["title"] == "tidebrew.com | Premium Domain | HubRegistrar"
    assert "Premium Domain" in meta["description"]
    assert "₹330,702,616.17 (1st Year)" in meta["description"]
    assert meta["is_premium"] is True


@pytest.mark.asyncio
async def test_og_meta_unavailable_domain():
    meta = await _og_meta_with_availability(is_premium=False, status="taken", price_inr=None)
    assert "Currently unavailable" in meta["description"]
    assert "Available" not in meta["description"]
    assert meta["status"] == "taken"


@pytest.mark.asyncio
async def test_og_meta_preserves_search_context():
    meta = await _og_meta_with_availability(is_premium=False)
    assert "· Search: a coffee shop near beach" in meta["description"]


@pytest.mark.asyncio
async def test_og_meta_falls_back_when_live_check_fails():
    """Crawlers must still get sane metadata even if the registrar check errors."""
    session = AsyncMock()
    service = ShareService(session)
    with patch.object(
        ShareService,
        "build_preview_payload",
        new=AsyncMock(side_effect=RuntimeError("registrar down")),
    ):
        meta = await service.build_og_meta(_share())
    assert meta["title"] == "tidebrew.com | HubRegistrar"
    assert meta["is_premium"] is False
    assert "tidebrew.com" in meta["description"]


@pytest.mark.asyncio
async def test_og_meta_no_internal_data_leaked():
    """OG meta must never expose referrer ids, tokens as ids, or registrar data."""
    meta = await _og_meta_with_availability(is_premium=True)
    blob = f"{meta['title']} {meta['description']}"
    assert "referrer" not in blob.lower()
    assert "openprovider" not in blob.lower()
    assert "commission" not in blob.lower()
    assert "edge" not in blob.lower()
    assert "price_inr" not in blob
