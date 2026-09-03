#!/usr/bin/env python3
"""Export Supabase Postgres and restore into AWS RDS, then run Alembic upgrade.

Usage (from CoBrother_Backend with pg_dump/pg_restore on PATH):

    # Set source (Supabase) and target (RDS) URLs — never commit passwords.
    set SOURCE_DATABASE_URL=postgresql://...@pooler.supabase.com:5432/postgres
    set TARGET_DATABASE_URL=postgresql://cobrotherpython:<PASSWORD>@database-1.cno8smi8qae3.ap-south-1.rds.amazonaws.com:5432/postgres

    python scripts/aws_migrate_database.py --dry-run
    python scripts/aws_migrate_database.py
    python scripts/aws_migrate_database.py --skip-dump --dump-file cobrother.dump

Requires: PostgreSQL client tools (pg_dump, pg_restore), network access to both hosts.
Production Supabase is NOT modified by this script (read-only dump).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], *, env: dict | None = None) -> None:
    print("+", " ".join(cmd))
    result = subprocess.run(
        cmd,
        cwd=str(BACKEND_ROOT),
        env=env,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _normalize_pg_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql://", 1)
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate Postgres from Supabase to AWS RDS")
    parser.add_argument(
        "--source-url",
        default=os.getenv("SOURCE_DATABASE_URL", ""),
        help="Supabase connection URL (session pooler :5432 recommended for pg_dump)",
    )
    parser.add_argument(
        "--target-url",
        default=os.getenv("TARGET_DATABASE_URL", ""),
        help="AWS RDS connection URL",
    )
    parser.add_argument(
        "--dump-file",
        default=str(BACKEND_ROOT / "cobrother_supabase.dump"),
        help="Path for custom-format pg_dump output",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print steps only")
    parser.add_argument(
        "--skip-dump",
        action="store_true",
        help="Reuse existing dump file (skip pg_dump)",
    )
    parser.add_argument(
        "--skip-restore",
        action="store_true",
        help="Only dump from Supabase",
    )
    parser.add_argument(
        "--skip-alembic",
        action="store_true",
        help="Skip alembic upgrade head on target",
    )
    args = parser.parse_args()

    source = _normalize_pg_url(args.source_url.strip())
    target = _normalize_pg_url(args.target_url.strip())
    dump_path = Path(args.dump_file)

    if not source and not args.skip_dump:
        print("ERROR: set SOURCE_DATABASE_URL or pass --source-url", file=sys.stderr)
        return 1
    if not target and not args.skip_restore:
        print("ERROR: set TARGET_DATABASE_URL or pass --target-url", file=sys.stderr)
        return 1

    if args.dry_run:
        print("Dry run — planned steps:")
        if not args.skip_dump:
            print(f"  1. pg_dump {source[:40]}... -> {dump_path}")
        if not args.skip_restore:
            print(f"  2. pg_restore -> {target[:40]}...")
        if not args.skip_alembic:
            print("  3. DATABASE_URL=target alembic upgrade head")
        return 0

    if not args.skip_dump:
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "pg_dump",
                source,
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "-f",
                str(dump_path),
            ]
        )
        print(f"Dump written: {dump_path} ({dump_path.stat().st_size} bytes)")

    if not args.skip_restore:
        _run(
            [
                "pg_restore",
                "--dbname",
                target,
                "--no-owner",
                "--no-acl",
                "--clean",
                "--if-exists",
                str(dump_path),
            ]
        )
        print("Restore completed.")

    if not args.skip_alembic and target:
        env = os.environ.copy()
        env["DATABASE_URL"] = target
        _run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env)
        print("Alembic upgrade head completed on target.")

    print("\nNext: python scripts/verify_aws_migration.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
