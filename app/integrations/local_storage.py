"""
Local filesystem image storage.

Images are saved to  <backend_root>/uploads/<folder>/<filename>
and served at         GET /uploads/<folder>/<filename>

This avoids any dependency on Supabase / S3 for profile pictures that
must remain permanently accessible (e.g. LinkedIn CDN URLs expire after
~1 week).
"""

from __future__ import annotations

import logging
import mimetypes
import re
from pathlib import Path

from app.core.config import settings
from app.utils.safe_http import (
    LINKEDIN_DOWNLOAD_HOST_SUFFIXES,
    assert_safe_outbound_url,
    ssrf_safe_get,
)

logger = logging.getLogger(__name__)

# Absolute path to the `uploads` directory inside the backend root.
UPLOADS_ROOT: Path = Path(__file__).resolve().parents[2] / "uploads"

_MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
_ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
}


def _ext_from_content_type(content_type: str) -> str:
    """Return a file extension from a MIME type string."""
    ct = content_type.split(";")[0].strip().lower()
    mapping = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    if ct in mapping:
        return mapping[ct]
    ext = mimetypes.guess_extension(ct)
    if ext and ext.lstrip(".") in {"jpg", "jpeg", "png", "webp", "gif"}:
        return "jpg" if ext.lstrip(".") == "jpeg" else ext.lstrip(".")
    return "jpg"


def _safe_filename(name: str) -> str:
    """Strip anything that isn't alphanumeric, dash, or underscore."""
    return re.sub(r"[^A-Za-z0-9_\-]", "_", name)


def build_local_image_url(relative_path: str) -> str:
    """
    Return the public URL for a locally-stored upload.

    Examples
    --------
    >>> build_local_image_url("community-images/abc123.jpg")
    'https://api.hubregistrar.com/uploads/community-images/abc123.jpg'
    """
    base = settings.BACKEND_BASE_URL.rstrip("/")
    rel = relative_path.lstrip("/")
    return f"{base}/uploads/{rel}"


def is_local_storage_url(url: str) -> bool:
    """Return True when *url* points at our own /uploads/ path."""
    if not url:
        return False
    base = settings.BACKEND_BASE_URL.rstrip("/")
    return url.startswith(f"{base}/uploads/")


def local_upload_file_exists(url: str | None) -> bool:
    """
    True when *url* references ``/uploads/...`` and the file exists on disk.

    Does not touch the database — used only to avoid returning broken image URLs.
    """
    if not url or "/uploads/" not in url:
        return False
    rel = url.split("/uploads/", 1)[1].split("?", 1)[0].lstrip("/")
    if not rel or ".." in rel.replace("\\", "/").split("/"):
        return False
    return (UPLOADS_ROOT / rel).is_file()


def save_upload_bytes(data: bytes, folder: str, filename: str) -> tuple[str, str]:
    """
    Persist raw upload bytes under ``uploads/<folder>/<uuid>.<ext>``.

    Returns ``(public_url, relative_key)`` where *relative_key* is suitable
    for storing in ``profile_photo_key`` / similar columns.
    """
    import uuid

    safe_folder = folder.strip("/").replace("\\", "/")
    original = (filename or "file").strip() or "file"
    ext = Path(original).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf", ".doc", ".docx"}:
        ext = ".bin"
    relative_key = f"{safe_folder}/{uuid.uuid4()}{ext}"
    dest = UPLOADS_ROOT / relative_key
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    logger.info("Saved local upload: %s (%d bytes)", dest, len(data))
    return build_local_image_url(relative_key), relative_key


def download_and_save(
    remote_url: str,
    folder: str,
    stem: str,
    *,
    timeout: int = 15,
) -> str:
    """
    Download *remote_url* and write it to ``uploads/<folder>/<stem>.<ext>``.

    Returns the public URL of the saved file (via ``build_local_image_url``).
    Raises ``RuntimeError`` on download or write failure.

    Parameters
    ----------
    remote_url : str
        The URL to download (e.g. a LinkedIn CDN URL).
    folder : str
        Sub-folder inside *uploads*, e.g. ``"community-images"``.
    stem : str
        Base filename without extension, e.g. ``"linkedin_abc123"``.
    timeout : int
        HTTP timeout in seconds (default 15).
    """
    try:
        safe_url = assert_safe_outbound_url(
            remote_url,
            allowed_host_suffixes=LINKEDIN_DOWNLOAD_HOST_SUFFIXES,
            allow_http=False,
        )
    except ValueError as exc:
        raise RuntimeError(f"Blocked unsafe remote image URL: {exc}") from exc

    logger.debug("Downloading remote image: %s", safe_url)

    try:
        resp = ssrf_safe_get(
            safe_url,
            allowed_host_suffixes=LINKEDIN_DOWNLOAD_HOST_SUFFIXES,
            allow_http=False,
            timeout=float(timeout),
            max_redirects=5,
            max_bytes=_MAX_DOWNLOAD_BYTES,
        )
    except ValueError as exc:
        raise RuntimeError(f"Blocked unsafe remote image URL: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to download remote image: {exc}") from exc

    resp.raise_for_status()

    content_type = (resp.headers.get("content-type") or "image/jpeg").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_IMAGE_CONTENT_TYPES:
        raise RuntimeError(f"Unsupported image content type: {content_type}")

    body = resp.content
    if len(body) > _MAX_DOWNLOAD_BYTES:
        raise RuntimeError("Remote image exceeds size limit")

    ext = _ext_from_content_type(content_type)
    safe_stem = _safe_filename(stem)
    filename = f"{safe_stem}.{ext}"

    dest_dir = UPLOADS_ROOT / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename

    dest_path.write_bytes(body)
    logger.info(
        "Saved local image: %s (%d bytes, %s)",
        dest_path,
        len(body),
        content_type,
    )

    return build_local_image_url(f"{folder}/{filename}")
