from app.core.database import _to_async_url, _to_sync_url


def test_sync_urls_use_psycopg2_for_sync_sessions() -> None:
    async_url = "postgresql+asyncpg://user:pass@localhost:5432/app"

    assert _to_sync_url(async_url) == "postgresql+psycopg2://user:pass@localhost:5432/app"
    assert _to_async_url(async_url) == async_url


def test_async_urls_use_asyncpg_for_async_sessions() -> None:
    sync_url = "postgresql+psycopg2://user:pass@localhost:5432/app"

    assert _to_sync_url(sync_url) == sync_url
    assert _to_async_url(sync_url) == "postgresql+asyncpg://user:pass@localhost:5432/app"
