"""SSRF-safe helpers for server-side HTTP fetches."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

# Hosts allowed for remote profile/image downloads (LinkedIn CDN / media).
LINKEDIN_DOWNLOAD_HOST_SUFFIXES = (
    "linkedin.com",
    "licdn.com",
)

_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def _host_allowed(hostname: str, allowed_suffixes: tuple[str, ...]) -> bool:
    host = (hostname or "").strip().lower().rstrip(".")
    if not host or host == "localhost":
        return False
    for suffix in allowed_suffixes:
        s = suffix.lower().lstrip(".")
        if host == s or host.endswith("." + s):
            return True
    return False


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        return False
    for net in _BLOCKED_NETWORKS:
        if ip in net:
            return False
    return True


def resolve_public_ips(host: str) -> list[str]:
    """Resolve *host* and return only public A/AAAA addresses."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError("URL host could not be resolved") from exc

    public_ips: list[str] = []
    seen: set[str] = set()
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if not _ip_is_public(ip):
            raise ValueError("URL resolves to a blocked address")
        if ip_str not in seen:
            seen.add(ip_str)
            public_ips.append(ip_str)

    if not public_ips:
        raise ValueError("URL host could not be resolved")
    return public_ips


def assert_safe_outbound_url(
    url: str,
    *,
    allowed_host_suffixes: tuple[str, ...] | None = None,
    allow_http: bool = False,
) -> str:
    """
    Validate *url* before server-side fetch.

    - https only (http optional for domain verification of customer sites)
    - optional host allowlist
    - resolved DNS must not point at private/link-local/metadata ranges
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("URL is required")

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme == "https":
        pass
    elif scheme == "http" and allow_http:
        pass
    else:
        raise ValueError("Only https URLs are allowed" if not allow_http else "Only http/https URLs are allowed")

    host = parsed.hostname
    if not host:
        raise ValueError("URL host is required")

    if allowed_host_suffixes is not None and not _host_allowed(host, allowed_host_suffixes):
        raise ValueError("URL host is not allowed")

    # Block literal private IPs in the URL.
    try:
        literal_ip = ipaddress.ip_address(host)
        if not _ip_is_public(literal_ip):
            raise ValueError("URL resolves to a blocked address")
        return raw
    except ValueError as exc:
        if "blocked" in str(exc):
            raise
        # host is a name — resolve A/AAAA
        pass

    resolve_public_ips(host)
    return raw


def same_registrable_host(url_a: str, url_b: str) -> bool:
    """Best-effort same-host check (hostname equality, ignore www.)."""
    try:
        a = (urlparse(url_a).hostname or "").lower().removeprefix("www.")
        b = (urlparse(url_b).hostname or "").lower().removeprefix("www.")
        return bool(a and b and a == b)
    except Exception:
        return False


@dataclass(frozen=True)
class SafeHttpResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes
    url: str

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    @property
    def is_redirect(self) -> bool:
        return self.status_code in {301, 302, 303, 307, 308}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code} for {self.url}")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """TLS connect to a pre-validated IP while keeping SNI/cert checks on hostname."""

    def __init__(self, hostname: str, ip: str, port: int, timeout: float):
        context = ssl.create_default_context()
        super().__init__(hostname, port=port, timeout=timeout, context=context)
        self._pinned_ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        server_hostname = self.host if isinstance(self.host, str) else None
        self.sock = self._context.wrap_socket(sock, server_hostname=server_hostname)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, hostname: str, ip: str, port: int, timeout: float):
        super().__init__(hostname, port=port, timeout=timeout)
        self._pinned_ip = ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)


def _pick_pinned_ip(hostname: str) -> str:
    """Resolve twice and require the chosen IP to remain public (anti-rebinding)."""
    first = resolve_public_ips(hostname)
    second = set(resolve_public_ips(hostname))
    for ip in first:
        if ip in second:
            # Final TOCTOU narrow: confirm this specific IP is still public.
            if not _ip_is_public(ipaddress.ip_address(ip)):
                continue
            return ip
    raise ValueError("URL host resolution changed to an unsafe address")


def ssrf_safe_get(
    url: str,
    *,
    allowed_host_suffixes: tuple[str, ...] | None = None,
    allow_http: bool = False,
    timeout: float = 15.0,
    max_redirects: int = 5,
    max_bytes: int | None = None,
    same_host_redirects_only: bool = False,
) -> SafeHttpResponse:
    """
    GET *url* by dialing a pre-validated public IP (Host/SNI keep the hostname).

    This closes the classic DNS-rebinding TOCTOU between allowlist checks and connect.
    Redirects are re-validated on every hop.
    """
    current = assert_safe_outbound_url(
        url,
        allowed_host_suffixes=allowed_host_suffixes,
        allow_http=allow_http,
    )

    for _ in range(max(1, max_redirects + 1)):
        parsed = urlparse(current)
        hostname = parsed.hostname
        if not hostname:
            raise ValueError("URL host is required")

        scheme = (parsed.scheme or "").lower()
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        # Literal IP in URL — already validated by assert_safe_outbound_url.
        try:
            ip = str(ipaddress.ip_address(hostname))
        except ValueError:
            ip = _pick_pinned_ip(hostname)

        if scheme == "https":
            conn: http.client.HTTPConnection = _PinnedHTTPSConnection(
                hostname, ip, port, timeout
            )
        else:
            conn = _PinnedHTTPConnection(hostname, ip, port, timeout)

        try:
            conn.request(
                "GET",
                path,
                headers={"Host": hostname, "User-Agent": "HubRegistrar-SafeFetch/1.0"},
            )
            resp = conn.getresponse()
            # Cap body size while reading.
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise RuntimeError("Remote response exceeds size limit")
                chunks.append(chunk)
            body = b"".join(chunks)
            headers = {k.lower(): v for k, v in resp.getheaders()}
            status = resp.status
        finally:
            conn.close()

        result = SafeHttpResponse(
            status_code=status,
            headers=headers,
            content=body,
            url=current,
        )
        if not result.is_redirect:
            return result

        location = headers.get("location")
        if not location:
            raise RuntimeError("Redirect without Location header")
        nxt = urljoin(current, location)
        if same_host_redirects_only and not same_registrable_host(current, nxt):
            raise ValueError("Cross-host redirect blocked")
        assert_safe_outbound_url(
            nxt,
            allowed_host_suffixes=allowed_host_suffixes,
            allow_http=allow_http,
        )
        current = nxt

    raise RuntimeError("Too many redirects")
