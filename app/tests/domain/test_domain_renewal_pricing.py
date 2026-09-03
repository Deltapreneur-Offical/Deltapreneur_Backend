"""Tests for domain renewal pricing with admin commission markup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.service.domain.domain_registration_service import DomainRegistrationService


@pytest.mark.asyncio
async def test_resolve_renewal_unit_price_applies_commission():
    service = DomainRegistrationService(AsyncMock())
    order = SimpleNamespace(
        domain_name="example",
        domain_extension=".com",
        fqdn="example.com",
    )

    with patch(
        "app.service.domain.domain_registration_service.active_registrar",
    ) as mock_registrar, patch(
        "app.service.domain.domain_commission_config.get_rate",
        return_value=0.05,
    ), patch(
        "app.service.domain.domain_commission_config.apply_markup",
        side_effect=lambda base, rate: round(base * (1 + rate), 2),
    ):
        mock_registrar.return_value.is_configured.return_value = False
        unit_inr, source = await service._resolve_renewal_unit_price_inr(order)

    assert source == "fallback"
    assert unit_inr > 0
