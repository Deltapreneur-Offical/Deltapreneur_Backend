from app.utils.safe_http import (
    LINKEDIN_DOWNLOAD_HOST_SUFFIXES,
    assert_safe_outbound_url,
    resolve_public_ips,
    same_registrable_host,
)
import pytest


def test_blocks_private_ip_literal():
    with pytest.raises(ValueError, match="blocked"):
        assert_safe_outbound_url("https://127.0.0.1/x")


def test_blocks_non_allowlisted_host_when_required():
    with pytest.raises(ValueError, match="not allowed"):
        assert_safe_outbound_url(
            "https://evil.example/image.jpg",
            allowed_host_suffixes=LINKEDIN_DOWNLOAD_HOST_SUFFIXES,
        )


def test_allows_linkedin_cdn_host():
    url = assert_safe_outbound_url(
        "https://media.licdn.com/dms/image/abc.jpg",
        allowed_host_suffixes=LINKEDIN_DOWNLOAD_HOST_SUFFIXES,
    )
    assert "licdn.com" in url


def test_same_registrable_host():
    assert same_registrable_host("https://www.example.com/a", "https://example.com/b")
    assert not same_registrable_host("https://example.com/a", "https://evil.com/b")


def test_resolve_public_ips_rejects_private(monkeypatch):
    def fake_getaddrinfo(host, _port):
        return [(None, None, None, None, ("127.0.0.1", 0))]

    monkeypatch.setattr("app.utils.safe_http.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="blocked"):
        resolve_public_ips("evil.local")
