import time

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db

router = APIRouter(tags=["Health"])

_start_monotonic = time.monotonic()


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
)
def health() -> dict:
    return {"status": "ok"}


@router.get(
    "/ready",
    status_code=status.HTTP_200_OK,
)
def ready(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {
        "status": "ready",
        "database": "ok",
        "databaseHost": settings.database_host_label(),
        "storageBackend": settings.storage_backend(),
        "storageConfigured": settings.storage_configured(),
    }


@router.get(
    "/metrics",
    status_code=status.HTTP_200_OK,
)
def metrics() -> dict:
    if not settings.EXPOSE_METRICS:
        return {"enabled": False}
    return {
        "enabled": True,
        "uptime_seconds": round(time.monotonic() - _start_monotonic, 3),
        "environment": settings.ENVIRONMENT,
    }
