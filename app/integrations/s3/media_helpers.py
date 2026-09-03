"""Shared helpers for Supabase media upload responses."""

from __future__ import annotations

from app.integrations.s3.supabase_storage import resolve_media_url

# Folders used with upload_image() — keep in sync with upload endpoints.
MEDIA_UPLOAD_FOLDERS = (
    "software-listings",
    "venture-images",
    "domain-logos",
    "community-images",
    "community-posts",
    "test-uploads",
)


def client_media_urls(stored_url: str | None) -> dict[str, str | None]:
    """Normalized URL fields returned to React after upload or read APIs."""
    resolved = resolve_media_url(stored_url)
    return {
        "imageUrl": resolved,
        "logoUrl": resolved,
        "logo": resolved,
    }
