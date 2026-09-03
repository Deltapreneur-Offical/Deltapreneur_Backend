"""Object storage helpers — Supabase Storage (S3-compatible) and native AWS S3."""

from __future__ import annotations

import logging
import re
import time
from threading import Lock
from urllib.parse import unquote, urlparse

from app.core.config import settings

logger = logging.getLogger(__name__)

# Browser-loadable signed URLs (private buckets need this; public buckets work too).
DEFAULT_SIGNED_URL_EXPIRE_SECONDS = 60 * 60 * 24 * 7

_presign_cache: dict[tuple[str, int], tuple[float, str]] = {}
_presign_cache_lock = Lock()

_LEGACY_KEY_PREFIXES = (
    "software-listings/",
    "venture-images/",
    "domain-logos/",
    "community-images/",
    "community-posts/",
    "test-uploads/",
    "payout-kyc/",
    "domain-transfer-proofs/",
    "domain-disputes/",
    "virtual-assistants/",
)


def supabase_project_ref() -> str:
    """Extract project ref from SUPABASE_URL (https://<ref>.supabase.co)."""
    url = (settings.SUPABASE_URL or "").strip().rstrip("/")
    if not url:
        raise ValueError("SUPABASE_URL is not set")
    match = re.match(r"https?://([a-z0-9-]+)\.supabase\.co", url, re.I)
    if not match:
        raise ValueError(
            "SUPABASE_URL must be your project URL, e.g. https://abcdefgh.supabase.co"
        )
    return match.group(1)


def supabase_s3_endpoint() -> str:
    """
    S3-compatible endpoint from Supabase dashboard → Storage → S3 Connection.
    Example: https://<ref>.storage.supabase.co/storage/v1/s3
    """
    custom = (settings.SUPABASE_S3_ENDPOINT or "").strip().rstrip("/")
    if custom:
        return custom if custom.endswith("/storage/v1/s3") else f"{custom}/storage/v1/s3"
    ref = supabase_project_ref()
    return f"https://{ref}.storage.supabase.co/storage/v1/s3"


def public_object_url(key: str) -> str:
    """Canonical public URL for a newly uploaded object key."""
    key = key.lstrip("/")
    if settings.storage_uses_aws():
        custom_base = (settings.AWS_S3_PUBLIC_BASE_URL or "").strip().rstrip("/")
        if custom_base:
            return f"{custom_base}/{key}"
        bucket = settings.resolved_storage_bucket()
        region = settings.resolved_storage_region()
        return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
    base = (settings.SUPABASE_URL or "").strip().rstrip("/")
    bucket = settings.resolved_storage_bucket()
    return f"{base}/storage/v1/object/public/{bucket}/{key}"


def supabase_public_object_url(key: str) -> str:
    """Backward-compatible alias for ``public_object_url``."""
    return public_object_url(key)


def is_supabase_storage_url(url: str) -> bool:
    if not url:
        return False
    return ".supabase.co" in url and "/storage/v1/object/" in url


def is_aws_s3_storage_url(url: str) -> bool:
    if not url:
        return False
    lower = url.lower()
    if ".amazonaws.com" not in lower:
        return False
    return ".s3." in lower or lower.startswith("https://s3.") or "/s3/" in lower


def is_managed_storage_url(url: str) -> bool:
    """True when URL points at Supabase Storage, AWS S3, or local /uploads/."""
    if is_supabase_storage_url(url):
        return True
    if is_aws_s3_storage_url(url):
        return True
    custom_base = (settings.AWS_S3_PUBLIC_BASE_URL or "").strip().rstrip("/")
    if custom_base and url.startswith(custom_base + "/"):
        return True
    # Locally-stored uploads served by this backend instance
    backend_base = (settings.BACKEND_BASE_URL or "").strip().rstrip("/")
    if backend_base and url.startswith(f"{backend_base}/uploads/"):
        return True
    return False


