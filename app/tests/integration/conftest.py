"""Shared pytest fixtures for DB-backed integration tests."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import AsyncGenerator, Callable

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import _to_async_url, get_async_db
from app.core.dependencies import get_current_user
from app.core.exceptions import register_exception_handlers
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole


def _assert_test_db_host_is_local(url: str) -> None:
    """Refuse destructive schema resets against any non-local database host.

    This suite runs DROP SCHEMA public CASCADE on TEST_DATABASE_URL. A remote
    host (RDS, Supabase, ...) is never a safe target — a string-inequality
    check against DATABASE_URL is not enough because the same physical
    database can be reachable via a tunnel address AND its direct hostname.
    """
    from app.tests.db_safety import check_test_db_url_is_local

    error = check_test_db_url_is_local(url)
    if error:
        pytest.fail(error)


def _require_test_db_url() -> str:
    url = (os.getenv("TEST_DATABASE_URL") or settings.TEST_DATABASE_URL or "").strip()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set — skipping DB integration tests.")
    if url == settings.DATABASE_URL:
        pytest.fail(
            "TEST_DATABASE_URL must differ from DATABASE_URL to prevent destructive ops."
        )
    _assert_test_db_host_is_local(url)
    return url


def _to_sync_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    return url


def _reset_schema_and_migrate(sync_url: str) -> None:
    engine = create_engine(sync_url, future=True)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
    engine.dispose()

    backend_root = Path(__file__).resolve().parents[3]
    alembic_ini = backend_root / "alembic.ini"
    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", sync_url)

    prev_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = sync_url
    try:
        command.upgrade(cfg, "head")
    finally:
        if prev_db_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prev_db_url


@pytest.fixture(scope="session")
def integration_db_url() -> str:
    return _require_test_db_url()


@pytest.fixture(scope="session")
def migrated_integration_db(integration_db_url: str) -> None:
    _reset_schema_and_migrate(_to_sync_url(integration_db_url))
    return None


@pytest_asyncio.fixture(scope="session")
async def integration_engine(migrated_integration_db, integration_db_url: str):
    engine = create_async_engine(_to_async_url(integration_db_url), future=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def integration_sessionmaker(integration_engine):
    return async_sessionmaker(
        bind=integration_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest_asyncio.fixture
async def integration_db(integration_sessionmaker) -> AsyncGenerator[AsyncSession, None]:
    async with integration_sessionmaker() as session:
        yield session


@pytest_asyncio.fixture
async def integration_user_factory(integration_sessionmaker) -> Callable:
    async def _make(
        *,
        email: str | None = None,
        role: UserRole = UserRole.USER,
    ) -> AppUser:
        async with integration_sessionmaker() as session:
            user = AppUser(
                email=email or f"integration-{uuid.uuid4().hex[:10]}@test.local",
                firstname="Integration",
                lastname="User",
                role=role,
                active=True,
                email_verified=True,
                profile_complete=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return _make


@pytest_asyncio.fixture
async def integration_app_factory(integration_sessionmaker) -> Callable:
    """Build a FastAPI app with selected routers and dependency overrides."""

    def _make(*, routers: list, current_user: AppUser | None = None) -> FastAPI:
        app = FastAPI()
        register_exception_handlers(app)
        for router in routers:
            app.include_router(router)

        async def _override_db():
            async with integration_sessionmaker() as session:
                yield session

        async def _override_user():
            if current_user is None:
                raise RuntimeError("integration test must pass current_user")
            return current_user

        app.dependency_overrides[get_async_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user
        return app

    return _make


@pytest_asyncio.fixture
async def integration_client_factory(integration_app_factory) -> Callable:
    async def _make(*, routers: list, current_user: AppUser):
        app = integration_app_factory(routers=routers, current_user=current_user)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client

    return _make
