from app.core.public_list_cache import (
    public_list_cache_clear,
    public_list_cache_get,
    public_list_cache_put,
)


def test_public_list_cache_round_trip_is_isolated() -> None:
    public_list_cache_clear()
    payload = {"items": [{"id": "v1", "name": "Alpha"}], "total": 1}
    public_list_cache_put("ventures:featured:VENTURE:1:16", payload)

    cached = public_list_cache_get("ventures:featured:VENTURE:1:16")
    assert cached == payload
    cached["items"][0]["name"] = "Mutated"
    assert public_list_cache_get("ventures:featured:VENTURE:1:16")["items"][0]["name"] == "Alpha"


def test_public_list_cache_expires_and_prefix_clear(monkeypatch) -> None:
    public_list_cache_clear()
    public_list_cache_put("software:featured:1:16", ["a"], ttl=30)
    public_list_cache_put("ventures:featured:VENTURE:1:16", ["b"], ttl=30)

    public_list_cache_clear("software:")
    assert public_list_cache_get("software:featured:1:16") is None
    assert public_list_cache_get("ventures:featured:VENTURE:1:16") == ["b"]

    monkeypatch.setattr("app.core.public_list_cache.time.time", lambda: 10**10)
    assert public_list_cache_get("ventures:featured:VENTURE:1:16") is None
    public_list_cache_clear()


def test_public_list_cache_skips_non_positive_ttl() -> None:
    public_list_cache_clear()
    public_list_cache_put("tech-services:all:0", ["x"], ttl=0)
    assert public_list_cache_get("tech-services:all:0") is None
