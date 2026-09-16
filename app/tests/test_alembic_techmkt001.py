"""Alembic graph tests for legacy Render technology-market stamps."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


TECHMKT001_LOCATOR = (
    "2026_09_15_1710-techmkt001_locate_legacy_alembic_stamp.py"
)
TECHMKT002_LOCATOR = (
    "2026_09_16_1100-techmkt002_locate_render_alembic_stamp.py"
)


def _script() -> ScriptDirectory:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    return ScriptDirectory.from_config(cfg)


def _revision_files_matching(revision_id: str) -> list[str]:
    root = Path(__file__).resolve().parents[2]
    matches = []
    typed = f'revision: str = "{revision_id}"'
    plain = f"revision = '{revision_id}'"
    plain_double = f'revision = "{revision_id}"'
    for path in sorted((root / "alembic" / "versions").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if typed in text or plain in text or plain_double in text:
            matches.append(path.name)
    return matches


def test_only_one_techmkt001_revision_file_exists():
    assert _revision_files_matching("techmkt001") == [TECHMKT001_LOCATOR]


def test_only_one_techmkt002_revision_file_exists():
    assert _revision_files_matching("techmkt002") == [TECHMKT002_LOCATOR]


def test_techmkt001_revision_is_discoverable():
    script = _script()
    rev = script.get_revision("techmkt001")
    assert rev is not None
    assert rev.revision == "techmkt001"
    assert rev.down_revision == "perf_listing_indexes_001"


def test_techmkt002_revision_is_discoverable():
    script = _script()
    rev = script.get_revision("techmkt002")
    assert rev is not None
    assert rev.revision == "techmkt002"
    assert rev.down_revision == "techmkt001"


def test_single_head_is_techmkt002():
    script = _script()
    assert script.get_heads() == ["techmkt002"]


def test_upgrade_path_includes_marketplace_and_legacy_ids():
    script = _script()
    revisions = [sc.revision for sc in script.walk_revisions()]
    assert "techmkt002" in revisions
    assert "techmkt001" in revisions
    assert "techmkt002" in revisions
    assert "7f3e7e682dc7" in revisions
    # walk_revisions yields newest-first; latest legacy id is the head.
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
