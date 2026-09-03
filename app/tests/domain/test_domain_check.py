"""Tests for GET /api/v1/domain/check (marketplace + OpenProvider)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.service.domain import domain_registration_service as drs_module


@pytest.mark.asyncio
async def test_domain_check_requires_query_param():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/domain/check")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_domain_check_accepts_name_alias():
    mock_result = drs_module.DomainCheckResponse(
        status="taken",
        domain="example.com",
        source="openprovider",
    )
    with patch.object(
        drs_module.DomainRegistrationService,
        "check_registration_domain",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/domain/check",
                params={"name": "example.com"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "taken"
    assert body["domain"] == "example.com"


@pytest.mark.asyncio
async def test_domain_check_new_mode_uses_openprovider_only():
    mock_result = drs_module.DomainCheckResponse(
        status="available",
        domain="coolbrand.com",
        price=752.0,
        source="openprovider",
    )
    with (
        patch.object(
            drs_module.DomainRegistrationService,
            "check_openprovider_domain",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as openprovider_check,
        patch.object(
            drs_module.DomainRegistrationService,
            "check_registration_domain",
            new_callable=AsyncMock,
        ) as registration_check,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/domain/check",
                params={"name": "coolbrand.com", "mode": "new"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "available"
    assert body["source"] == "openprovider"
    openprovider_check.assert_awaited_once_with("coolbrand.com")
    registration_check.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_registration_domain_marketplace_listing():
    from app.entity.cobranding.domain_listing_entity import DomainListing
    from app.utils.marketplace_enums import DomainListingStatus, SaleType

    listing = DomainListing(
        id=uuid4(),
        domain_name="coolbrand",
        domain_extension=".com",
        asking_price=25000.0,
        domain_status=DomainListingStatus.AVAILABLE,
        sale_type=SaleType.ONE_TIME,
        taken_down=False,
    )

    mock_repo = AsyncMock()
    mock_repo.find_active_by_name = AsyncMock(return_value=listing)

    service = drs_module.DomainRegistrationService(session=AsyncMock())
    service._listings = mock_repo

    result = await service.check_registration_domain("coolbrand.com")
    assert result.status == "marketplace"
    assert result.source == "marketplace"
    assert result.listing is not None
    assert result.listing.domainName == "coolbrand"
    assert result.price == 25000.0


@pytest.mark.asyncio
async def test_check_openprovider_domain_ignores_marketplace_listing():
    mock_reg = AsyncMock()
    mock_reg.is_configured = lambda: True
    mock_reg.check_domain = AsyncMock(return_value={"status": "free"})
    mock_reg.get_create_price = AsyncMock(
        return_value={"price": {"reseller": {"currency": "INR", "price": 500.0}}},
    )
    mock_reg.is_free = lambda check: True
    mock_reg.extract_create_price_details = lambda quote, **kw: (
        500.0,
        "INR",
        "openprovider_panel_inr",
    )
    mock_reg.resolve_registration_period = lambda period, ext: 1
    mock_reg.yearly_create_price_from_check = lambda raw, ext: round(float(raw), 2)

    service = drs_module.DomainRegistrationService(session=AsyncMock())

    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "registrar_source", return_value="openprovider"),
        patch.object(drs_module, "is_demo_mode", return_value=False),
    ):
        result = await service.check_openprovider_domain("coolbrand.com")

    assert result.status == "available"
    assert result.source == "registrar"
    assert result.listing is None


@pytest.mark.asyncio
async def test_check_registration_domain_registrar_error_raises():
    """Registrar failures must not return fake 'taken' — surface 502 via AppException."""
    mock_repo = AsyncMock()
    mock_repo.find_active_by_name = AsyncMock(return_value=None)

    mock_reg = AsyncMock()
    mock_reg.is_configured = lambda: True
    mock_reg.check_domain = AsyncMock(
        side_effect=RuntimeError("OpenProvider login failed (HTTP 500): ..."),
    )

    service = drs_module.DomainRegistrationService(session=AsyncMock())
    service._listings = mock_repo

    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "is_demo_mode", return_value=False),
    ):
        with pytest.raises(drs_module.AppException) as exc_info:
            await service.check_registration_domain("apios.com")

    assert exc_info.value.status_code == 502
    assert "Could not verify domain availability" in exc_info.value.message


@pytest.mark.asyncio
async def test_check_registration_domain_registrar_available():
    mock_repo = AsyncMock()
    mock_repo.find_active_by_name = AsyncMock(return_value=None)

    mock_reg = AsyncMock()
    mock_reg.is_configured = lambda: True
    mock_reg.check_domain = AsyncMock(
        return_value={"status": "available", "price": 799.0},
    )
    mock_reg.get_create_price = AsyncMock(
        return_value={"price": 799.0, "currency": "INR"},
    )
    mock_reg.is_free = lambda check: check.get("status") == "available"
    mock_reg.extract_create_price_details = lambda quote, **kw: (
        799.0,
        "INR",
        "openprovider_panel_inr",
    )
    mock_reg.resolve_registration_period = lambda period, ext: 1
    mock_reg.yearly_create_price_from_check = lambda raw, ext: round(float(raw), 2)

    service = drs_module.DomainRegistrationService(session=AsyncMock())
    service._listings = mock_repo

    # Pin commission to 0 so this test isolates the GST breakdown math.
    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "registrar_source", return_value="openprovider"),
        patch.object(drs_module, "is_demo_mode", return_value=False),
        patch(
            "app.service.domain.domain_commission_config.get_rate",
            return_value=0.0,
        ),
    ):
        result = await service.check_registration_domain("newdomain12345.com")

    assert result.status == "available"
    assert result.source == "openprovider"
    assert result.unitPrice == 799.0
    assert result.subtotalInr == 799.0
    assert result.gstInr == 143.82
    assert result.totalInr == 942.82
    assert result.price == 942.82
    assert result.priceCurrency == "INR"
    assert result.priceSource == "openprovider_panel_inr"
    assert result.gstEnabled is True


@pytest.mark.asyncio
async def test_check_registration_domain_includes_commission_markup():
    """The exact-match card price must include the admin commission markup so it
    matches the extensions list and the final checkout total (base + commission
    + GST). The commission is baked into unitPrice, never a separate line item."""
    mock_repo = AsyncMock()
    mock_repo.find_active_by_name = AsyncMock(return_value=None)

    mock_reg = AsyncMock()
    mock_reg.is_configured = lambda: True
    mock_reg.check_domain = AsyncMock(
        return_value={"status": "available", "price": 1000.0},
    )
    mock_reg.get_create_price = AsyncMock(
        return_value={"price": 1000.0, "currency": "INR"},
    )
    mock_reg.is_free = lambda check: check.get("status") == "available"
    mock_reg.extract_create_price_details = lambda quote, **kw: (
        1000.0,
        "INR",
        "openprovider_panel_inr",
    )
    mock_reg.resolve_registration_period = lambda period, ext: 1
    mock_reg.yearly_create_price_from_check = lambda raw, ext: round(float(raw), 2)

    service = drs_module.DomainRegistrationService(session=AsyncMock())
    service._listings = mock_repo

    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "registrar_source", return_value="openprovider"),
        patch.object(drs_module, "is_demo_mode", return_value=False),
        patch(
            "app.service.domain.domain_commission_config.get_rate",
            return_value=0.10,
        ),
    ):
        result = await service.check_registration_domain("newdomain12345.com")

    # 1000 base + 10% commission = 1100 unit price (commission baked in).
    assert result.unitPrice == 1100.0
    assert result.subtotalInr == 1100.0
    # 18% GST on the commission-inclusive subtotal.
    assert result.gstInr == 198.0
    assert result.totalInr == 1298.0


@pytest.mark.asyncio
async def test_homepage_premium_search_uses_non_auction_service():
    from app.service.domain.marketplace_domain_service import MarketplaceDomainService

    with patch.object(
        MarketplaceDomainService,
        "search_listed_non_auction",
        new_callable=AsyncMock,
        return_value=[],
    ) as premium_search:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/domain/search",
                params={"mode": "premium", "query": "ai"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "premium"
    assert body["items"] == []
    premium_search.assert_awaited_once_with("ai")


@pytest.mark.asyncio
async def test_homepage_auction_search_uses_auction_service():
    from app.service.auction.auction_service import AuctionService

    with patch.object(
        AuctionService,
        "search_active_enriched",
        new_callable=AsyncMock,
        return_value=[],
    ) as auction_search:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/domain/search",
                params={"mode": "auction", "query": "ai"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "auction"
    assert body["items"] == []
    auction_search.assert_awaited_once_with("ai", page=1, page_size=50)


@pytest.mark.asyncio
async def test_search_tlds_returns_all_extensions_sorted_by_price():
    """GET /api/v1/domain/search-tlds must return every available OpenProvider extension,
    sorted ascending by registration price, with renewal price when present."""
    raw = [
        {
            "domain": "drymotorjosjkm.com",
            "name": "drymotorjosjkm",
            "extension": "com",
            "status": "free",
            "price": {
                "product": {"currency": "USD", "price": 9.77},
                "reseller": {"currency": "EUR", "price": 9.77},
            },
        },
        {
            "domain": "drymotorjosjkm.shop",
            "name": "drymotorjosjkm",
            "extension": "shop",
            "status": "free",
            "price": {
                "product": {"currency": "USD", "price": 2.50},
                "reseller": {"currency": "EUR", "price": 2.50},
            },
        },
        {
            "domain": "drymotorjosjkm.xyz",
            "name": "drymotorjosjkm",
            "extension": "xyz",
            "status": "free",
            "price": {
                "product": {"currency": "USD", "price": 1.20},
                "reseller": {"currency": "EUR", "price": 1.20},
            },
        },
        {
            "domain": "drymotorjosjkm.club",
            "name": "drymotorjosjkm",
            "extension": "club",
            "status": "free",
            "price": {
                "product": {"currency": "USD", "price": 14.99},
                "reseller": {"currency": "EUR", "price": 14.99},
            },
        },
        # Taken domain should still be returned (not filtered out).
        {
            "domain": "drymotorjosjkm.store",
            "name": "drymotorjosjkm",
            "extension": "store",
            "status": "in use",
            "price": {
                "product": {"currency": "USD", "price": 3.00},
                "reseller": {"currency": "EUR", "price": 3.00},
            },
        },
        # Renewal price present in the reseller block must be passed through.
        {
            "domain": "drymotorjosjkm.town",
            "name": "drymotorjosjkm",
            "extension": "town",
            "status": "free",
            "price": {
                "product": {"currency": "USD", "price": 4.00, "renew": 4.50},
                "reseller": {"currency": "EUR", "price": 4.00, "renew": 4.50},
            },
        },
    ]

    priority_raw = [raw[0]] # .com
    remaining_raw = raw[1:] # .shop, .xyz, .club, .store, .town

    # Fresh cache so this test is deterministic regardless of ordering.
    from app.service.domain import domain_registration_service as drs
    drs._tld_search_cache.clear()

    with patch(
        "app.integrations.openprovider.client.search_domains_label_first_page",
        new_callable=AsyncMock,
        return_value=(priority_raw, True, "com"),
    ) as mock_first, patch(
        "app.integrations.openprovider.client.search_domains_label_remaining",
        new_callable=AsyncMock,
        return_value=(remaining_raw, False, None),
    ) as mock_remaining:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Page 1 = fast first page: only the curated priority TLD (.com).
            resp_page1 = await client.get(
                "/api/v1/domain/search-tlds", params={"name": "drymotorjosjkm"}
            )
            # Page 2 = "Load more": the remaining catalog, price-sorted.
            resp_page2 = await client.get(
                "/api/v1/domain/search-tlds",
                params={"name": "drymotorjosjkm", "page": 2},
            )

    assert resp_page1.status_code == 200
    page1 = resp_page1.json()
    assert [it["tld"] for it in page1["items"]] == [".com"]
    assert page1["moreAvailable"] is True
    mock_first.assert_awaited()

    assert resp_page2.status_code == 200
    page2 = resp_page2.json()
    rem_items = page2["items"]
    mock_remaining.assert_awaited()

    # 'store' was 'in use' so it was filtered out. We should not see it.
    assert all(it["tld"] != ".store" for it in rem_items)

    # Remaining, sorted by registration price:
    # .xyz (1.20) -> .shop (2.50) -> .town (4.00) -> .club (14.99)
    assert [it["tld"] for it in rem_items] == [".xyz", ".shop", ".town", ".club"]
    rem_prices = [it["registrationPrice"] for it in rem_items]
    assert rem_prices == sorted(rem_prices)

    # Check that renewal price is populated when present in the raw data
    town_item = next(it for it in rem_items if it["tld"] == ".town")
    assert town_item["renewalPrice"] is not None

    for it in page1["items"] + rem_items:
        assert it["name"] == "drymotorjosjkm"

@pytest.mark.asyncio
async def test_search_tlds_prices_premium_featured_domain():
    """A premium (exact-match / featured) domain returns its price from the
    `premium.price` block instead of coming back null.

    Reproduces the bug where the cheapest/featured card (e.g. pinksale.courses)
    displayed no price while normal reseller-priced TLDs displayed correctly.
    """
    raw = [
        # Premium exact-match domain: price lives under premium.price.create,
        # with no usable reseller/product price block. This is the featured card.
        {
            "domain": "pinksale.courses",
            "name": "pinksale",
            "extension": "courses",
            "status": "free",
            "is_premium": True,
            "premium": {"price": {"create": 146.59, "renew": 146.59}},
            "price": {"reseller": {"currency": "INR"}},
        },
        # Ordinary reseller-priced TLD (control) — must keep working.
        {
            "domain": "pinksale.club",
            "name": "pinksale",
            "extension": "club",
            "status": "free",
            "price": {
                "product": {"currency": "INR", "price": 147.0},
                "reseller": {"currency": "INR", "price": 147.0},
            },
        },
    ]

    from app.service.domain import domain_registration_service as drs
    drs._tld_search_cache.clear()

    with patch(
        "app.integrations.openprovider.client.search_domains_label_first_page",
        new_callable=AsyncMock,
        return_value=(raw, False, None),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/domain/search-tlds", params={"name": "pinksale"}
            )

    assert resp.status_code == 200
    items = resp.json()["items"]

    premium_item = next(it for it in items if it["tld"] == ".courses")
    # The featured/premium domain must carry a valid, non-null registration price.
    assert premium_item["registrationPrice"] is not None
    assert premium_item["registrationPrice"] > 0
    assert premium_item["isPremium"] is True
    assert premium_item["registryTier"] == "premium"
    # Renewal list price reflects exact raw OpenProvider renewal price.
    assert premium_item["renewalPrice"] == 146.59

    club_item = next(it for it in items if it["tld"] == ".club")
    assert club_item["registrationPrice"] is not None
    assert club_item["registrationPrice"] > 0
    assert club_item.get("isPremium") is False


@pytest.mark.asyncio
async def test_search_tlds_premium_scalar_price_does_not_fallback_to_create_for_renewal():
    raw = [
        {
            "domain": "swara.org",
            "name": "swara",
            "extension": "org",
            "status": "free",
            "is_premium": True,
            "premium": {"price": 220214.49},
            "price": {"reseller": {"price": 220214.49, "currency": "INR"}},
        },
    ]
    renew_quote = {
        "price": {
            "product": {"price": 11.2, "currency": "USD"},
            "reseller": {"price": 1118.64, "currency": "INR"},
        },
        "is_premium": False,
    }

    from app.service.domain import domain_registration_service as drs
    drs._tld_search_cache.clear()

    with patch(
        "app.integrations.openprovider.client.search_domains_label_first_page",
        new_callable=AsyncMock,
        return_value=(raw, False, None),
    ), patch(
        "app.integrations.openprovider.client.get_domain_price",
        new_callable=AsyncMock,
        return_value=renew_quote,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/domain/search-tlds", params={"name": "swara"}
            )

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["registrationPrice"] is not None
    assert item["registrationPrice"] > 0
    # Renewal must come from GetPrice(operation=renew), never registration/create.
    assert item["renewalPrice"] == 1118.64
    assert item["renewalPrice"] != item["registrationPrice"]


@pytest.mark.asyncio
async def test_search_tlds_uses_reseller_price_when_panel_factor_disabled():
    """With OPENPROVIDER_PANEL_INR_FACTOR <= 1.0 (default), the extensions list
    must show the raw OpenProvider reseller INR — same as the exact-match card —
    so 0% admin commission equals wholesale API price with no hidden uplift."""
    from app.core.config import settings

    raw = [
        {
            "domain": "mypeaceandsoul.com",
            "name": "mypeaceandsoul",
            "extension": "com",
            "status": "free",
            "price": {
                "product": {"currency": "USD", "price": 10.0},
                "reseller": {"currency": "INR", "price": 1000.0},
            },
        },
    ]

    from app.service.domain import domain_registration_service as drs
    drs._tld_search_cache.clear()

    with (
        patch.object(settings, "OPENPROVIDER_PANEL_INR_FACTOR", 1.0),
        patch(
            "app.integrations.openprovider.client.search_domains_label_first_page",
            new_callable=AsyncMock,
            return_value=(raw, False, None),
        ),
        patch(
            "app.service.domain.domain_commission_config.get_rate",
            return_value=0.0,
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/domain/search-tlds", params={"name": "mypeaceandsoul"}
            )

    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["registrationPrice"] == 1000.0


@pytest.mark.asyncio
async def test_search_tlds_applies_optional_panel_inr_factor_when_enabled():
    """When OPENPROVIDER_PANEL_INR_FACTOR > 1.0 is explicitly enabled, list and
    card share the same uplifted INR (legacy FX bridge)."""
    from app.core.config import settings
    import math

    raw = [
        {
            "domain": "mypeaceandsoul.com",
            "name": "mypeaceandsoul",
            "extension": "com",
            "status": "free",
            "price": {
                "product": {"currency": "USD", "price": 10.0},
                "reseller": {"currency": "INR", "price": 1000.0},
            },
        },
    ]

    from app.service.domain import domain_registration_service as drs
    drs._tld_search_cache.clear()
    factor = 1.114074

    with (
        patch.object(settings, "OPENPROVIDER_PANEL_INR_FACTOR", factor),
        patch(
            "app.integrations.openprovider.client.search_domains_label_first_page",
            new_callable=AsyncMock,
            return_value=(raw, False, None),
        ),
        patch(
            "app.service.domain.domain_commission_config.get_rate",
            return_value=0.0,
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/domain/search-tlds", params={"name": "mypeaceandsoul"}
            )

    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["registrationPrice"] == float(math.floor(1000.0 * factor))


@pytest.mark.asyncio
async def test_search_tlds_requires_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/domain/search-tlds")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_check_openprovider_domain_normalizes_ai_check_total_to_one_year():
    """Storefront must show 1-year unitPrice even when OP check embeds the 2yr .ai total."""
    mock_repo = AsyncMock()
    mock_repo.find_active_by_name = AsyncMock(return_value=None)

    mock_reg = AsyncMock()
    mock_reg.is_configured = lambda: True
    mock_reg.check_domain = AsyncMock(
        return_value={
            "status": "free",
            "price": {"reseller": {"currency": "INR", "price": 16167.61}},
        },
    )
    # Search uses CheckDomain only — GetPrice is reserved for checkout.
    mock_reg.get_create_price = AsyncMock(side_effect=RuntimeError("should not be called"))
    mock_reg.is_free = lambda check: True
    mock_reg.extract_create_price_details = lambda quote, **kw: (
        float((quote.get("price") or {}).get("reseller", {}).get("price") or 0),
        "INR",
        "registrar_check",
    )
    mock_reg.resolve_registration_period = (
        lambda period, ext: 2 if str(ext).lower() == "ai" else max(1, period)
    )
    mock_reg.yearly_create_price_from_check = (
        lambda raw, ext: round(float(raw) / 2, 2)
        if str(ext).lower() == "ai"
        else round(float(raw), 2)
    )
    mock_reg.is_private_whois_allowed = AsyncMock(return_value=True)

    service = drs_module.DomainRegistrationService(session=AsyncMock())
    service._listings = mock_repo

    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "registrar_source", return_value="openprovider"),
        patch.object(drs_module, "is_demo_mode", return_value=False),
        patch(
            "app.service.domain.domain_commission_config.calculate_customer_price",
            side_effect=lambda provider_price, **kw: {
                "providerUnitInr": float(provider_price),
                "customerUnitInr": float(provider_price),
                "commissionRate": 0.0,
                "commissionService": "registration",
                "isPremium": False,
                "registryTier": "standard",
                "currency": "INR",
                "providerCurrency": "INR",
            },
        ),
    ):
        result = await service.check_registration_domain("batterify.ai")

    assert result.status == "available"
    assert result.unitPrice == 8083.81
    assert result.subtotalInr == 8083.81
    assert result.minPeriodYears == 2
    # GST on the 1-year unit only — not on the 2-year check total.
    assert result.gstInr == round(8083.81 * 0.18, 2)
    mock_reg.get_create_price.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_openprovider_domain_uses_check_price_not_get_price():
    """Exact-match search uses CheckDomain only (no GetPrice during search)."""
    mock_repo = AsyncMock()
    mock_repo.find_active_by_name = AsyncMock(return_value=None)

    mock_reg = AsyncMock()
    mock_reg.is_configured = lambda: True
    mock_reg.check_domain = AsyncMock(
        return_value={
            "status": "free",
            "price": {"reseller": {"currency": "INR", "price": 16167.61}},
        },
    )
    mock_reg.get_create_price = AsyncMock(
        return_value={"price": {"reseller": {"currency": "INR", "price": 8083.8}}},
    )
    mock_reg.is_free = lambda check: True
    mock_reg.extract_create_price_details = lambda quote, **kw: (
        float((quote.get("price") or {}).get("reseller", {}).get("price") or 0),
        "INR",
        "openprovider_check",
    )
    mock_reg.resolve_registration_period = (
        lambda period, ext: 2 if str(ext).lower() == "ai" else max(1, period)
    )
    mock_reg.yearly_create_price_from_check = (
        lambda raw, ext: round(float(raw) / 2, 2)
        if str(ext).lower() == "ai"
        else round(float(raw), 2)
    )
    mock_reg.is_private_whois_allowed = AsyncMock(return_value=True)

    service = drs_module.DomainRegistrationService(session=AsyncMock())
    service._listings = mock_repo

    with (
        patch.object(drs_module, "active_registrar", return_value=mock_reg),
        patch.object(drs_module, "registrar_source", return_value="openprovider"),
        patch.object(drs_module, "is_demo_mode", return_value=False),
        patch(
            "app.service.domain.domain_commission_config.calculate_customer_price",
            side_effect=lambda provider_price, **kw: {
                "providerUnitInr": float(provider_price),
                "customerUnitInr": float(provider_price),
                "commissionRate": 0.0,
                "commissionService": "registration",
                "isPremium": False,
                "registryTier": "standard",
                "currency": "INR",
                "providerCurrency": "INR",
            },
        ),
    ):
        result = await service.check_registration_domain("batterify.ai")

    assert result.status == "available"
    assert result.unitPrice == 8083.81
    mock_reg.get_create_price.assert_not_awaited()
    mock_reg.check_domain.assert_awaited()


@pytest.mark.asyncio
async def test_build_tld_items_normalizes_ai_registration_price():
    raw = [
        {
            "domain": "batterify.ai",
            "name": "batterify",
            "extension": "ai",
            "status": "free",
            "price": {
                "reseller": {"currency": "INR", "price": 16167.61},
            },
        },
        {
            "domain": "batterify.com",
            "name": "batterify",
            "extension": "com",
            "status": "free",
            "price": {
                "reseller": {"currency": "INR", "price": 999.0},
            },
        },
    ]
    with (
        patch(
            "app.service.domain.domain_commission_config.get_rate",
            return_value=0.0,
        ),
        patch.object(drs_module, "registrar_source", return_value="openprovider"),
        patch.object(drs_module.settings, "OPENPROVIDER_PANEL_INR_FACTOR", 1.0),
    ):
        items = drs_module.DomainRegistrationService._build_tld_items(raw, "batterify")

    by_tld = {it["tld"]: it for it in items}
    assert by_tld[".ai"]["registrationPrice"] == 8083.81
    assert by_tld[".ai"]["minPeriodYears"] == 2
    assert by_tld[".com"]["registrationPrice"] == 999.0
    assert by_tld[".com"]["minPeriodYears"] == 1
