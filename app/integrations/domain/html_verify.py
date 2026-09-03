"""HTTP checks for domain verification via meta tag / hosted file."""

from __future__ import annotations

import re

from app.utils.safe_http import ssrf_safe_get

_META_NAME = "cobrother-domain-verification"
_TIMEOUT = 8.0


def _candidate_bases(fqdn: str) -> list[str]:
    host = fqdn.strip().lower()
    with_www = host if host.startswith("www.") else f"www.{host}"
    return [
        f"https://{host}",
        f"https://{with_www}",
        f"http://{host}",
        f"http://{with_www}",
    ]


def _extract_meta_values(html: str) -> list[str]:
    # Matches: <meta name="cobrother-domain-verification" content="...">
    pattern = re.compile(
        r"<meta[^>]*name=[\"']cobrother-domain-verification[\"'][^>]*content=[\"']([^\"']+)[\"'][^>]*>",
        re.IGNORECASE,
    )
    return [m.group(1).strip() for m in pattern.finditer(html or "")]


def _get_same_host(url: str):
    """GET *url* without following cross-host redirects; block private IPs / rebinding."""
    try:
        return ssrf_safe_get(
            url,
            allowed_host_suffixes=None,
            allow_http=True,
            timeout=_TIMEOUT,
            max_redirects=3,
            max_bytes=2 * 1024 * 1024,
            same_host_redirects_only=True,
        )
    except Exception:
        return None


def domain_has_meta_verification(fqdn: str, expected_value: str) -> bool:
    expected = (expected_value or "").strip()
    if not expected:
        return False
    for base in _candidate_bases(fqdn):
        try:
            res = _get_same_host(base)
            if res is None or res.status_code >= 400:
                continue
            if expected in _extract_meta_values(res.text):
                return True
        except Exception:
            continue
    return False


def domain_has_verification_file(
    fqdn: str,
    expected_value: str,
    *,
    file_path: str = "/.well-known/cobrother-domain-verification.txt",
) -> bool:
    expected = (expected_value or "").strip()
    if not expected:
        return False
    file_path = file_path if file_path.startswith("/") else f"/{file_path}"
    for base in _candidate_bases(fqdn):
        try:
            res = _get_same_host(f"{base}{file_path}")
            if res is None or res.status_code >= 400:
                continue
            if expected == (res.text or "").strip():
                return True
        except Exception:
            continue
    return False


def build_meta_tag(value: str) -> str:
    safe = (value or "").strip()
    return f'<meta name="{_META_NAME}" content="{safe}" />'
