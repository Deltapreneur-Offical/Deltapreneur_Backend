"""Validate Alembic migration graph before upgrade.

Usage:
    python scripts/check_alembic_graph.py

Exits 0 when the graph is healthy (single head, unique revision IDs).
Exits 1 when duplicate revisions or multiple heads are detected.
"""
from __future__ import annotations

import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _collect_revisions() -> dict[str, list[str]]:
    by_id: dict[str, list[str]] = defaultdict(list)
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        match = re.search(
            r'^revision(?:\s*:\s*str)?\s*=\s*["\']([^"\']+)["\']',
            text,
            re.MULTILINE,
        )
        if match:
            by_id[match.group(1)].append(path.name)
    return by_id


def main() -> int:
    errors: list[str] = []

    by_id = _collect_revisions()
    duplicates = {rev: files for rev, files in by_id.items() if len(files) > 1}
    if duplicates:
        for rev, files in sorted(duplicates.items()):
            errors.append(
                f"Duplicate revision id '{rev}' in: {', '.join(files)}"
            )

    heads = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        capture_output=True,
        text=True,
        check=False,
    )
    if heads.returncode != 0:
        errors.append(heads.stderr.strip() or heads.stdout.strip())
    else:
        head_lines = [
            line.strip()
            for line in heads.stdout.splitlines()
            if line.strip() and "(head)" in line
        ]
        if len(head_lines) != 1:
            errors.append(
                "Expected exactly one Alembic head; found:\n  "
                + "\n  ".join(head_lines or ["(none)"])
            )

    if errors:
        print("Alembic graph check FAILED:")
        for err in errors:
            print(f"  - {err}")
        print(
            "\nFix tips:"
            "\n  - Never reuse a revision id; generate a new unique id."
            "\n  - Chain new migrations from the current head (alembic heads)."
            "\n  - Run: python scripts/merge_alembic_heads.py"
        )
        return 1

    print("Alembic graph check OK (single head, unique revision ids).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
