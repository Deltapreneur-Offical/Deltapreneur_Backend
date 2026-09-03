"""Hub Registrar category business logic."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.hub_registrar.hub_registrar_category_entity import (
    HubRegistrarCategory,
)
from app.model.hub_registrar.hub_registrar_category_request import (
    HubRegistrarCategoryCreateRequest,
    HubRegistrarCategoryUpdateRequest,
)
from app.repository.hub_registrar_category_repository import (
    HubRegistrarCategoryRepository,
)


class HubRegistrarCategoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = HubRegistrarCategoryRepository(session)

    # ── Serialisation ──────────────────────────────────────────────────────

    @staticmethod
    def _serialize_public(row: HubRegistrarCategory) -> dict:
        """Return only the fields needed by the public homepage API."""
        return {
            "id": str(row.id),
            "slug": row.slug,
            "name": row.name,
            "description": row.description,
            "startingPrice": row.starting_price,
            "icon": row.icon,
            "displayOrder": row.display_order,
            "isActive": row.is_active,
        }

    @staticmethod
    def _serialize_admin(row: HubRegistrarCategory) -> dict:
        """Return all admin-relevant fields."""
        return {
            "id": str(row.id),
            "slug": row.slug,
            "name": row.name,
            "description": row.description,
            "startingPrice": row.starting_price,
            "icon": row.icon,
            "displayOrder": row.display_order,
            "isActive": row.is_active,
            "createdAt": row.created_at.isoformat() if row.created_at else None,
            "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        }

    # ── Public ─────────────────────────────────────────────────────────────

    async def list_public(self) -> list[dict]:
        rows = await self._repo.list_public()
        return [self._serialize_public(row) for row in rows]

    # ── Admin ──────────────────────────────────────────────────────────────

    async def list_admin(self) -> list[dict]:
        rows = await self._repo.list_admin()
        return [self._serialize_admin(row) for row in rows]

    async def get_admin(self, category_id: uuid.UUID) -> dict:
        row = await self._repo.get_by_id(category_id)
        if row is None:
            raise AppException("Category not found", status_code=404)
        return self._serialize_admin(row)

    async def create_admin(
        self,
        payload: HubRegistrarCategoryCreateRequest,
    ) -> dict:
        # Check slug uniqueness
        existing = await self._repo.get_by_slug(payload.slug)
        if existing is not None:
            raise AppException(
                f"Category with slug '{payload.slug}' already exists",
                status_code=409,
            )

        max_order = await self._repo.get_max_display_order()

        row = HubRegistrarCategory(
            slug=payload.slug,
            name=payload.name,
            description=payload.description,
            starting_price=payload.starting_price,
            icon=payload.icon,
            display_order=payload.display_order if payload.display_order > 0 else max_order + 1,
            is_active=payload.is_active,
        )
        created = await self._repo.create(row)
        await self._session.commit()
        return self._serialize_admin(created)

    async def update_admin(
        self,
        category_id: uuid.UUID,
        payload: HubRegistrarCategoryUpdateRequest,
    ) -> dict:
        row = await self._repo.get_by_id(category_id)
        if row is None:
            raise AppException("Category not found", status_code=404)

        # Slug is intentionally IMMUTABLE after creation.
        # Reason: operations_services.category stores the slug as a plain
        # string and changing it here would silently orphan linked services.
        # If a slug rename is ever needed it should be a dedicated migration.

        if payload.name is not None:
            row.name = payload.name
        if payload.description is not None:
            row.description = payload.description
        if payload.starting_price is not None:
            row.starting_price = payload.starting_price
        if payload.icon is not None:
            row.icon = payload.icon
        if payload.display_order is not None:
            row.display_order = payload.display_order
        if payload.is_active is not None:
            row.is_active = payload.is_active

        updated = await self._repo.save(row)
        await self._session.commit()
        return self._serialize_admin(updated)

    async def delete_admin(
        self,
        category_id: uuid.UUID,
        *,
        deleted_by: uuid.UUID | None = None,
    ) -> None:
        row = await self._repo.get_by_id(category_id)
        if row is None:
            raise AppException("Category not found", status_code=404)
        await self._repo.soft_delete(row, deleted_by=deleted_by)
        await self._session.commit()
