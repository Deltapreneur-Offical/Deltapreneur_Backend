"""Operations virtual-assistant catalog business logic."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.operations.operations_service_entity import OperationsService
from app.model.operations.operations_service_mapper import build_operations_service_response
from app.model.operations.operations_service_request import (
    OperationsServiceAvailabilityRequest,
    OperationsServiceCreateRequest,
    OperationsServiceUpdateRequest,
)
from app.model.operations.operations_service_response import OperationsServiceResponse
from app.repository.operations_service_repository import OperationsServiceRepository

CATEGORY_DEFAULT_ICONS: dict[str, str] = {
    "people": "Users",
    "finance": "Calculator",
    "marketing": "Megaphone",
    "technology": "Code",
    "sales": "TrendingUp",
    "support": "MessageCircle",
    "creative": "Palette",
    "growth": "Briefcase",
    "operations": "ClipboardList",
}

DEFAULT_DESCRIPTION = (
    "Dedicated remote professional for your MSME — flexible monthly engagement."
)


class OperationsServiceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = OperationsServiceRepository(session)

    @staticmethod
    def _serialize(row: OperationsService) -> dict:
        return build_operations_service_response(row).model_dump(
            mode="json",
            by_alias=True,
        )

    @staticmethod
    def _default_icon(category: str) -> str:
        return CATEGORY_DEFAULT_ICONS.get(category.lower(), "Headset")

    async def list_public(self, *, service_type: str | None = None) -> list[dict]:
        rows = await self._repo.list_public(service_type=service_type)
        return [self._serialize(row) for row in rows]

    async def get_public(self, service_id: uuid.UUID) -> dict:
        row = await self._repo.get_by_id(service_id, public_only=True)
        if row is None:
            raise AppException("Operations service not found", status_code=404)
        return self._serialize(row)

    async def list_admin(self) -> list[dict]:
        rows = await self._repo.list_admin()
        return [self._serialize(row) for row in rows]

    async def create_admin(
        self,
        payload: OperationsServiceCreateRequest,
    ) -> dict:
        max_order = await self._repo.get_max_display_order()
        category = payload.category.strip().lower()
        row = OperationsService(
            name=payload.name.strip(),
            category=category,
            description=(payload.description or DEFAULT_DESCRIPTION).strip(),
            price=float(payload.price),
            is_available=payload.is_available,
            icon=self._default_icon(category),
            display_order=max_order + 1,
            skills=None,
            service_type=payload.service_type,
            government_fees_applicable=payload.government_fees_applicable,
            government_fee_text=(payload.government_fee_text or "Government fees applicable").strip(),
        )
        created = await self._repo.create(row)
        await self._session.commit()
        return self._serialize(created)

    async def update_admin(
        self,
        service_id: uuid.UUID,
        payload: OperationsServiceUpdateRequest,
    ) -> dict:
        row = await self._repo.get_by_id(service_id)
        if row is None:
            raise AppException("Operations service not found", status_code=404)

        category = payload.category.strip().lower()
        row.name = payload.name.strip()
        row.category = category
        row.description = (payload.description or DEFAULT_DESCRIPTION).strip()
        row.price = float(payload.price)
        row.is_available = payload.is_available
        row.service_type = payload.service_type
        row.government_fees_applicable = payload.government_fees_applicable
        row.government_fee_text = (payload.government_fee_text or "Government fees applicable").strip()
        if not row.icon:
            row.icon = self._default_icon(category)

        updated = await self._repo.save(row)
        await self._session.commit()
        return self._serialize(updated)

    async def patch_availability_admin(
        self,
        service_id: uuid.UUID,
        payload: OperationsServiceAvailabilityRequest,
    ) -> dict:
        row = await self._repo.get_by_id(service_id)
        if row is None:
            raise AppException("Operations service not found", status_code=404)

        row.is_available = payload.is_available
        updated = await self._repo.save(row)
        await self._session.commit()
        return self._serialize(updated)

    async def delete_admin(
        self,
        service_id: uuid.UUID,
        *,
        deleted_by: uuid.UUID | None = None,
    ) -> None:
        row = await self._repo.get_by_id(service_id)
        if row is None:
            raise AppException("Operations service not found", status_code=404)

        await self._repo.soft_delete(row, deleted_by=deleted_by)
        await self._session.commit()
