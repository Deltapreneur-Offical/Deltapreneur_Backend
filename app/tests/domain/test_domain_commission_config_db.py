import json
from unittest.mock import AsyncMock

import pytest

from app.service.domain import domain_commission_config as commission


class FakeSettingsRepository:
    values: dict[str, str] = {}

    def __init__(self, _session):
        pass

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def insert_if_absent(self, key: str, value: str) -> None:
        self.values.setdefault(key, value)

    async def set(self, key: str, value: str) -> None:
        self.values[key] = value


@pytest.fixture(autouse=True)
def fake_repository(monkeypatch):
    original_runtime_config = commission.load()
    FakeSettingsRepository.values = {}
    monkeypatch.setattr(
        commission,
        "PlatformSettingsRepository",
        FakeSettingsRepository,
    )
    yield
    commission._runtime_config = original_runtime_config


@pytest.mark.asyncio
async def test_refresh_seeds_database_from_legacy_config(monkeypatch):
    legacy = {
        "registration": {"default": 0.15, "by_tld": {".in": 0.2}},
        "renewal": {"default": 0.1, "by_tld": {}},
    }
    monkeypatch.setattr(commission, "_load_legacy_seed", lambda: legacy)
    session = AsyncMock()

    config = await commission.refresh_from_db(session)

    saved = json.loads(
        FakeSettingsRepository.values[commission.KEY_DOMAIN_COMMISSION_CONFIG]
    )
    assert saved == legacy
    assert config["registration"]["default"] == 0.15
    assert config["registration"]["by_tld"][".in"] == 0.2
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_normalises_and_shares_commission_config():
    session = AsyncMock()
    previous_revision = commission.revision()

    saved = await commission.save(
        session,
        {
            "registration": {
                "default": 0.12,
                "by_tld": {"IN": 0.25, ".COM": 0.18},
            },
        },
    )

    persisted = json.loads(
        FakeSettingsRepository.values[commission.KEY_DOMAIN_COMMISSION_CONFIG]
    )
    assert persisted["registration"]["by_tld"] == {".in": 0.25, ".com": 0.18}
    assert saved["premium_registration"] == saved["registration"]
    assert commission.get_rate("registration", "in") == 0.25
    assert commission.revision() != previous_revision
    session.commit.assert_awaited_once()
