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
    assert script.get_current_head() == "techmkt002"


def test_alembic_can_locate_render_techmkt002_stamp():
    script = _script()
    rev = script.get_revision("techmkt002")
    assert rev is not None
    assert rev.revision == "techmkt002"
    assert rev.down_revision == "techmkt001"
