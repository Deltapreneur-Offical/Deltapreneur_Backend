"""Tests for AI domain availability checker (OpenProvider integration)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.model.domain.domain_check_response import DomainCheckResponse
from app.schemas.ai_domains import AIDomainAvailability
from app.services.domain_checker import AIDomainChecker, DEFAULT_AI_DOMAIN_TLDS


@pytest.mark.asyncio
async def test_check_many_openprovider_maps_taken_and_available():
    mock_service = MagicMock()
    mock_service.check_openprovider_domain = AsyncMock(
        return_value=DomainCheckResponse(
            status="available",
            domain="veyra.com",
            unitPrice=1280.0,
            priceCurrency="INR",
            source="openprovider",
        ),
    )

    checker = AIDomainChecker(mock_service)
    bulk = [
        {"domain": "veyra.com", "status": "available"},
        {"domain": "veyra.in", "status": "taken"},
    ]

    mock_settings = MagicMock()
    mock_settings.domain_registrar.return_value = "openprovider"

    with (
        patch("app.services.domain_checker.settings", mock_settings),
        patch(
            "app.integrations.openprovider.client.is_configured",
            return_value=True,
        ),
        patch(
            "app.integrations.openprovider.client.check_availability_bulk",
            new_callable=AsyncMock,
            return_value=bulk,
        ),
    ):
        results = await checker.check_many("Veyra", DEFAULT_AI_DOMAIN_TLDS)

    assert results["com"].status == "available"
    assert results["com"].available is True
    assert results["com"].price_inr == 1280.0
    assert results["in"].status == "taken"
    assert results["in"].available is False
    assert results["in"].price_inr is None


@pytest.mark.asyncio
async def test_check_many_openprovider_failure_returns_unknown():
    mock_service = MagicMock()
    checker = AIDomainChecker(mock_service)

    mock_settings = MagicMock()
    mock_settings.domain_registrar.return_value = "openprovider"

    with (
        patch("app.services.domain_checker.settings", mock_settings),
        patch("app.integrations.openprovider.client.is_configured", return_value=True),
        patch(
            "app.integrations.openprovider.client.check_availability_bulk",
            new_callable=AsyncMock,
            side_effect=RuntimeError("HTTP 403"),
        ),
    ):
        results = await checker.check_many("Nuvio", DEFAULT_AI_DOMAIN_TLDS)

    assert results["com"].status == "unknown"
    assert results["in"].status == "unknown"
    assert results["com"].available is False


@pytest.mark.asyncio
async def test_check_many_not_always_available_stub_removed():
    """Regression: checker must not hardcode available=True."""
    mock_service = MagicMock()
    mock_service.check_openprovider_domain = AsyncMock(
        return_value=DomainCheckResponse(
            status="taken",
            domain="google.com",
            source="openprovider",
        ),
    )
    checker = AIDomainChecker(mock_service)

    mock_settings = MagicMock()
    mock_settings.domain_registrar.return_value = "openprovider"

    with patch("app.services.domain_checker.settings", mock_settings):
        results = await checker.check_many("Google", ("com",))

    assert results["com"].status == "taken"
    assert results["com"].available is False


@pytest.mark.asyncio
async def test_check_sanitizes_invalid_name():
    checker = AIDomainChecker(MagicMock())
    result = await checker.check("!!!", "com")
    assert result.status == "unknown"
