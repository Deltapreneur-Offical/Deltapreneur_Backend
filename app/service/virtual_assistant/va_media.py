"""Resolve Virtual Assistant media URLs for browser loading."""

from __future__ import annotations

import logging
import re

from botocore.exceptions import ClientError
from fastapi import HTTPException, UploadFile

from app.core.config import settings
from app.integrations.s3.media_service import generate_media_key
from app.integrations.s3.supabase_storage import public_object_url, resolve_media_url
from app.integrations.s3.upload_service import (
    _raise_for_storage_client_error,
    _require_storage_configured,
)

logger = logging.getLogger(__name__)

_PLACEHOLDER_FRAGMENTS = (
    "example.com",
    "storage.example.com",
    "placeholder",
    "test.com",
    "dummy",
)

VA_PROFILE_PHOTO_FOLDER = "virtual-assistants/profile-photos"


def _clean_stored_url(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    cleaned = url.strip()
    if not cleaned:
        return None
    lower = cleaned.lower()
    if any(fragment in lower for fragment in _PLACEHOLDER_FRAGMENTS):
        return None
    return cleaned


def _canonical_storage_reference(
    stored_url: str | None,
    storage_key: str | None,
) -> str | None:
    """Prefer S3 object key (source of truth); fall back to legacy stored URL."""
    key = (storage_key or "").strip().lstrip("/") or None
    if key:
        return public_object_url(key)

    stored = _clean_stored_url(stored_url)
    if stored and not stored.startswith(("http://", "https://")):
        return public_object_url(stored.lstrip("/"))
    return stored


def resolve_va_storage_media_url(
    stored_url: str | None,
    storage_key: str | None,
) -> str | None:
    """Resolve a VA S3 object (e.g. legacy resume file) to a browser-loadable URL."""
    reference = _canonical_storage_reference(stored_url, storage_key)
    if not reference:
        return None
    return resolve_media_url(reference)


def resolve_va_profile_photo_url(
    profile_photo_url: str | None,
    profile_photo_key: str | None,
) -> str | None:
    """Resolve a VA profile photo for API responses (public / CloudFront URL)."""
    return resolve_va_storage_media_url(profile_photo_url, profile_photo_key)


def upload_va_profile_photo_to_s3(file: UploadFile) -> str:
    """
    Upload a VA profile photo via the same S3 stack as Domain/Venture/Tech.

    Returns the S3 object key only (persist this in ``profile_photo_key``).
    """
    _require_storage_configured()
    key = generate_media_key(VA_PROFILE_PHOTO_FOLDER, file.filename or "file")
    from app.integrations.s3.s3_service import get_storage_client

    client = get_storage_client()
    extra_args = {"ContentType": file.content_type or "application/octet-stream"}
    try:
        file.file.seek(0)
    except Exception:
        pass
    try:
        client.upload_fileobj(
            file.file,
            settings.resolved_storage_bucket(),
            key,
            ExtraArgs=extra_args,
        )
    except ClientError as exc:
        _raise_for_storage_client_error(exc)
    except Exception as exc:
        logger.exception("virtual_assistant.profile_photo.upload.failed key=%s", key)
        raise HTTPException(
            status_code=503,
            detail="Media storage upload failed. Please try again later.",
        ) from exc
    logger.info("virtual_assistant.profile_photo.upload.ok key=%s", key)
    return key


def validate_resume_link(url: str | None) -> str:
    """Validate and normalize an external resume link (Drive / OneDrive / Dropbox / https)."""
    cleaned = (url or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Resume link is required.")
    if len(cleaned) > 500:
        raise HTTPException(status_code=400, detail="Resume link must be 500 characters or fewer.")
    if not cleaned.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail="Resume link must be a valid URL starting with http:// or https://",
        )
    lower = cleaned.lower()
    if any(fragment in lower for fragment in _PLACEHOLDER_FRAGMENTS):
        raise HTTPException(status_code=400, detail="Resume link is invalid.")
    return cleaned


_LINKEDIN_PROFILE_URL_RE = re.compile(
    r"^https?://(?:www\.)?linkedin\.com/in/[\w%-]+/?$",
    re.IGNORECASE,
)
_INVALID_LINKEDIN_PATH_FRAGMENTS = (
    "linkedin.com/oauth",
    "linkedin.com/login",
    "linkedin.com/uas",
    "linkedin.com/checkpoint",
    "linkedin.com/legal",
    "linkedin.com/help",
    "linkedin.com/authwall",
    "linkedin.com/sharing",
)


def validate_linkedin_profile_url(url: str | None) -> str:
    """Validate and normalize a public LinkedIn profile URL (/in/username)."""
    cleaned = (url or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="LinkedIn Profile URL is required.")
    if len(cleaned) > 500:
        raise HTTPException(
            status_code=400,
            detail="LinkedIn Profile URL must be 500 characters or fewer.",
        )

    candidate = cleaned
    if not candidate.lower().startswith(("http://", "https://")):
        candidate = f"https://{candidate.lstrip('/')}"

    lower = candidate.lower()
    if any(fragment in lower for fragment in _PLACEHOLDER_FRAGMENTS):
        raise HTTPException(status_code=400, detail="Please enter a valid LinkedIn profile URL.")
    if any(fragment in lower for fragment in _INVALID_LINKEDIN_PATH_FRAGMENTS):
        raise HTTPException(status_code=400, detail="Please enter a valid LinkedIn profile URL.")
    if not _LINKEDIN_PROFILE_URL_RE.match(candidate):
        raise HTTPException(status_code=400, detail="Please enter a valid LinkedIn profile URL.")

    return candidate
