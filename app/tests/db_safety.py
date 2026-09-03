"""Single source of truth for keeping test-database operations away from real data.

The DB-backed test suites run destructive operations (DROP SCHEMA public
CASCADE, TRUNCATE) against TEST_DATABASE_URL. The shared RDS instance was
wiped twice in July 2026 because that URL pointed at it. Every conftest that
touches a database must validate the URL through this module first.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

_LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1"}
# run_rds_tunnel.ps1 exposes the shared RDS instance (real data!) on this
# local port, so "localhost" alone is not proof the database is local.
_RDS_TUNNEL_PORTS = {5433}


def check_test_db_url_is_local(url: str) -> str | None:
    """Return an error message if `url` does not target a disposable local DB.

    Returns None when the URL is safe to use for destructive test operations.
    Set ALLOW_REMOTE_TEST_DB=1 to deliberately allow a remote host (e.g. a
    dedicated, disposable CI database) — the tunnel-port check still applies.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host not in _LOCAL_DB_HOSTS and os.getenv("ALLOW_REMOTE_TEST_DB") != "1":
        return (
            f"TEST_DATABASE_URL host '{host}' is not local. DB-backed test suites "
            "DROP the entire schema — point TEST_DATABASE_URL at a disposable local "
            "database, or set ALLOW_REMOTE_TEST_DB=1 if the remote DB is truly "
            "disposable."
        )
    if parts.port in _RDS_TUNNEL_PORTS:
        return (
            f"TEST_DATABASE_URL uses port {parts.port}, which is the SSH tunnel to "
            "the shared RDS instance — the same database as production. DB-backed "
            "test suites DROP the entire schema. Point TEST_DATABASE_URL at a "
            "disposable local database on a different port."
        )
    return None
