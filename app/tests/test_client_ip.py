from unittest.mock import MagicMock, patch

from fastapi import Request

from app.core.client_ip import get_client_ip


def _make_request(
    *,
    client_host: str | None = "127.0.0.1",
    headers: dict[str, str] | None = None,
) -> Request:
    request = MagicMock(spec=Request)
    request.headers = headers or {}
    if client_host is None:
        request.client = None
    else:
        request.client = MagicMock()
        request.client.host = client_host
    return request


@patch("app.core.client_ip.settings")
def test_ignores_forwarded_when_proxy_headers_not_trusted(mock_settings) -> None:
    mock_settings.TRUST_PROXY_HEADERS = False

    request = _make_request(
        headers={"x-forwarded-for": "203.0.113.1, 10.0.0.1"},
    )

    assert get_client_ip(request) == "127.0.0.1"


@patch("app.core.client_ip.settings")
def test_uses_first_forwarded_hop_when_trusted(mock_settings) -> None:
    mock_settings.TRUST_PROXY_HEADERS = True

    request = _make_request(
        headers={"x-forwarded-for": "203.0.113.1, 10.0.0.1"},
    )

    assert get_client_ip(request) == "203.0.113.1"


@patch("app.core.client_ip.settings")
def test_uses_x_real_ip_when_trusted_and_no_forwarded(mock_settings) -> None:
    mock_settings.TRUST_PROXY_HEADERS = True

    request = _make_request(
        headers={"x-real-ip": "198.51.100.42"},
    )

    assert get_client_ip(request) == "198.51.100.42"


@patch("app.core.client_ip.settings")
def test_returns_unknown_when_no_client(mock_settings) -> None:
    mock_settings.TRUST_PROXY_HEADERS = False

    request = _make_request(client_host=None)

    assert get_client_ip(request) == "unknown"
