"""
Person 4 — Domain registration stack (storefront + webhooks + admin).

``/api/v1/domain`` marketplace routes are mounted from ``app.main``.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.controller.admin.domain_registration_admin_controller import (
    router as domain_registration_admin_router,
)
from app.controller.domain.domain_storefront_controller import router as domain_storefront_router
from app.controller.domain.domain_webhook_controller import router as domain_webhook_router


def register(app: FastAPI) -> None:
    app.include_router(domain_storefront_router)
    app.include_router(domain_webhook_router)
    app.include_router(domain_registration_admin_router)
