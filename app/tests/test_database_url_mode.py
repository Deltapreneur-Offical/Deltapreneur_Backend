from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import (
    _async_connect_args,
    _queue_pool_kwargs,
    _sync_connect_args,
    _to_async_url,
    _to_sync_url,
    async_engine,
    engine,
)


def test_sync_urls_use_psycopg2_for_sync_sessions() -> None:
    async_url = "postgresql+asyncpg://user:pass@localhost:5432/app"

    assert _to_sync_url(async_url) == "postgresql+psycopg2://user:pass@localhost:5432/app"
    assert _to_async_url(async_url) == async_url


def test_async_urls_use_asyncpg_for_async_sessions() -> None:
    sync_url = "postgresql+psycopg2://user:pass@localhost:5432/app"

    assert _to_sync_url(sync_url) == sync_url
    assert _to_async_url(sync_url) == "postgresql+asyncpg://user:pass@localhost:5432/app"


def test_db_timeout_and_recycle_settings() -> None:
    assert settings.DB_CONNECT_TIMEOUT_SECONDS == 5
    assert settings.DB_POOL_TIMEOUT_SECONDS == 10
    assert settings.DB_COMMAND_TIMEOUT_SECONDS == 30
    assert settings.DB_POOL_RECYCLE_SECONDS == 90
    assert settings.DB_POOL_SIZE == 3
    assert settings.DB_MAX_OVERFLOW == 2


def test_sync_connect_args_use_psycopg2_timeouts() -> None:
    args = _sync_connect_args()
    assert args["connect_timeout"] == settings.DB_CONNECT_TIMEOUT_SECONDS
    assert args["options"] == (
        f"-c statement_timeout={settings.DB_COMMAND_TIMEOUT_SECONDS * 1000}"
    )


def test_async_connect_args_use_asyncpg_timeouts() -> None:
    args = _async_connect_args()
    assert args["timeout"] == settings.DB_CONNECT_TIMEOUT_SECONDS
    assert args["command_timeout"] == settings.DB_COMMAND_TIMEOUT_SECONDS
    assert "statement_cache_size" not in args


def test_queue_pool_kwargs_include_timeout_and_recycle_without_raising_size() -> None:
    kwargs = _queue_pool_kwargs(settings.DB_POOL_SIZE, settings.DB_MAX_OVERFLOW)
    assert kwargs["pool_timeout"] == settings.DB_POOL_TIMEOUT_SECONDS
    assert kwargs["pool_recycle"] == settings.DB_POOL_RECYCLE_SECONDS
    assert kwargs["pool_size"] == 3
    assert kwargs["max_overflow"] == 2


def test_live_engines_apply_pool_timeouts_and_recycle() -> None:
    for live_engine in (engine, async_engine.sync_engine):
        if isinstance(live_engine.pool, NullPool):
            continue
        assert live_engine.pool.timeout() == settings.DB_POOL_TIMEOUT_SECONDS
        assert live_engine.pool._recycle == settings.DB_POOL_RECYCLE_SECONDS
        assert live_engine.pool._pre_ping is True
        assert live_engine.pool._max_overflow == settings.DB_MAX_OVERFLOW
