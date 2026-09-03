"""
Auction test-suite fixtures.

Strategy:
- Use a dedicated test database. Configure `TEST_DATABASE_URL` (env var); if
  unset, the whole suite skips. It must point at a disposable LOCAL Postgres
  (never RDS, never the 5433 tunnel) — guards below enforce this.
- Create all auction-module tables once per test session.
- Truncate auction-related tables BEFORE each test (function-scoped) to give
  every test a clean slate while still allowing real commits — which is what
  the concurrency tests need to exercise SELECT FOR UPDATE.
- Override FastAPI deps `get_current_user` + `get_async_db` to inject test
  doubles deterministically.

Requires:
    pytest>=8
    pytest-asyncio>=0.23
    httpx>=0.27         (already in requirements.txt)
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import AsyncGenerator, Callable

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.database import Base, _to_async_url, get_async_db
from app.core.dependencies import get_current_user
from app.entity.auction.auction_entity import Auction
from app.entity.auction.bid_entity import Bid           # noqa: F401  (table registration)
from app.entity.auction.domain_entity import Domain     # noqa: F401  (table registration)
from app.entity.auction.payment_entity import Payment   # noqa: F401
from app.entity.auction.transaction_entity import Transaction  # noqa: F401
from app.entity.user.app_user import AppUser
from app.entity.user.refresh_token import RefreshToken  # noqa: F401
from app.entity.user.user_role import UserRole
from app.tests.auction.domain_test_util import ensure_domain_owned
from app.utils.enums import AuctionDuration, AuctionStatus


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


def _get_test_database_url() -> str | None:
    return (os.getenv("TEST_DATABASE_URL") or settings.TEST_DATABASE_URL or "").strip() or None


def _sync_rebuild_test_schema() -> None:
    """
    Rebuild the entire PostgreSQL public schema safely for tests.

    Using DROP SCHEMA ... CASCADE avoids foreign-key dependency
    issues that commonly happen with Base.metadata.drop_all().
    """
    from sqlalchemy import create_engine, text

    url = _get_test_database_url()
    if not url:
        pytest.skip(
            "TEST_DATABASE_URL must be set before running auction tests.",
            allow_module_level=False,
        )
    if url == settings.DATABASE_URL:
        pytest.fail(
            "TEST_DATABASE_URL must differ from DATABASE_URL."
        )
    _assert_test_db_host_is_local(url)

    # Convert async driver -> sync driver for schema operations
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace(
            "postgresql+asyncpg://",
            "postgresql+psycopg2://",
            1,
        )

    eng = create_engine(url, future=True)

    with eng.begin() as conn:

        # Force remove all tables, constraints, indexes, sequences
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))

        # Recreate clean public schema
        conn.execute(text("CREATE SCHEMA public"))

        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))

        # Recreate all ORM tables
        Base.metadata.create_all(bind=conn)

    eng.dispose()


@pytest.fixture(scope="session")
def _auction_schema_reset() -> None:
    _sync_rebuild_test_schema()
    return None


# --------------------------------------------------------------------------- #
# Engine + schema                                                             #
# --------------------------------------------------------------------------- #


def _resolve_test_db_url() -> str:
    url = _get_test_database_url()
    if not url:
        pytest.skip(
            "TEST_DATABASE_URL must be set before running auction tests. "
            "Never run the auction suite against your development DATABASE_URL.",
        )
    if url == settings.DATABASE_URL:
        pytest.fail(
            "TEST_DATABASE_URL must differ from DATABASE_URL to prevent "
            "accidental schema destruction."
        )
    _assert_test_db_host_is_local(url)
    return _to_async_url(url)


@pytest_asyncio.fixture(scope="session")
async def test_engine(_auction_schema_reset):
    engine = create_async_engine(_resolve_test_db_url(), future=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def test_sessionmaker(test_engine):
    return async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


# --------------------------------------------------------------------------- #
# Per-test isolation: truncate auction tables before each test                #
# --------------------------------------------------------------------------- #

# Order matters — children first, then parents.
_AUCTION_TABLES = ("transactions", "payments", "bids", "auctions", "domains")


CREATION_FEE_JSON = {"creationFeeOrderId": "order_test_creation_fee"}

BID_FEE_KWARGS = {
    "razorpay_order_id": "order_test_bid",
    "razorpay_payment_id": "pay_test_bid",
    "razorpay_signature": "sig_test_bid",
}


def make_place_bid_request(auction_id, amount):
    from app.model.auction.bid_request import PlaceBidRequest

    return PlaceBidRequest(auction_id=auction_id, amount=amount, **BID_FEE_KWARGS)


@pytest.fixture(autouse=True)
def _bypass_auction_creation_fee():
    with (
        patch(
            "app.service.auction.auction_service.AuctionFeeService.consume_creation_fee",
            new_callable=AsyncMock,
        ),
        patch(
            "app.service.auction.bid_service.AuctionFeeService.verify_bid_fee_payment",
            new_callable=AsyncMock,
        ),
        patch(
            "app.service.auction.bid_service.AuctionFeeService.consume_bid_fee",
            new_callable=AsyncMock,
        ),
        patch(
            "app.service.auction.bid_service.ensure_domain_verified_for_auction",
            new_callable=AsyncMock,
        ),
    ):
        yield


@pytest_asyncio.fixture(autouse=True)
async def _truncate_between_tests(test_sessionmaker):
    async with test_sessionmaker() as session:
        for tbl in _AUCTION_TABLES:
            await session.execute(
                text(f'TRUNCATE TABLE "{tbl}" RESTART IDENTITY CASCADE')
            )
        await session.commit()
    yield


# --------------------------------------------------------------------------- #
# Session for direct DB assertions                                            #
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def db_session(test_sessionmaker) -> AsyncGenerator[AsyncSession, None]:
    async with test_sessionmaker() as session:
        yield session


# --------------------------------------------------------------------------- #
# User factories                                                              #
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def user_factory(test_sessionmaker) -> Callable:
    """
    Factory that creates and persists an AppUser. Returns the saved entity.

    The AppUser table is assumed to already exist (created by Base.metadata).
    """
    async def _make(
        email: str | None = None,
        firstname: str = "Test",
        lastname: str = "User",
        role: UserRole = UserRole.USER,
    ) -> AppUser:
        async with test_sessionmaker() as session:
            user = AppUser(
                email=email or f"user-{uuid.uuid4().hex[:10]}@test.local",
                firstname=firstname,
                lastname=lastname,
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
async def seller(user_factory) -> AppUser:
    return await user_factory(firstname="Seller")


@pytest_asyncio.fixture
async def bidder(user_factory) -> AppUser:
    return await user_factory(firstname="Bidder")


@pytest_asyncio.fixture
async def admin_user(user_factory) -> AppUser:
    return await user_factory(firstname="Admin", role=UserRole.ADMIN)


# --------------------------------------------------------------------------- #
# Auction factory                                                             #
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def auction_factory(test_sessionmaker, seller) -> Callable:
    async def _make(
        *,
        created_by: uuid.UUID | None = None,
        domain_id: uuid.UUID | None = None,
        domain_owner: AppUser | None = None,
        min_bid_price: Decimal = Decimal("100.00"),
        duration: AuctionDuration = AuctionDuration.ONE_DAY,
        status: AuctionStatus = AuctionStatus.ACTIVE,
        end_time: datetime | None = None,
    ) -> Auction:
        dom_owner = domain_owner or seller
        creator = created_by if created_by is not None else seller.id
        did = domain_id or uuid.uuid4()
        await ensure_domain_owned(
            test_sessionmaker,
            dom_owner.id,
            domain_id=did,
            domain_name=f"factory-{did.hex[:16]}.test",
        )
        now = datetime.now(timezone.utc)
        et = end_time or (now + timedelta(seconds=duration.to_seconds()))
        async with test_sessionmaker() as session:
            a = Auction(
                domain_id=did,
                status=status,
                duration=duration,
                min_bid_price=min_bid_price,
                current_highest_bid=None,
                total_bids=0,
                current_winner_id=None,
                start_time=now,
                end_time=et,
                original_end_time=et,
                created_by=creator,
            )
            session.add(a)
            await session.commit()
            await session.refresh(a)
            return a
    return _make


# --------------------------------------------------------------------------- #
# FastAPI app + AsyncClient                                                    #
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def app_factory(test_sessionmaker, seller) -> Callable:
    """
    Returns a callable producing a FastAPI app with auction + bid routers and
    the standard dependencies overridden:
      - get_async_db          -> yields a session from the test sessionmaker
      - get_current_user      -> returns the user passed to the factory
    """
    from app.controller.auction.auction_controller import router as auction_router
    from app.controller.auction.bid_controller import router as bid_router
    from app.core.exceptions import register_exception_handlers

    def _make(current_user: AppUser | None = None) -> FastAPI:
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(auction_router)
        app.include_router(bid_router)

        async def _override_db():
            async with test_sessionmaker() as session:
                yield session

        def _override_user():
            return current_user or seller

        app.dependency_overrides[get_async_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user
        return app

    return _make


@pytest_asyncio.fixture
async def client_factory(app_factory) -> Callable:
    async def _make(current_user: AppUser | None = None):
        app = app_factory(current_user=current_user)
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://testserver")
    return _make
