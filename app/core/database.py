from typing import AsyncGenerator
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
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


# Respect DATABASE_URL as configured.
# Supabase pooler (:5432 session / :6543 transaction) uses special pool settings below.
# AWS RDS and other Postgres hosts use normal SQLAlchemy pooling (DB_POOL_SIZE / DB_MAX_OVERFLOW).
DATABASE_URL = settings.resolved_database_url()


def _effective_pool_settings() -> tuple[int, int]:
    """Tune SQLAlchemy pool size for Supabase pooler mode."""
    pool_size = settings.DB_POOL_SIZE
    max_overflow = settings.DB_MAX_OVERFLOW
    if _uses_supabase_pooler(DATABASE_URL):
        if _supabase_pooler_port(DATABASE_URL) == 6543:
            # Transaction pooler — NullPool is used; these values are ignored.
            return pool_size, max_overflow
        # Session pooler (:5432) — allow modest parallelism (handlers may open sync + async).
        pool_size = min(max(pool_size, 3), 5)
        max_overflow = min(max(max_overflow, 2), 3)
    return pool_size, max_overflow


def _pgbouncer_prepared_statement_name() -> str:
    return f"__asyncpg_{uuid4()}__"


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
}

if _uses_supabase_pooler(DATABASE_URL):
    if _supabase_pooler_port(DATABASE_URL) == 6543:
        # Transaction pooler — open/close per request so parallel HTTP handlers don't queue.
        _sync_engine_kwargs["poolclass"] = NullPool
    else:
        # Session pooler (:5432) — keep SQLAlchemy pool tiny to respect session limits.
        _sync_engine_kwargs["pool_recycle"] = settings.DB_POOL_RECYCLE_SECONDS
        _sync_engine_kwargs["pool_size"] = _sync_pool_size
        _sync_engine_kwargs["max_overflow"] = _sync_max_overflow
else:
    _sync_engine_kwargs["pool_recycle"] = settings.DB_POOL_RECYCLE_SECONDS
    _sync_engine_kwargs["pool_size"] = _sync_pool_size
    _sync_engine_kwargs["max_overflow"] = _sync_max_overflow

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


_pooler_async_connect_args = {
    "statement_cache_size": 0,
    "prepared_statement_cache_size": 0,
    "prepared_statement_name_func": _pgbouncer_prepared_statement_name,
}

_async_pool_size, _async_max_overflow = _effective_pool_settings()

_async_engine_kwargs: dict = {
    "pool_pre_ping": True,
    "future": True,
}

if _uses_supabase_pooler(DATABASE_URL):
    if _supabase_pooler_port(DATABASE_URL) == 6543:
        # Transaction pooler — disable SQLAlchemy pooling; unique prepared statement names.
        _async_engine_kwargs["poolclass"] = NullPool
        _async_engine_kwargs["connect_args"] = _pooler_async_connect_args
    else:
        # Session pooler (:5432) — keep SQLAlchemy pool; disable statement caches only.
        _async_engine_kwargs["pool_recycle"] = settings.DB_POOL_RECYCLE_SECONDS
        _async_engine_kwargs["pool_size"] = _async_pool_size
        _async_engine_kwargs["max_overflow"] = _async_max_overflow
        _async_engine_kwargs["connect_args"] = {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        }
else:
    _async_engine_kwargs["pool_recycle"] = settings.DB_POOL_RECYCLE_SECONDS
    _async_engine_kwargs["pool_size"] = _async_pool_size
    _async_engine_kwargs["max_overflow"] = _async_max_overflow

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
