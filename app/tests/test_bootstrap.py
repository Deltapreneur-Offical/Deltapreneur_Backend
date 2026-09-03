from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.bootstrap import configure_middleware, register_routers
from app.core.bot_middleware import BotGuardMiddleware
from app.core.config import settings
from app.core.rate_limiter import limiter
from app.core.request_middleware import RequestContextMiddleware


def test_configure_middleware_registers_the_expected_stack(monkeypatch) -> None:
    monkeypatch.setattr(
        type(settings),
        "resolved_cors_origins",
        lambda self: ["https://example.com"],
    )
    monkeypatch.setattr(
        type(settings),
        "resolved_cors_origin_regex",
        lambda self: None,
    )

    app = FastAPI()
    configure_middleware(app)

    assert app.state.limiter is limiter
    assert [mw.cls for mw in app.user_middleware] == [
        GZipMiddleware,
        RequestContextMiddleware,
        CORSMiddleware,
        BotGuardMiddleware,
        SlowAPIMiddleware,
    ]


def test_register_routers_includes_core_and_dev_routes(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")

    app = FastAPI()
    register_routers(app)

    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/health" in paths
    assert "/api/v1/auth/login" in paths
    assert "/test-upload/" in paths


def test_register_routers_skips_dev_only_routes_outside_development(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    app = FastAPI()
    register_routers(app)

    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/test-upload/" not in paths
