"""API v1 — domain-only routes not mounted in ``app.main``."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.endpoints import domain


def register_person4_routes(app: FastAPI) -> None:
    """Mount domain storefront, webhooks, and registration admin routers."""
    domain.register(app)


__all__ = ["register_person4_routes"]
