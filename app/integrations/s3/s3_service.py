"""S3 client for Supabase Storage (S3-compatible) or native AWS S3."""

from __future__ import annotations

import boto3
from botocore.config import Config

from app.core.config import settings
from app.integrations.s3.supabase_storage import supabase_s3_endpoint

_client = None


def reset_storage_client() -> None:
    """Clear cached client (tests or env reload)."""
    global _client
    _client = None


def get_storage_client():
    """Lazy boto3 S3 client for the active storage backend."""
    global _client
    if _client is not None:
        return _client
    if not settings.storage_configured():
        raise RuntimeError(
            "Object storage is not configured. For Supabase set SUPABASE_URL, "
            "SUPABASE_STORAGE_BUCKET, and S3 connection keys. For AWS set "
            "STORAGE_BACKEND=aws, AWS_BUCKET_NAME, AWS_ACCESS_KEY_ID, "
            "AWS_SECRET_ACCESS_KEY, and AWS_REGION."
        )

    client_kwargs: dict = {
        "service_name": "s3",
        "aws_access_key_id": settings.resolved_storage_access_key_id(),
        "aws_secret_access_key": settings.resolved_storage_secret_access_key(),
        "region_name": settings.resolved_storage_region(),
        "config": Config(signature_version="s3v4"),
    }
    if settings.storage_uses_supabase():
        client_kwargs["endpoint_url"] = supabase_s3_endpoint()
    else:
        endpoint = (settings.AWS_S3_ENDPOINT_URL or "").strip()
        if endpoint:
            client_kwargs["endpoint_url"] = endpoint

    _client = boto3.client(**client_kwargs)
    return _client
