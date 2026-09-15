"""Search backfill hydrates a bounded first page; GST still attaches."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.service.domain.domain_registration_service import (
    DomainRegistrationService,
    _TLD_PRICE_HYDRATE_MAX,
)


@pytest.mark.asyncio
async def test_hydrate_caps_openprovider_calls_and_keeps_gst_on_priced_items():
    missing = [
        {
            "tld": "com",
            "name": f"n{i}",
            "domain": f"n{i}.com",
            "registrationPrice": None,
            "renewalPrice": None,
        }
        for i in range(_TLD_PRICE_HYDRATE_MAX + 4)
    ]
    priced = {
        "tld": "in",
        "name": "priced",
        "domain": "priced.in",
        "registrationPrice": 575.0,
        "renewalPrice": 500.0,
    }
    items = [*missing, priced]
    calls = []

    async def fake_get_domain_price(*_args, **kwargs):
        calls.append(kwargs.get("operation"))
        raise RuntimeError("skip live quote")

    with (
        patch(
            "app.integrations.openprovider.client.get_domain_price",
            side_effect=fake_get_domain_price,
        ),
        patch("app.utils.domain_gst.settings") as mock_settings,
        patch(
            "app.service.domain.domain_commission_config.get_rate",
            return_value=0.15,
        ),
    ):
        mock_settings.DOMAIN_GST_ENABLED = True
        mock_settings.DOMAIN_GST_RATE = 18.0
        mock_settings.DOMAIN_PRICE_GST_INCLUSIVE = False
        await DomainRegistrationService._hydrate_missing_tld_prices(items)

    assert calls.count("create") == _TLD_PRICE_HYDRATE_MAX
    assert calls.count("renew") == _TLD_PRICE_HYDRATE_MAX
    assert priced["registrationPrice"] == 575.0
    assert priced["totalInr"] == 678.5
    assert priced["gstInr"] == 103.5
    assert priced["renewalPrice"] == 500.0
    assert items[-2]["registrationPrice"] is None
    assert "totalInr" not in items[-2]
