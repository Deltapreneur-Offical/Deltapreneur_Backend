"""Diagnose and repair Alembic state against Supabase/Postgres.

Usage:
    cd CoBrother_Backend
    python scripts/repair_alembic_database.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_HEAD = "v2w3x4y5z6a7"

SCHEMA_MARKERS = {
    "operations_service_requests": (
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='operations_service_requests')"
    ),
    "operations_service_requests_contacted_by": (
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='operations_service_requests' "
        "AND column_name='contacted_by_user_id')"
    ),
    "seller_payout_profiles": (
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='seller_payout_profiles')"
    ),
    "seller_payout_account_number": (
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='seller_payout_profiles' "
        "AND column_name='account_number')"
    ),
}


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _heads() -> list[str]:
    proc = _run([sys.executable, "-m", "alembic", "heads"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    heads: list[str] = []
    for line in proc.stdout.splitlines():
        token = line.strip().split()[0] if line.strip() else ""
        if token and "(head)" in line:
            heads.append(token)
    return heads


def _current_db_revisions(engine) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num")).fetchall()
    return [row[0] for row in rows]


def _schema_marker_state(engine) -> dict[str, bool]:
    state: dict[str, bool] = {}
    with engine.connect() as conn:
        for name, sql in SCHEMA_MARKERS.items():
            state[name] = bool(conn.execute(text(sql)).scalar())
    return state


def main() -> int:
    sys.path.insert(0, str(BACKEND_ROOT))
    from app.core.database import DATABASE_URL

    graph = _run([sys.executable, "scripts/check_alembic_graph.py"])
    heads = _heads()
    if graph.returncode != 0 or len(heads) != 1:
        print("Alembic graph is unhealthy. Fix migration files before upgrading.")
        print(graph.stdout or graph.stderr)
        if len(heads) > 1:
            print(
                "\nTip: run  python scripts/merge_alembic_heads.py  "
                "then commit the merge file and retry."
            )
        return 1

    expected_head = heads[0]

    url = DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(url)
    before_revs = _current_db_revisions(engine)
    before_markers = _schema_marker_state(engine)

    if len(before_revs) > 1:
        print(
            "Multiple alembic_version rows detected:",
            ", ".join(before_revs),
            "— running upgrade head to merge branches.",
        )

    upgrade = _run([sys.executable, "-m", "alembic", "upgrade", "head"])
    if upgrade.returncode != 0:
        print("alembic upgrade head failed:")
        print(upgrade.stdout)
        print(upgrade.stderr, file=sys.stderr)
        return upgrade.returncode

    after_revs = _current_db_revisions(engine)
    after_markers = _schema_marker_state(engine)
    current = _run([sys.executable, "-m", "alembic", "current"])

    ok = (
        len(after_revs) == 1
        and after_revs[0] == expected_head
        and all(after_markers.values())
    )
    print("Before revisions:", before_revs or ["(none)"])
    print("After revisions:", after_revs or ["(none)"])
    print("Schema markers:", before_markers, "->", after_markers)
    print("Alembic current:\n", current.stdout or current.stderr)
    if ok:
        print("Alembic database repair OK — at head", expected_head)
        return 0

    print("Alembic repair completed with warnings — review state above.")
    return 0 if after_revs else 1


if __name__ == "__main__":
    raise SystemExit(main())
