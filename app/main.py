"""HubRegistrar FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.background_jobs import start_background_jobs, stop_background_jobs
from app.bootstrap import configure_middleware, register_routers
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging_config import configure_logging

# -------------------------------------------------------------------
# Logging
# -------------------------------------------------------------------

configure_logging()

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Lifespan
# -------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info(
        "Starting HubRegistrar Backend | environment=%s",
        settings.ENVIRONMENT,
    )
    logger.info(
        "AI config | AI_PROVIDER=%s AI_MODEL=%s OPENROUTER_BASE_URL=%s OPENROUTER_API_KEY_CONFIGURED=%s",
        settings.AI_PROVIDER,
        settings.AI_MODEL,
        settings.OPENROUTER_BASE_URL,
        bool(settings.OPENROUTER_API_KEY.strip()),
    )
    logger.info(
        "Virtual Assistant module loaded | application endpoint=/api/v1/virtual-assistant"
    )

    from app.integrations import domain_registrar
    reg = domain_registrar.active_registrar()
    live_checkout = not reg.is_sandbox()
    val_report = reg.validate_runtime(for_live_checkout=live_checkout)
    profile = val_report["profile"]
    logger.info(
        "%s registrar | env=%s api=%s control_panel=%s configured=%s nameservers=%s",
        settings.domain_registrar().upper(),
        profile["env"],
        profile["apiBaseUrl"],
        profile["controlPanelUrl"],
        profile["configured"],
        ",".join(val_report["nameservers"]) or "(none)",
    )
    for warn in val_report["warnings"]:
        logger.warning("%s config: %s", settings.domain_registrar().upper(), warn)
    for err in val_report["blockingIssues"]:
        logger.error("%s config BLOCKING: %s", settings.domain_registrar().upper(), err)

    if settings.gstin_live_configured():
        logger.info("GSTIN live verification enabled (sheet.gstincheck.co.in)")
    elif settings.gstin_sandbox_enabled():
        logger.info("GSTIN sandbox mode — format check only, no live API")
    elif settings.ENVIRONMENT == "production":
        logger.warning(
            "GSTIN live verification is NOT configured. "
            "Set GSTIN_API_KEY on Render and GSTIN_API_SANDBOX=false."
        )

    scheduler_task: asyncio.Task | None = None

    # Run database Enum migration for hardware categories and auto-create missing tables
    try:
        from app.core.database import engine
        from app.entity.base.base import Base
        import app.entity.user.app_user  # noqa: F401
        import app.entity.platform.track_record_entity  # noqa: F401
        import app.entity.coventure.partner_entity  # noqa: F401
        Base.metadata.create_all(bind=engine)

        from sqlalchemy import text
        with engine.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            for val in [
                "IOT_DEVICE", "CONSUMER_ELECTRONICS", "INDUSTRIAL_EQUIPMENT",
                "MEDICAL_DEVICE", "NETWORKING_EQUIPMENT", "ROBOTICS",
                "EMBEDDED_SYSTEM", "SECURITY_DEVICE", "SMART_HOME",
                "COMPONENTS", "MANUFACTURING_EQUIPMENT"
            ]:
                try:
                    conn.execute(text(f"ALTER TYPE software_category_enum ADD VALUE '{val}'"))
                except Exception:
                    pass
    except Exception as db_err:
        logger.warning("Could not run database migrations/initialization: %s", db_err)

    if settings.BACKGROUND_JOBS_ENABLED:
        scheduler_task = start_background_jobs()
    else:
        logger.info(
            "Background jobs disabled (BACKGROUND_JOBS_ENABLED=false)"
        )

    try:

        yield

    finally:

        if scheduler_task is not None:
            scheduler_task.cancel()

            try:

                await scheduler_task

            except asyncio.CancelledError:
                pass

        if settings.BACKGROUND_JOBS_ENABLED:
            await stop_background_jobs()

        logger.info(
            "HubRegistrar Backend shutdown complete"
        )


# -------------------------------------------------------------------
# FastAPI App
# -------------------------------------------------------------------

app = FastAPI(
    title="HubRegistrar Backend",
    version="0.1.0",
    lifespan=lifespan,
)

# -------------------------------------------------------------------
# Middleware
# -------------------------------------------------------------------

configure_middleware(app)

cors_origins = settings.resolved_cors_origins()
cors_origin_regex = settings.resolved_cors_origin_regex()
if cors_origins or cors_origin_regex:
    logger.info(
        "CORS enabled origins=%s regex=%s",
        cors_origins,
        cors_origin_regex,
    )
elif settings.ENVIRONMENT == "production":
    logger.warning(
        "CORS_ALLOW_ORIGINS is empty in production."
    )

# -------------------------------------------------------------------
# Exception Handlers
# -------------------------------------------------------------------

app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler,
)

register_exception_handlers(app)

# -------------------------------------------------------------------
# REST Routers
# -------------------------------------------------------------------

register_routers(app)

# -------------------------------------------------------------------
# Static files — locally stored uploads (e.g. LinkedIn profile images)
# -------------------------------------------------------------------

_uploads_dir = Path(__file__).resolve().parents[1] / "uploads"
_uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")

# -------------------------------------------------------------------
# Root Endpoint
# -------------------------------------------------------------------

@app.get("/")
async def root():

    return {
        "message": "Backend running",
        "environment": settings.ENVIRONMENT,
    }
