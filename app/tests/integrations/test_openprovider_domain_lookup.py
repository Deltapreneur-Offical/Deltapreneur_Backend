"""OpenProvider domain list lookup must parse the official nested payload."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from app.integrations.openprovider import client as op_client

HUBREGISTRAR_OP_RECORD = {
    "id": 30145282,
    "status": "ACT",
    "owner_handle": "XX-HUB-IN",
    "admin_handle": "XX-HUB-IN",
    "owner": {"full_name": "Neminath Akkole", "company_name": ""},
    "domain": {"name": "hubregistrar", "extension": "in"},
    "expiration_date": "2027-08-27 00:00:00",
    "verification_email_name": "neminath.akkole01@gmail.com",
    "verification_email_status": "not verified",
}


def test_nested_list_item_yields_provider_id():
    """Official list results nest SLD/TLD under domain — top-level name/extension are absent."""
    results = [HUBREGISTRAR_OP_RECORD]
    assert op_client._domain_id_from_search_results("hubregistrar.in", results) == "30145282"
    record = op_client._domain_record_from_search_results("hubregistrar.in", results)
    assert record is not None
    assert record["owner_handle"] == "XX-HUB-IN"
    assert record["verification_email_name"] == "neminath.akkole01@gmail.com"
    assert record["domain"] == {"name": "hubregistrar", "extension": "in"}


def test_nested_list_item_does_not_match_other_fqdn():
    assert op_client._domain_id_from_search_results("otherbrand.com", [HUBREGISTRAR_OP_RECORD]) is None


def test_legacy_flat_name_extension_still_matches():
    results = [{"id": "99", "name": "brand", "extension": "com"}]
    assert op_client._domain_id_from_search_results("brand.com", results) == "99"


def test_lookup_query_uses_full_name_then_sld_plus_extension():
    variants = op_client._lookup_domain_query_variants("hubregistrar.in")
    assert variants[0]["full_name"] == "hubregistrar.in"
    assert "domain_name_pattern" not in variants[0]
    assert variants[1]["domain_name_pattern"] == "hubregistrar"
    assert variants[1]["extension"] == "in"


@pytest.mark.asyncio
async def test_lookup_order_id_by_domain_reads_official_nested_response(monkeypatch):
    seen_params: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {"code": 0, "data": {"results": [HUBREGISTRAR_OP_RECORD]}}

    class FakeClient:
        async def get(self, _url, headers=None, params=None):
            seen_params.append(dict(params or {}))
            return FakeResponse()

    @asynccontextmanager
    async def fake_http(**_kwargs):
        yield FakeClient()

    monkeypatch.setattr(op_client, "_auth_headers", AsyncMock(return_value={"Authorization": "Bearer t"}))
    monkeypatch.setattr(op_client, "_base_url", lambda: "https://registrar.test")
    monkeypatch.setattr(op_client, "_op_http_client", fake_http)

    domain_id = await op_client.lookup_order_id_by_domain("hubregistrar.in")
    record = await op_client.lookup_domain_record_by_fqdn("hubregistrar.in")

    assert domain_id == "30145282"
    assert record is not None
    assert record["id"] == 30145282
    assert seen_params[0]["full_name"] == "hubregistrar.in"
    assert seen_params[0]["with_verification_email"] == "true"
