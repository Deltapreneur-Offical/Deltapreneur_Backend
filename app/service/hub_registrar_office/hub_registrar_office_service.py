"""Hub Registrar Office service - business logic for office management."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.hub_registrar_office.hub_registrar_office_entity import (
    HubRegistrarOffice,
)
from app.model.hub_registrar_office.hub_registrar_office_request import (
    HubRegistrarOfficeCreateRequest,
    HubRegistrarOfficeUpdateRequest,
)


class HubRegistrarOfficeService:
    """Service for Hub Registrar Office CRUD operations."""

    @staticmethod
    async def get_public_offices(session: AsyncSession) -> List[HubRegistrarOffice]:
        """Get all active, non-deleted offices for public display."""
        stmt = (
            select(HubRegistrarOffice)
            .where(
                HubRegistrarOffice.is_deleted == False,
                HubRegistrarOffice.is_active == True,
            )
            .order_by(HubRegistrarOffice.display_order, HubRegistrarOffice.created_at)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_office_by_id(
        session: AsyncSession, office_id: UUID
    ) -> Optional[HubRegistrarOffice]:
        """Get a single active office by ID."""
        stmt = select(HubRegistrarOffice).where(
            HubRegistrarOffice.id == office_id,
            HubRegistrarOffice.is_deleted == False,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_offices_admin(
        session: AsyncSession, include_deleted: bool = False
    ) -> List[HubRegistrarOffice]:
        """Get all offices for admin (optionally including deleted)."""
        stmt = select(HubRegistrarOffice)
        if not include_deleted:
            stmt = stmt.where(HubRegistrarOffice.is_deleted == False)
        stmt = stmt.order_by(HubRegistrarOffice.display_order, HubRegistrarOffice.created_at)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def _check_zone_unique(
        session: AsyncSession,
        office_name: str,
        zone: int,
        exclude_id: Optional[UUID] = None,
    ) -> None:
        """Raise ValueError if another active office has the same operator + zone."""
        if zone <= 0:
            return  # 0 means no zone assigned - skip uniqueness check
        stmt = select(HubRegistrarOffice).where(
            HubRegistrarOffice.office_name == office_name,
            HubRegistrarOffice.zone == zone,
            HubRegistrarOffice.is_deleted == False,
            HubRegistrarOffice.is_active == True,
        )
        if exclude_id:
            stmt = stmt.where(HubRegistrarOffice.id != exclude_id)
        result = await session.execute(stmt)
        if result.scalar_one_or_none():
            raise ValueError(
                f"Zone {zone} is already assigned to {office_name}. "
                "Please choose another zone."
            )

    @staticmethod
    async def create_office(
        session: AsyncSession,
        data: HubRegistrarOfficeCreateRequest,
    ) -> HubRegistrarOffice:
        """Create a new office."""
        await HubRegistrarOfficeService._check_zone_unique(
            session, data.office_name, data.zone
        )
        office = HubRegistrarOffice(
            office_name=data.office_name,
            phone_number=data.phone_number,
            city=data.city,
            full_address=data.full_address,
            map_link=data.map_link,
            zone=data.zone,
            display_order=data.display_order,
            is_active=data.is_active,
        )
        session.add(office)
        await session.commit()
        await session.refresh(office)
        return office

    @staticmethod
    async def update_office(
        session: AsyncSession,
        office: HubRegistrarOffice,
        data: HubRegistrarOfficeUpdateRequest,
    ) -> HubRegistrarOffice:
        """Update an existing office."""
        update_data = data.model_dump(exclude_unset=True)
        # Check zone uniqueness if name or zone changed
        new_name = update_data.get("office_name", office.office_name)
        new_zone = update_data.get("zone", office.zone)
        if "office_name" in update_data or "zone" in update_data:
            await HubRegistrarOfficeService._check_zone_unique(
                session, new_name, new_zone, exclude_id=office.id
            )
        for field, value in update_data.items():
            setattr(office, field, value)
        await session.commit()
        await session.refresh(office)
        return office

    @staticmethod
    async def toggle_active(
        session: AsyncSession,
        office: HubRegistrarOffice,
        is_active: bool,
    ) -> HubRegistrarOffice:
        """Toggle active status."""
        office.is_active = is_active
        await session.commit()
        await session.refresh(office)
        return office

    @staticmethod
    async def soft_delete(
        session: AsyncSession,
        office: HubRegistrarOffice,
        deleted_by: UUID,
    ) -> HubRegistrarOffice:
        """Soft-delete an office."""
        office.is_deleted = True
        office.deleted_by = deleted_by
        await session.commit()
        await session.refresh(office)
        return office
