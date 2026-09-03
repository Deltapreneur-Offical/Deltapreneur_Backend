"""Tests for openprovider.client.search_domains_label batching + resilience.

These exercise the provider request-limit handling that caused the homepage
domain-search slowdowns:

* /domains/check with pricing is batched (up to 100 domains per request) so the
  catalog is searched in a handful of parallel batches, not one request per TLD.
* one unpriceable extension poisons its whole batch (code=199) → must be
  isolated via binary-split and dropped, not fail the search.
* transient throttles (code=10005 "Access denied", 5xx) are retried, not split.
* partial results are returned; only a total failure raises.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.integrations.openprovider import client as op


def _ok(results):
    return {"code": 0, "data": {"results": results}}


def _err(code, desc):
    return {"code": code, "desc": desc}


@pytest.fixture(autouse=True)
def _patch_auth(monkeypatch):
    async def _fake_headers():
        return {"Authorization": "Bearer test", "Content-Type": "application/json"}

    monkeypatch.setattr(op, "_auth_headers", _fake_headers)
    # Keep the curated list small + deterministic for the test.
    monkeypatch.setattr(op, "_PRIORITY_TLDS", ["com", "net", "org", "web", "io"])
    monkeypatch.setattr(op, "_DOMAIN_SEARCH_BATCH_SIZE", 2)
    monkeypatch.setattr(op, "_DOMAIN_SEARCH_CONCURRENCY", 2)
    monkeypatch.setattr(op, "_DOMAIN_SEARCH_RETRIES", 2)


def _install_transport(monkeypatch, handler):
    """Patch httpx.AsyncClient so all requests go through a MockTransport."""
    orig_init = httpx.AsyncClient.__init__

    def _patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs.pop("timeout", None)
        orig_init(self, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)


@pytest.mark.asyncio
async def test_never_sends_more_than_chunk_size(monkeypatch):
    seen_sizes = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        domains = body["domains"]
        seen_sizes.append(len(domains))
        results = [{"domain": f"{d['name']}.{d['extension']}", "name": d["name"],
                    "extension": d["extension"], "status": "free"} for d in domains]
        return httpx.Response(200, json=_ok(results))

    _install_transport(monkeypatch, handler)
    results = await op.search_domains_label("label")
    assert results, "should return results"
    # Chunk size is 2 in the fixture → no request ever exceeds it.
    assert max(seen_sizes) <= 2
    exts = sorted(r["extension"] for r in results)
    assert exts == ["com", "io", "net", "org", "web"]


@pytest.mark.asyncio
async def test_poison_tld_is_isolated_not_fatal(monkeypatch):
    """A .web batch returns code=199; only .web is dropped, the rest survive."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        domains = body["domains"]
        exts = [d["extension"] for d in domains]
        if "web" in exts:
            # Poison: the whole batch fails until .web is isolated alone.
            if len(exts) == 1:
                return httpx.Response(500, json=_err(199, "An unknown error has occurred!"))
            return httpx.Response(500, json=_err(199, "An unknown error has occurred!"))
        results = [{"domain": f"{d['name']}.{d['extension']}", "name": d["name"],
                    "extension": d["extension"], "status": "free"} for d in domains]
        return httpx.Response(200, json=_ok(results))

    _install_transport(monkeypatch, handler)
    results = await op.search_domains_label("label")
    exts = sorted(r["extension"] for r in results)
    # .web dropped; all others returned.
    assert "web" not in exts
    assert exts == ["com", "io", "net", "org"]


@pytest.mark.asyncio
async def test_transient_access_denied_is_retried(monkeypatch):
    """code=10005 (throttle) fails once then succeeds on retry — no data lost."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        domains = body["domains"]
        call_count["n"] += 1
        # Fail the very first call transiently, then serve normally.
        if call_count["n"] == 1:
            return httpx.Response(500, json=_err(10005, "Access denied."))
        results = [{"domain": f"{d['name']}.{d['extension']}", "name": d["name"],
                    "extension": d["extension"], "status": "free"} for d in domains]
        return httpx.Response(200, json=_ok(results))

    _install_transport(monkeypatch, handler)
    results = await op.search_domains_label("label")
    exts = sorted(r["extension"] for r in results)
    # Retry recovers the initially-throttled batch → full set returned.
    assert exts == ["com", "io", "net", "org", "web"]


@pytest.mark.asyncio
async def test_total_failure_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json=_err(10005, "Access denied."))

    _install_transport(monkeypatch, handler)
    with pytest.raises(RuntimeError):
        await op.search_domains_label("label")
