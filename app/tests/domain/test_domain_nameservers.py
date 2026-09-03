"""Tests for nameserver parsing, platform validation, and registrar sync.

Covers the ResellerClub → OpenProvider migration fix: stale
``order.custom_nameservers`` must self-heal from registrar state instead of
producing false HTTP 400 rejections on the DNS records endpoints.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.config import settings
from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.integrations.openprovider import client as op_client
from app.service.domain import domain_registration_service as drs
from app.service.domain.domain_registration_followup import DomainRegistrationFollowup
from app.utils.domain_nameservers import (
    parse_order_nameservers,
    set_order_nameservers,
)
from app.utils.registration_enums import RegistrationOrderStatus

OP_2NS = ["ns1.openprovider.nl", "ns2.openprovider.be"]
OP_3NS = ["ns1.openprovider.nl", "ns2.openprovider.be", "ns3.openprovider.eu"]
RC_PARKING = ["dns3.parkpage.foundationapi.com", "dns4.parkpage.foundationapi.com"]
EXTERNAL = ["gail.ns.cloudflare.com", "hank.ns.cloudflare.com"]


@pytest.fixture(autouse=True)
def _configured_defaults(monkeypatch):
    monkeypatch.setattr(
        settings,
        "OPENPROVIDER_DEFAULT_NAMESERVERS",
        "ns1.openprovider.nl,ns2.openprovider.be",
    )


def _order(**kwargs) -> DomainRegistrationOrder:
    o = DomainRegistrationOrder(
        id=uuid4(),
        domain_name="brand",
        domain_extension=".com",
        buyer_id=uuid4(),
        buyer_email="buyer@example.com",
        period_years=1,
        price_inr=999.0,
        status=RegistrationOrderStatus.ACTIVE,
        open_provider_domain_id="12345",
    )
    for k, v in kwargs.items():
        setattr(o, k, v)
    return o


# ── parse_order_nameservers ──────────────────────────────────────────────────


class TestParseOrderNameservers:
    def test_canonical_json_dict(self):
        order = _order(
            custom_nameservers=json.dumps(
                {"hosts": ["NS1.OpenProvider.NL.", "ns2.openprovider.be"], "source": "openprovider"}
            )
        )
        hosts, source = parse_order_nameservers(order)
        assert hosts == OP_2NS
        assert source == "openprovider"

    def test_json_dict_without_hosts(self):
        order = _order(custom_nameservers=json.dumps({"source": "openprovider"}))
        assert parse_order_nameservers(order) == ([], None)

    def test_json_list(self):
        order = _order(custom_nameservers=json.dumps(OP_2NS))
        hosts, source = parse_order_nameservers(order)
        assert hosts == OP_2NS
        assert source == "custom"

    def test_json_string_comma_separated(self):
        order = _order(custom_nameservers=json.dumps("ns1.example.com,ns2.example.com"))
        hosts, source = parse_order_nameservers(order)
        assert hosts == ["ns1.example.com", "ns2.example.com"]
        assert source == "custom"

    def test_legacy_raw_comma_separated(self):
        # Format written by the pre-fix manual nameserver update path.
        order = _order(custom_nameservers=",".join(RC_PARKING))
        hosts, source = parse_order_nameservers(order)
        assert hosts == RC_PARKING
        assert source == "custom"

    def test_single_raw_host(self):
        order = _order(custom_nameservers="ns1.example.com")
        hosts, _ = parse_order_nameservers(order)
        assert hosts == ["ns1.example.com"]

    def test_empty_values(self):
        assert parse_order_nameservers(_order(custom_nameservers=None)) == ([], None)
        assert parse_order_nameservers(_order(custom_nameservers="")) == ([], None)
        assert parse_order_nameservers(_order(custom_nameservers="   ")) == ([], None)

    def test_malformed_json_yields_no_garbage_hosts(self):
        order = _order(custom_nameservers='{"hosts": [')
        hosts, _ = parse_order_nameservers(order)
        assert hosts == []

    def test_deduplicates_and_normalizes(self):
        order = _order(
            custom_nameservers=json.dumps(
                {"hosts": ["NS1.EXAMPLE.COM", "ns1.example.com.", " ns2.example.com "], "source": "custom"}
            )
        )
        hosts, _ = parse_order_nameservers(order)
        assert hosts == ["ns1.example.com", "ns2.example.com"]


class TestSetOrderNameservers:
    def test_roundtrip_canonical_format(self):
        order = _order()
        set_order_nameservers(order, ["NS1.OpenProvider.NL.", "ns2.openprovider.be"], "openprovider")
        data = json.loads(order.custom_nameservers)
        assert data["hosts"] == OP_2NS
        assert data["source"] == "openprovider"
        assert data["syncedAt"]  # debugging timestamp, no schema migration needed
        hosts, source = parse_order_nameservers(order)
        assert hosts == OP_2NS
        assert source == "openprovider"


# ── OpenProvider client: platform nameserver validation ─────────────────────


class TestIsPlatformNameserverSet:
    def test_empty_treated_as_platform_defaults(self):
        assert op_client.is_platform_nameserver_set([]) is True

    def test_configured_two_ns_pair(self):
        assert op_client.is_platform_nameserver_set(OP_2NS) is True

    def test_openprovider_three_ns_group(self):
        # The migrated domain scenario: OP group has 3 members but env lists 2.
        assert op_client.is_platform_nameserver_set(OP_3NS) is True

    def test_subset_of_group(self):
        assert op_client.is_platform_nameserver_set(["ns2.openprovider.be", "ns3.openprovider.eu"]) is True

    def test_external_nameservers_blocked(self):
        assert op_client.is_platform_nameserver_set(EXTERNAL) is False

    def test_resellerclub_parking_blocked(self):
        assert op_client.is_platform_nameserver_set(RC_PARKING) is False

    def test_mixed_platform_and_external_blocked(self):
        assert op_client.is_platform_nameserver_set(["ns1.openprovider.nl", EXTERNAL[0]]) is False

    def test_case_and_trailing_dot_normalized(self):
        assert op_client.is_platform_nameserver_set(["NS1.OPENPROVIDER.NL.", "Ns2.OpenProvider.BE"]) is True

    def test_custom_configured_defaults_accepted(self, monkeypatch):
        monkeypatch.setattr(
            settings, "OPENPROVIDER_DEFAULT_NAMESERVERS", "ns1.cobrother.com,ns2.cobrother.com",
        )
        assert op_client.is_platform_nameserver_set(["ns1.cobrother.com", "ns2.cobrother.com"]) is True
        # OP group members remain valid platform hosts alongside custom defaults.
        assert op_client.is_platform_nameserver_set(OP_3NS) is True

    def test_cobrother_vanity_three_ns_accepted(self):
        assert op_client.is_platform_nameserver_set(
            ["ns1.cobrother.com", "ns2.cobrother.com", "ns3.cobrother.com"]
        ) is True

    def test_hubregistrar_vanity_three_ns_accepted_even_if_env_is_cobrother(self, monkeypatch):
        monkeypatch.setattr(
            settings,
            "OPENPROVIDER_DEFAULT_NAMESERVERS",
            "ns1.cobrother.com,ns2.cobrother.com,ns3.cobrother.com",
        )
        assert op_client.is_platform_nameserver_set(
            ["ns1.hubregistrar.com", "ns2.hubregistrar.com", "ns3.hubregistrar.com"]
        ) is True

    def test_mixed_cobrother_and_hubregistrar_still_platform(self):
        assert op_client.is_platform_nameserver_set(
            ["ns1.cobrother.com", "ns2.hubregistrar.com"]
        ) is True

    def test_default_nameservers_returns_vanity_from_settings(self, monkeypatch):
        monkeypatch.setattr(
            settings,
            "OPENPROVIDER_DEFAULT_NAMESERVERS",
            "ns1.cobrother.com,ns2.cobrother.com,ns3.cobrother.com",
        )
        hosts = op_client.default_nameservers()
        assert hosts == ["ns1.cobrother.com", "ns2.cobrother.com", "ns3.cobrother.com"]
        assert "openprovider" not in ",".join(hosts)

    def test_default_nameservers_returns_hubregistrar_from_settings(self, monkeypatch):
        monkeypatch.setattr(
            settings,
            "OPENPROVIDER_DEFAULT_NAMESERVERS",
            "ns1.hubregistrar.com,ns2.hubregistrar.com,ns3.hubregistrar.com",
        )
        hosts = op_client.default_nameservers()
        assert hosts == ["ns1.hubregistrar.com", "ns2.hubregistrar.com", "ns3.hubregistrar.com"]

    def test_default_nameservers_empty_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "OPENPROVIDER_DEFAULT_NAMESERVERS", "")
        with pytest.raises(RuntimeError, match="OPENPROVIDER_DEFAULT_NAMESERVERS"):
            op_client.default_nameservers()


class TestParseNameserversFromDetails:
    def test_dict_shape(self):
        details = {"name_servers": [{"name": "NS1.OpenProvider.NL."}, {"name": "ns2.openprovider.be"}]}
        assert op_client.parse_nameservers_from_details(details) == OP_2NS

    def test_string_list_shape(self):
        assert op_client.parse_nameservers_from_details({"name_servers": OP_2NS}) == OP_2NS

    def test_missing_or_invalid(self):
        assert op_client.parse_nameservers_from_details({}) == []
        assert op_client.parse_nameservers_from_details({"name_servers": "oops"}) == []
        assert op_client.parse_nameservers_from_details({"name_servers": None}) == []


# ── sync_from_registrar: nameserver refresh ──────────────────────────────────


def _followup() -> DomainRegistrationFollowup:
    followup = DomainRegistrationFollowup(session=AsyncMock())
    followup._orders = AsyncMock()
    return followup


def _sync_patches(details: dict):
    return (
        patch(
            "app.integrations.openprovider.client.get_domain_all_details",
            AsyncMock(return_value=details),
        ),
        patch("app.integrations.openprovider.client.is_configured", return_value=True),
    )


@pytest.mark.asyncio
async def test_sync_heals_stale_resellerclub_nameservers():
    """Migrated domain: DB holds RC parking NS, registrar reports the OP group."""
    order = _order(
        custom_nameservers=json.dumps({"hosts": RC_PARKING, "source": "resellerclub"}),
    )
    details = {
        "status": "ACT",
        "name_servers": [{"name": ns} for ns in OP_3NS],
    }
    p1, p2 = _sync_patches(details)
    with p1, p2:
        await _followup().sync_from_registrar(order)

    hosts, source = parse_order_nameservers(order)
    assert hosts == OP_3NS
    assert source == "openprovider"
    assert drs._order_is_using_default_nameservers(order) is True


@pytest.mark.asyncio
async def test_sync_records_custom_nameservers_set_at_registrar():
    order = _order(custom_nameservers=json.dumps({"hosts": OP_2NS, "source": "openprovider"}))
    details = {"status": "ACT", "name_servers": [{"name": ns} for ns in EXTERNAL]}
    p1, p2 = _sync_patches(details)
    with p1, p2:
        await _followup().sync_from_registrar(order)

    hosts, source = parse_order_nameservers(order)
    assert hosts == EXTERNAL
    assert source == "custom"
    assert drs._order_is_using_default_nameservers(order) is False


@pytest.mark.asyncio
async def test_sync_never_clobbers_when_registrar_returns_no_nameservers():
    stored = json.dumps({"hosts": OP_2NS, "source": "openprovider"})
    order = _order(custom_nameservers=stored)
    details = {"status": "ACT"}  # e.g. pending transfer / unknown shape
    p1, p2 = _sync_patches(details)
    with p1, p2:
        await _followup().sync_from_registrar(order)
    assert order.custom_nameservers == stored


# ── DNS endpoints: refresh-on-failure validation ─────────────────────────────


def _service() -> drs.DomainRegistrationService:
    svc = drs.DomainRegistrationService.__new__(drs.DomainRegistrationService)
    svc._session = AsyncMock()
    svc._orders = AsyncMock()
    svc._followup = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_dns_validation_self_heals_stale_db_row():
    order = _order(
        custom_nameservers=json.dumps({"hosts": RC_PARKING, "source": "resellerclub"}),
        last_registrar_sync_at=None,
    )
    svc = _service()

    async def _sync(o):
        set_order_nameservers(o, OP_3NS, "openprovider")
        return True, o

    svc._followup.sync_from_registrar = AsyncMock(side_effect=_sync)

    await svc._ensure_dns_managed_nameservers(order)  # must not raise

    svc._followup.sync_from_registrar.assert_awaited_once_with(order)
    assert drs._order_is_using_default_nameservers(order) is True


@pytest.mark.asyncio
async def test_dns_validation_blocks_external_nameservers_after_refresh():
    from app.core.exceptions import AppException

    order = _order(
        custom_nameservers=json.dumps({"hosts": EXTERNAL, "source": "custom"}),
        last_registrar_sync_at=None,
    )
    svc = _service()
    svc._followup.sync_from_registrar = AsyncMock(return_value=(True, order))

    with pytest.raises(AppException) as exc_info:
        await svc._ensure_dns_managed_nameservers(order)

    assert exc_info.value.status_code == 400
    svc._followup.sync_from_registrar.assert_awaited_once()


@pytest.mark.asyncio
async def test_dns_validation_recent_sync_skips_registrar_call():
    from app.core.exceptions import AppException

    order = _order(
        custom_nameservers=json.dumps({"hosts": EXTERNAL, "source": "custom"}),
        last_registrar_sync_at=datetime.now(timezone.utc),
    )
    svc = _service()

    with pytest.raises(AppException):
        await svc._ensure_dns_managed_nameservers(order)

    svc._followup.sync_from_registrar.assert_not_awaited()


@pytest.mark.asyncio
async def test_dns_validation_happy_path_makes_no_registrar_call():
    order = _order(custom_nameservers=json.dumps({"hosts": OP_2NS, "source": "openprovider"}))
    svc = _service()

    await svc._ensure_dns_managed_nameservers(order)

    svc._followup.sync_from_registrar.assert_not_awaited()


# ── Lifecycle write paths ────────────────────────────────────────────────────


def test_apply_registrar_registration_stores_canonical_nameservers():
    order = _order(open_provider_domain_id=None)
    svc = _service()
    svc._apply_registrar_registration(
        order,
        {
            "id": "777",
            "status": "ACT",
            "nameservers": OP_2NS,
            "nameserverSource": "openprovider",
        },
    )
    assert order.open_provider_domain_id == "777"
    hosts, source = parse_order_nameservers(order)
    assert hosts == OP_2NS
    assert source == "openprovider"


@pytest.mark.asyncio
async def test_update_nameservers_stores_canonical_json():
    order = _order()
    svc = _service()
    svc.get_order = AsyncMock(return_value=order)
    svc.get_order_detail = AsyncMock(return_value={})
    svc._followup.sync_from_registrar = AsyncMock(return_value=(True, order))

    reg = MagicMock()
    reg.is_configured.return_value = False
    with patch.object(drs, "active_registrar", return_value=reg):
        await svc.update_nameservers(
            order.id, ["NS1.Example.COM.", "ns2.example.com"], buyer=MagicMock(),
        )

    hosts, source = parse_order_nameservers(order)
    assert hosts == ["ns1.example.com", "ns2.example.com"]
    assert source == "custom"
    svc._followup.sync_from_registrar.assert_awaited_once()