def extract_storage_key(stored_url: str) -> str | None:
    """Resolve S3 object key from a stored public URL or legacy bare path."""
    if not stored_url:
        return None
    bucket = settings.resolved_storage_bucket()
    if not bucket:
        return None

    if is_supabase_storage_url(stored_url):
        public_marker = f"/object/public/{bucket}/"
        if public_marker in stored_url:
            return stored_url.split(public_marker, 1)[1].split("?", 1)[0]
        sign_marker = f"/object/sign/{bucket}/"
        if sign_marker in stored_url:
            return stored_url.split(sign_marker, 1)[1].split("?", 1)[0]

    custom_base = (settings.AWS_S3_PUBLIC_BASE_URL or "").strip().rstrip("/")
    if custom_base and stored_url.startswith(custom_base + "/"):
        return unquote(stored_url[len(custom_base) + 1 :].split("?", 1)[0])

    if is_aws_s3_storage_url(stored_url):
        parsed = urlparse(stored_url)
        path = unquote(parsed.path or "").lstrip("/")
        host = (parsed.hostname or "").lower()
        # Virtual-hosted: bucket.s3.region.amazonaws.com/key
        if host.startswith(f"{bucket.lower()}.s3."):
            return path.split("?", 1)[0] or None
        # Path-style: s3.region.amazonaws.com/bucket/key
        if path.startswith(f"{bucket}/"):
            return path[len(bucket) + 1 :].split("?", 1)[0]
        if f"/{bucket}/" in path:
            return path.split(f"/{bucket}/", 1)[1].split("?", 1)[0]

    parsed = urlparse(stored_url)
    path = parsed.path or stored_url
    public_marker = f"/object/public/{bucket}/"
    if public_marker in path:
        return path.split(public_marker, 1)[1]
    sign_marker = f"/object/sign/{bucket}/"
    if sign_marker in path:
        return path.split(sign_marker, 1)[1]

    for folder in _LEGACY_KEY_PREFIXES:
        if stored_url.startswith(folder):
            return stored_url.split("?", 1)[0]
        if f"/{folder}" in stored_url:
            return stored_url[stored_url.index(folder) :].split("?", 1)[0]
    return None


def resolve_media_url(
    stored_url: str | None,
    *,
    expires_in: int = DEFAULT_SIGNED_URL_EXPIRE_SECONDS,
) -> str | None:
    """
    Return a URL the browser can load for a stored object.

    Public bucket URLs often 403 when the bucket is private; presigned GET URLs
    work with the configured S3 credentials.
    """
    if not stored_url:
        return None
    url = stored_url.strip()
    if not url:
        return None
    
    # Rewrite local /uploads/ base URLs to use the current BACKEND_BASE_URL dynamically.
    # This prevents local loopback IPs (127.0.0.1:8000) stored in DB from causing CORS issues in production.
    if "/uploads/" in url:
        parts = url.split("/uploads/", 1)
        if len(parts) == 2:
            backend_base = (settings.BACKEND_BASE_URL or "").strip().rstrip("/")
            url = f"{backend_base}/uploads/{parts[1]}"

    # Local /uploads/ URLs are served directly — no signing needed.
    backend_base = (settings.BACKEND_BASE_URL or "").strip().rstrip("/")
    if backend_base and url.startswith(f"{backend_base}/uploads/"):
        return url
    if not is_managed_storage_url(url):
        return url
    if "X-Amz-Signature=" in url or "X-Amz-Algorithm=" in url:
        return url
    if not settings.storage_configured():
        return url
    key = extract_storage_key(url)
    if not key:
        return url
    # === ADD THESE LINES HERE ===
    public_prefixes = (
        "domain-logos/",
        "venture-images/",
        "software-listings/",
        "community-images/",
        "community-posts/",
    )
    if settings.storage_configured() and key.startswith(public_prefixes):
        return public_object_url(key)
    # ============================
    cache_key = (key, expires_in)
    now = time.monotonic()
    with _presign_cache_lock:
        cached = _presign_cache.get(cache_key)
        if cached and now < cached[0]:
            return cached[1]

    try:
        from app.integrations.s3.s3_service import get_storage_client

        client = get_storage_client()
        signed_url = client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": settings.resolved_storage_bucket(),
                "Key": key,
            },
            ExpiresIn=expires_in,
        )
        with _presign_cache_lock:
            _presign_cache[cache_key] = (now + expires_in * 0.9, signed_url)
        return signed_url
    except Exception:
        logger.warning(
            "Failed to presign object key=%s; using stored URL",
            key,
            exc_info=True,
        )
        return url


def key_from_storage_url(image_url: str, folder: str) -> str | None:
    """Resolve object key from a public URL or legacy path fragment."""
    key = extract_storage_key(image_url)
    if key:
        return key
    if not image_url:
        return None
    if f"{folder}/" in image_url:
        return image_url[image_url.index(f"{folder}/") :].split("?", 1)[0]
    return None
