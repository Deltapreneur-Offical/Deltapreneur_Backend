"""Alembic graph tests for the legacy ``techmkt001`` locator revision."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


TECHMKT001_LOCATOR = (
    "2026_09_15_1710-techmkt001_locate_legacy_alembic_stamp.py"
)
TECHMKT002_MARKETPLACE = (
    "2026_09_15_1800-techmkt002_tech_marketplace_payment_safety.py"
)


def _script() -> ScriptDirectory:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    return ScriptDirectory.from_config(cfg)


def test_only_one_techmkt001_revision_file_exists():
    root = Path(__file__).resolve().parents[2]
    matches = []
    for path in sorted((root / "alembic" / "versions").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if 'revision: str = "techmkt001"' in text or "revision = 'techmkt001'" in text:
            matches.append(path.name)

    assert matches == [TECHMKT001_LOCATOR]


def test_techmkt001_revision_is_discoverable():
    script = _script()
    rev = script.get_revision("techmkt001")
    assert rev is not None
    assert rev.revision == "techmkt001"
    assert rev.down_revision == "perf_listing_indexes_001"


def test_single_head_is_techmkt002():
    script = _script()
    heads = script.get_heads()
    assert heads == ["techmkt002"]


def test_techmkt002_chains_from_techmkt001_locator():
    script = _script()
    rev = script.get_revision("techmkt002")
    assert rev is not None
    assert rev.down_revision == "techmkt001"
    assert (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / TECHMKT002_MARKETPLACE
    ).exists()


def test_upgrade_path_includes_marketplace_and_legacy_id():
    script = _script()
    revisions = [sc.revision for sc in script.walk_revisions()]
    assert "techmkt002" in revisions
    assert "techmkt001" in revisions
    assert "7f3e7e682dc7" in revisions
    # walk_revisions yields newest-first; marketplace schema is the head.
    assert revisions[0] == "techmkt002"
    assert revisions.index("techmkt002") < revisions.index("techmkt001")
    assert revisions.index("techmkt001") < revisions.index("7f3e7e682dc7")


def test_base_to_head_path_reaches_techmkt002():
    script = _script()
    upgrade_order = [
        sc.revision
        for sc in script.iterate_revisions("techmkt002", "base")
    ]
    # iterate_revisions(upper, lower) yields upper to lower (newest first).
    assert upgrade_order[0] == "techmkt002"
    assert "techmkt001" in upgrade_order
    assert "7f3e7e682dc7" in upgrade_order
    assert "perf_listing_indexes_001" in upgrade_order
