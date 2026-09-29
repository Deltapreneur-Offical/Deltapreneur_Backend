from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def _script() -> ScriptDirectory:
    ini = Path(__file__).resolve().parents[3] / "alembic.ini"
    return ScriptDirectory.from_config(Config(str(ini)))


def test_alembic_can_locate_render_techmkt001_stamp():
    script = _script()
    rev = script.get_revision("techmkt001")
    assert rev is not None
    assert rev.revision == "techmkt001"
    # techmkt002 must stay in the ancestry of the (single) head; the head itself
    # is not hard-coded because newer migrations move it forward.
    head = script.get_current_head()
    ancestors = {sc.revision for sc in script.walk_revisions(base="base", head=head)}
    assert "techmkt002" in ancestors


def test_alembic_can_locate_render_techmkt002_stamp():
    script = _script()
    rev = script.get_revision("techmkt002")
    assert rev is not None
    assert rev.revision == "techmkt002"
    assert rev.down_revision == "techmkt001"
