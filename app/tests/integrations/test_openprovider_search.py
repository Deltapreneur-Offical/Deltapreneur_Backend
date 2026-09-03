from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.integrations.openprovider import client as op_client


@pytest.mark.asyncio
async def test_search_domains_label_uses_full_catalog_in_provider_safe_chunks(monkeypatch):
    tlds = [f"tld{i}" for i in range(205)]
    posted_batches: list[list[dict[str, str]]] = []

    monkeypatch.setattr(op_client, "_auth_headers", AsyncMock(return_value={"Authorization": "Bearer test"}))
    monkeypatch.setattr(op_client, "_base_url", lambda: "https://registrar.test")
    monkeypatch.setattr(op_client, "list_active_tlds", AsyncMock(return_value=tlds))

    class FakeResponse:
        status_code = 200
        text = ""

        def __init__(self, domains: list[dict[str, str]]) -> None:
            self._domains = domains

        def json(self) -> dict:
            return {
                "code": 0,
                "data": {
                    "results": [
                        {
                            "domain": f"{item['name']}.{item['extension']}",
                            "name": item["name"],
                            "extension": item["extension"],
                            "status": "free",
                        }
                        for item in self._domains
                    ]
                },
            }

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc_info) -> None:
            return None

        async def get(self, _url: str, *, headers: dict = None, params: dict = None):
            class FakeGetResponse:
                status_code = 200
                text = ""
                def json(self):
                    return {
                        "data": {
                            "results": [{"extension": t} for t in tlds]
                        }
                    }
            return FakeGetResponse()

        async def post(self, _url: str, *, headers: dict, json: dict):
            assert headers == {"Authorization": "Bearer test"}
            domains = json["domains"]
            posted_batches.append(domains)
            return FakeResponse(domains)

    monkeypatch.setattr(op_client.httpx, "AsyncClient", FakeClient)

    results = await op_client.search_domains_label("indianco")

    batch_size = op_client._DOMAIN_SEARCH_BATCH_SIZE
    expected_batches = (len(tlds) + batch_size - 1) // batch_size

    assert len(results) == 205
    assert len(posted_batches) == expected_batches
    assert max(len(batch) for batch in posted_batches) <= batch_size
    assert {entry["extension"] for entry in results} == set(tlds)


@pytest.mark.asyncio
async def test_remaining_scan_covers_priority_tail_without_skips(monkeypatch):
    """The 'Load more' remaining scan must include curated priority TLDs beyond
    the first page (no skips) and never duplicate first-page or priority TLDs."""
    fake_priority = [f"p{i}" for i in range(70)]  # 70 curated priority TLDs
    monkeypatch.setattr(op_client, "_PRIORITY_TLDS", fake_priority)

    # Catalog overlaps the priority list and adds catalog-only extensions.
    catalog = fake_priority[:50] + [f"c{i}" for i in range(30)]
    monkeypatch.setattr(
        op_client, "_resolve_tlds_to_check", AsyncMock(return_value=catalog)
    )

    captured: list[list[str]] = []

    async def fake_check(label, tlds):
        captured.append(list(tlds))
        return [{"extension": t, "name": label, "status": "free"} for t in tlds]

    monkeypatch.setattr(op_client, "_check_tld_batches", fake_check)

    results, more_available, _token = await op_client.search_domains_label_remaining(
        "mybrand", offset=0, chunk_size=100
    )
    checked = captured[0]

    # Priority tail (indices 60-69) must be present — these were previously skipped.
    assert "p60" in checked and "p69" in checked
    # First-page-covered priority TLDs (0-59) must NOT reappear.
    assert all(f"p{i}" not in checked for i in range(60))
    # Catalog-only extensions are included.
    assert "c0" in checked and "c29" in checked
    # No duplicates anywhere.
    assert len(checked) == len(set(checked))
    # Whole remaining universe fit in one window → no more pages.
    assert more_available is False
    assert {r["extension"] for r in results} == set(checked)


@pytest.mark.asyncio
async def test_remaining_scan_offset_windows_are_contiguous(monkeypatch):
    """Offset-based windows must tile the remaining catalog contiguously with no
    gaps or overlaps, and stop paging once the catalog is exhausted."""
    monkeypatch.setattr(op_client, "_PRIORITY_TLDS", [])  # no priority tail

    catalog = [f"c{i}" for i in range(250)]
    monkeypatch.setattr(
        op_client, "_resolve_tlds_to_check", AsyncMock(return_value=catalog)
    )

    async def fake_check(label, tlds):
        return [{"extension": t, "name": label, "status": "free"} for t in tlds]

    monkeypatch.setattr(op_client, "_check_tld_batches", fake_check)

    seen: list[str] = []
    page = 2
    while True:
        offset = (page - 2) * 100
        results, more_available, _t = await op_client.search_domains_label_remaining(
            "mybrand", offset=offset, chunk_size=100
        )
        seen.extend(r["extension"] for r in results)
        if not more_available:
            break
        page += 1

    # Exactly the full catalog, once each, in order.
    assert seen == catalog
