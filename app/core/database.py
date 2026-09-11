from typing import AsyncGenerator
from urllib.parse import quote, urlparse, urlunparse
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.entity.base.base import Base


def _uses_supabase_pooler(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return "pooler.supabase.com" in host


def _supabase_pooler_port(url: str) -> int | None:
    try:
        parsed = urlparse(url)
        if _uses_supabase_pooler(url):
            return parsed.port
    except Exception:
        pass
    return None


def _normalize_supabase_pooler_url(url: str) -> str:
    """Prefer Supabase transaction pooler (:6543) over session mode (:5432).

    Render deploys can briefly overlap old/new instances plus migrations, and
    the session pooler has a strict client cap. Transaction mode combined with
    ``NullPool`` keeps the app and Alembic from pinning scarce sessions.
    """
    raw = (url or "").strip()
    if not raw:
        return raw

    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        port = parsed.port or 5432
    except Exception:
        return raw

    if "pooler.supabase.com" not in host or port != 5432:
        return raw

    auth = ""
    if parsed.username:
        auth = quote(parsed.username, safe="")
        if parsed.password is not None:
            auth = f"{auth}:{quote(parsed.password, safe='')}"
        auth = f"{auth}@"

    netloc = f"{auth}{parsed.hostname}:6543"
    return urlunparse(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


# Respect DATABASE_URL, but normalize Supabase pooler URLs to the safer
# transaction mode when they target the pooled host on :5432.
# AWS RDS and other Postgres hosts use the URL unchanged.
# AWS RDS and other Postgres hosts use normal SQLAlchemy pooling (DB_POOL_SIZE / DB_MAX_OVERFLOW).
DATABASE_URL = _normalize_supabase_pooler_url(settings.resolved_database_url())


def _effective_pool_settings() -> tuple[int, int]:
    """Tune SQLAlchemy pool size for Supabase pooler mode."""
    pool_size = settings.DB_POOL_SIZE
    max_overflow = settings.DB_MAX_OVERFLOW
    if _uses_supabase_pooler(DATABASE_URL):
        if _supabase_pooler_port(DATABASE_URL) == 6543:
            # Transaction pooler — pgbouncer multiplexes many clients onto few
            # server connections, so we can hold a wider client-side pool to
            # absorb a bursty page load (~10 parallel queries) plus background
            # workers without connecting per request.
            pool_size = max(pool_size, 10)
            max_overflow = max(max_overflow, 10)
            return pool_size, max_overflow
        # Session pooler (:5432) — allow modest parallelism (handlers may open sync + async).
        pool_size = min(max(pool_size, 3), 5)
        max_overflow = min(max(max_overflow, 2), 3)
    return pool_size, max_overflow


def _pgbouncer_prepared_statement_name() -> str:
    return f"__asyncpg_{uuid4()}__"


def _positive_int(value: int) -> int:
    return max(1, int(value))


def _sync_connect_args() -> dict:
    """psycopg2 connect_args: fail fast on dead/unreachable servers."""
    timeout_ms = _positive_int(settings.DB_COMMAND_TIMEOUT_SECONDS) * 1000
    return {
        "connect_timeout": _positive_int(settings.DB_CONNECT_TIMEOUT_SECONDS),
        "options": f"-c statement_timeout={timeout_ms}",
    }


def _async_connect_args(
    *,
    disable_statement_cache: bool = False,
    unique_prepared_names: bool = False,
) -> dict:
    """asyncpg connect_args: connection + command timeouts (seconds)."""
    args: dict = {
        "timeout": _positive_int(settings.DB_CONNECT_TIMEOUT_SECONDS),
        "command_timeout": _positive_int(settings.DB_COMMAND_TIMEOUT_SECONDS),
    }
    if disable_statement_cache or unique_prepared_names:
        args["statement_cache_size"] = 0
        args["prepared_statement_cache_size"] = 0
    if unique_prepared_names:
        args["prepared_statement_name_func"] = _pgbouncer_prepared_statement_name
    return args


def _queue_pool_kwargs(pool_size: int, max_overflow: int) -> dict:
    """SQLAlchemy QueuePool settings. Do not use with NullPool."""
    return {
        "pool_recycle": settings.DB_POOL_RECYCLE_SECONDS,
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_timeout": settings.DB_POOL_TIMEOUT_SECONDS,
    }


def _to_sync_url(url: str) -> str:
    """Promote an async Postgres URL to the sync psycopg2 variant."""
    if url.startswith("postgresql+psycopg2://"):
        return url
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
    return url

_sync_pool_size, _sync_max_overflow = _effective_pool_settings()
_sync_engine_kwargs: dict = {
    "pool_pre_ping": True,
    "future": True,
    "connect_args": _sync_connect_args(),
}

def _transaction_pooler_reuse_enabled() -> bool:
    """Whether to keep a bounded QueuePool on the Supabase transaction pooler.

    NullPool opened a fresh TCP+TLS connection per request, so a bursty page
    load hammered the pooler and intermittently timed out. A small QueuePool
    reuses connections and is safe with pgbouncer transaction mode as long as
    prepared-statement caching stays disabled (handled in _async_connect_args).
    """
    return bool(getattr(settings, "DB_POOLER_REUSE_CONNECTIONS", True))


if _uses_supabase_pooler(DATABASE_URL):
    if _supabase_pooler_port(DATABASE_URL) == 6543:
        if _transaction_pooler_reuse_enabled():
            # Transaction pooler — reuse a small pool instead of connecting per request.
            _sync_engine_kwargs.update(
                _queue_pool_kwargs(_sync_pool_size, _sync_max_overflow)
            )
        else:
            # Legacy behaviour — open/close per request.
            _sync_engine_kwargs["poolclass"] = NullPool
    else:
        # Session pooler (:5432) — keep SQLAlchemy pool tiny to respect session limits.
        _sync_engine_kwargs.update(_queue_pool_kwargs(_sync_pool_size, _sync_max_overflow))
else:
    _sync_engine_kwargs.update(_queue_pool_kwargs(_sync_pool_size, _sync_max_overflow))

engine = create_engine(
    _to_sync_url(DATABASE_URL),
    **_sync_engine_kwargs,
)


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Async engine (auction / payment modules — SQLAlchemy 2.0 async + asyncpg)
# ---------------------------------------------------------------------------

def _to_async_url(url: str) -> str:
    """Promote a sync Postgres URL to its asyncpg variant."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    return url


_async_pool_size, _async_max_overflow = _effective_pool_settings()

_async_engine_kwargs: dict = {
    "pool_pre_ping": True,
    "future": True,
}

if _uses_supabase_pooler(DATABASE_URL):
    if _supabase_pooler_port(DATABASE_URL) == 6543:
        # Transaction pooler — statement caching MUST stay disabled and prepared
        # statement names MUST stay unique regardless of pool class, or asyncpg
        # raises DuplicatePreparedStatementError behind pgbouncer.
        _async_engine_kwargs["connect_args"] = _async_connect_args(
            disable_statement_cache=True,
            unique_prepared_names=True,
        )
        if _transaction_pooler_reuse_enabled():
            # Reuse a small bounded pool instead of connecting per request.
            _async_engine_kwargs.update(
                _queue_pool_kwargs(_async_pool_size, _async_max_overflow)
            )
        else:
            # Legacy behaviour — no SQLAlchemy pooling.
            _async_engine_kwargs["poolclass"] = NullPool
    else:
        # Session pooler (:5432) — keep SQLAlchemy pool; disable statement caches only.
        _async_engine_kwargs.update(
            _queue_pool_kwargs(_async_pool_size, _async_max_overflow)
        )
        _async_engine_kwargs["connect_args"] = _async_connect_args(
            disable_statement_cache=True,
        )
else:
    _async_engine_kwargs.update(
        _queue_pool_kwargs(_async_pool_size, _async_max_overflow)
    )
    _async_engine_kwargs["connect_args"] = _async_connect_args()

async_engine = create_async_engine(
    _to_async_url(DATABASE_URL),
    **_async_engine_kwargs,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an AsyncSession; caller commits/rollbacks."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
