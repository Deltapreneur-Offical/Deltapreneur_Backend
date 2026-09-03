#!/usr/bin/env python3
"""Copy objects from Supabase Storage to AWS S3 and optionally rewrite DB URLs.

Environment — source (Supabase):
    SUPABASE_URL, SUPABASE_STORAGE_BUCKET, SUPABASE_S3_ACCESS_KEY_ID, SUPABASE_S3_SECRET_ACCESS_KEY
    SUPABASE_S3_REGION (optional)

Environment — target (AWS S3):
    AWS_BUCKET_NAME, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION

Optional — rewrite stored URLs in Postgres after copy:
    TARGET_DATABASE_URL or DATABASE_URL pointing at RDS

Usage:
    python scripts/aws_migrate_storage.py --dry-run
    python scripts/aws_migrate_storage.py --prefix software-listings/
    python scripts/aws_migrate_storage.py --rewrite-db-urls
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.integrations.s3.supabase_storage import (  # noqa: E402
    is_aws_s3_storage_url,
    is_supabase_storage_url,
)

# table, column, optional WHERE fragment
_MEDIA_URL_COLUMNS: list[tuple[str, str, str]] = [
    ("brand_details", "venture_image_url", "venture_image_url IS NOT NULL"),
    ("software_listings", "image_url", "image_url IS NOT NULL"),
    ("domain_listings", "logo", "logo IS NOT NULL"),
    ("community", "image_url", "image_url IS NOT NULL"),
    ("community_posts", "image_url", "image_url IS NOT NULL"),
    ("venture_documents", "file_url", "file_url IS NOT NULL"),
    ("venture_verification_documents", "file_url", "file_url IS NOT NULL"),
    ("venture_company_profiles", "file_url", "file_url IS NOT NULL"),
    ("seller_payout_profiles", "kyc_document_storage_key", "kyc_document_storage_key IS NOT NULL"),
    (
        "domain_marketplace_transactions",
        "proof_storage_key",
        "proof_storage_key IS NOT NULL",
    ),
    ("domain_dispute_evidence", "storage_key", "storage_key IS NOT NULL"),
]


def _supabase_client():
    url = (os.getenv("SUPABASE_URL") or "").strip()
    bucket = (os.getenv("SUPABASE_STORAGE_BUCKET") or "").strip()
    key_id = (os.getenv("SUPABASE_S3_ACCESS_KEY_ID") or "").strip()
    secret = (os.getenv("SUPABASE_S3_SECRET_ACCESS_KEY") or "").strip()
    region = (os.getenv("SUPABASE_S3_REGION") or "ap-southeast-2").strip()
    if not all([url, bucket, key_id, secret]):
        raise SystemExit(
            "Set SUPABASE_URL, SUPABASE_STORAGE_BUCKET, SUPABASE_S3_ACCESS_KEY_ID, "
            "SUPABASE_S3_SECRET_ACCESS_KEY for the source bucket."
        )
    ref_match = urlparse(url).hostname or ""
    endpoint = (os.getenv("SUPABASE_S3_ENDPOINT") or "").strip()
    if not endpoint:
        project = ref_match.split(".")[0] if ref_match else ""
        endpoint = f"https://{project}.storage.supabase.co/storage/v1/s3"
    return (
        boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=key_id,
            aws_secret_access_key=secret,
            region_name=region,
            config=Config(signature_version="s3v4"),
        ),
        bucket,
    )


def _aws_client():
    bucket = (os.getenv("AWS_BUCKET_NAME") or "").strip()
    key_id = (os.getenv("AWS_ACCESS_KEY_ID") or "").strip()
    secret = (os.getenv("AWS_SECRET_ACCESS_KEY") or "").strip()
    region = (os.getenv("AWS_REGION") or "ap-south-1").strip()
    if not all([bucket, key_id, secret]):
        raise SystemExit(
            "Set AWS_BUCKET_NAME, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION."
        )
    kwargs: dict = {
        "service_name": "s3",
        "aws_access_key_id": key_id,
        "aws_secret_access_key": secret,
        "region_name": region,
        "config": Config(signature_version="s3v4"),
    }
    endpoint = (os.getenv("AWS_S3_ENDPOINT_URL") or "").strip()
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client(**kwargs), bucket


def _list_keys(client, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        for item in resp.get("Contents") or []:
            key = item.get("Key")
            if key and not key.endswith("/"):
                keys.append(key)
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    return keys


def _copy_objects(
    src_client,
    src_bucket: str,
    dst_client,
    dst_bucket: str,
    *,
    prefix: str,
    dry_run: bool,
) -> tuple[int, int]:
    keys = _list_keys(src_client, src_bucket, prefix)
    copied = 0
    skipped = 0
    for key in keys:
        if dry_run:
            print(f"  would copy: {key}")
            copied += 1
            continue
        try:
            dst_client.head_object(Bucket=dst_bucket, Key=key)
            skipped += 1
            continue
        except dst_client.exceptions.ClientError:
            pass
        body = src_client.get_object(Bucket=src_bucket, Key=key)
        extra = {}
        if body.get("ContentType"):
            extra["ContentType"] = body["ContentType"]
        dst_client.upload_fileobj(body["Body"], dst_bucket, key, ExtraArgs=extra or None)
        copied += 1
        if copied % 50 == 0:
            print(f"  copied {copied} objects...")
    return copied, skipped


def _aws_public_url(key: str, *, bucket: str, region: str, public_base: str) -> str:
    key = key.lstrip("/")
    base = public_base.strip().rstrip("/")
    if base:
        return f"{base}/{key}"
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


def _rewrite_db_urls(
    db_url: str,
    *,
    supabase_bucket: str,
    aws_bucket: str,
    aws_region: str,
    aws_public_base: str,
    dry_run: bool,
) -> int:
    engine = create_engine(db_url.replace("+asyncpg", ""))
    total = 0
    with engine.begin() as conn:
        for table, column, where in _MEDIA_URL_COLUMNS:
            rows = conn.execute(
                text(f"SELECT id, {column} FROM {table} WHERE {where}")
            ).fetchall()
            for row_id, stored in rows:
                if not stored or not isinstance(stored, str):
                    continue
                if is_aws_s3_storage_url(stored):
                    continue
                if not is_supabase_storage_url(stored) and not stored.startswith(
                    (
                        "software-listings/",
                        "venture-images/",
                        "domain-logos/",
                    )
                ):
                    continue
                key = None
                if is_supabase_storage_url(stored):
                    marker = f"/object/public/{supabase_bucket}/"
                    if marker in stored:
                        key = stored.split(marker, 1)[1].split("?", 1)[0]
                else:
                    for prefix in (
                        "software-listings/",
                        "venture-images/",
                        "domain-logos/",
                        "community-images/",
                        "payout-kyc/",
                        "domain-transfer-proofs/",
                        "domain-disputes/",
                    ):
                        if stored.startswith(prefix):
                            key = stored.split("?", 1)[0]
                            break
                if not key:
                    continue
                new_url = _aws_public_url(
                    key,
                    bucket=aws_bucket,
                    region=aws_region,
                    public_base=aws_public_base,
                )
                if new_url == stored:
                    continue
                total += 1
                if dry_run:
                    print(f"  would update {table}.{column} id={row_id}")
                else:
                    conn.execute(
                        text(f"UPDATE {table} SET {column} = :url WHERE id = :id"),
                        {"url": new_url, "id": row_id},
                    )
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate Supabase Storage objects to AWS S3")
    parser.add_argument("--prefix", default="", help="Only copy keys under this prefix")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--rewrite-db-urls",
        action="store_true",
        help="Rewrite Supabase URLs in RDS after object copy",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("TARGET_DATABASE_URL") or os.getenv("DATABASE_URL", ""),
    )
    args = parser.parse_args()

    src_client, src_bucket = _supabase_client()
    dst_client, dst_bucket = _aws_client()

    print(f"Source: Supabase bucket {src_bucket}")
    print(f"Target: AWS bucket {dst_bucket} ({os.getenv('AWS_REGION', 'ap-south-1')})")
    print(f"Prefix: {args.prefix or '(all)'}")

    copied, skipped = _copy_objects(
        src_client,
        src_bucket,
        dst_client,
        dst_bucket,
        prefix=args.prefix,
        dry_run=args.dry_run,
    )
    print(f"Objects copied: {copied}, already present: {skipped}")

    if args.rewrite_db_urls:
        db_url = args.database_url.strip()
        if not db_url:
            print("ERROR: set TARGET_DATABASE_URL or --database-url for URL rewrite", file=sys.stderr)
            return 1
        count = _rewrite_db_urls(
            db_url,
            supabase_bucket=src_bucket,
            aws_bucket=dst_bucket,
            aws_region=os.getenv("AWS_REGION", "ap-south-1"),
            aws_public_base=os.getenv("AWS_S3_PUBLIC_BASE_URL", ""),
            dry_run=args.dry_run,
        )
        print(f"DB URL rows {'to update' if args.dry_run else 'updated'}: {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
