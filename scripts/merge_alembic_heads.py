"""Create a merge migration when Alembic has multiple heads.

Usage:
    python scripts/merge_alembic_heads.py
    python scripts/merge_alembic_heads.py --dry-run

Run after `git pull` or merging a branch when teammates added parallel
migrations. Then commit the new file under alembic/versions/ and run
`alembic upgrade head`.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(BACKEND_ROOT),
        capture_output=capture,
        text=True,
        check=False,
    )


def _parse_heads(output: str) -> list[str]:
    heads: list[str] = []
    for line in output.splitlines():
        if "(head)" not in line:
            continue
        match = re.match(r"^(\S+)\s+\(head\)", line.strip())
        if match:
            heads.append(match.group(1))
    return heads


def _heads() -> list[str]:
    proc = _run([sys.executable, "-m", "alembic", "heads"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return _parse_heads(proc.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create an Alembic merge revision when multiple heads exist."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would run without creating a merge migration.",
    )
    args = parser.parse_args()

    heads = _heads()
    if len(heads) <= 1:
        head = heads[0] if heads else "(none)"
        print(f"Alembic has a single head ({head}); no merge needed.")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    message = f"merge {len(heads)} parallel heads ({stamp})"
    cmd = [
        sys.executable,
        "-m",
        "alembic",
        "merge",
        "-m",
        message,
        "heads",
    ]

    print("Multiple Alembic heads detected:")
    for head in heads:
        print(f"  - {head}")

    if args.dry_run:
        print("\nDry run — would execute:")
        print("  " + " ".join(cmd))
        return 0

    print(f"\nCreating merge migration: {message!r}")
    merge = _run(cmd, capture=False)
    if merge.returncode != 0:
        return merge.returncode

    check = _run([sys.executable, "scripts/check_alembic_graph.py"], capture=False)
    if check.returncode != 0:
        print(
            "\nMerge file was created but graph check failed — review alembic/versions/."
        )
        return check.returncode

    new_heads = _heads()
    print(f"\nMerge complete. New head: {new_heads[0] if new_heads else '(unknown)'}")
    print("Next steps:")
    print("  1. git add alembic/versions/")
    print("  2. git commit -m \"chore: merge alembic heads\"")
    print("  3. alembic upgrade head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
