#!/usr/bin/env python3
"""Smoke-test AWS RDS + S3 configuration before cutover.

Usage (EC2 or laptop with .env pointing at AWS):

    cd CoBrother_Backend
    python scripts/verify_aws_migration.py

Checks:
  - DATABASE_URL connectivity + alembic_version
  - Storage backend resolution
  - S3 upload / presigned GET / delete (when configured)
"""
from __future__ import annotations

import io
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text

from app.core.config import settings
from app.integrations.s3.s3_service import get_storage_client, reset_storage_client
from app.integrations.s3.supabase_storage import extract_storage_key, public_object_url, resolve_media_url


def _check_database() -> bool:
    print("\n=== Database ===")
    print(f"  host label: {settings.database_host_label()}")
    url = settings.DATABASE_URL.replace("+asyncpg", "")
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        print(f"  SELECT 1: OK")
        print(f"  alembic_version: {version}")
        return True
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


def _check_storage() -> bool:
    print("\n=== Storage ===")
    print(f"  backend: {settings.storage_backend()}")
    print(f"  configured: {settings.storage_configured()}")
    print(f"  bucket: {settings.resolved_storage_bucket() or '(unset)'}")
    print(f"  region: {settings.resolved_storage_region()}")
    if not settings.storage_configured():
        print("  SKIP upload test — storage not configured")
        return False

    reset_storage_client()
    key = f"test-uploads/aws-migration-{secrets.token_hex(4)}.txt"
    payload = b"coBrother aws migration smoke test\n"
    ok = True
    try:
        client = get_storage_client()
        client.upload_fileobj(
            io.BytesIO(payload),
            settings.resolved_storage_bucket(),
            key,
            ExtraArgs={"ContentType": "text/plain"},
        )
        stored_url = public_object_url(key)
        print(f"  upload: OK -> {stored_url[:80]}...")
        parsed_key = extract_storage_key(stored_url)
        if parsed_key != key:
            print(f"  WARN: extract_storage_key mismatch ({parsed_key!r})")
        signed = resolve_media_url(stored_url, expires_in=300)
        if not signed:
            print("  FAIL: resolve_media_url returned empty")
            ok = False
        else:
            print("  presign: OK")
        client.delete_object(Bucket=settings.resolved_storage_bucket(), Key=key)
        print("  delete: OK")
    except Exception as exc:
        print(f"  FAIL: {exc}")
        ok = False
    finally:
        reset_storage_client()
    return ok


def main() -> int:
    print("CoBrother AWS migration verification")
    print(f"  ENVIRONMENT={settings.ENVIRONMENT}")
    db_ok = _check_database()
    storage_ok = _check_storage()
    print("\n=== Summary ===")
    print(f"  database: {'PASS' if db_ok else 'FAIL'}")
    print(f"  storage:  {'PASS' if storage_ok else 'FAIL/SKIP'}")
    if not db_ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
