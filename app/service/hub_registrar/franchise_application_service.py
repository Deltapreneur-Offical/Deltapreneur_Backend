"""Franchise Application service — business logic."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.hub_registrar.franchise_application_entity import (
    FranchiseApplication,
)
from app.model.hub_registrar.franchise_application_request import (
    FranchiseApplicationSubmitRequest,
)


class FranchiseApplicationService:
    """Service for Franchise Application CRUD operations."""

    @staticmethod
    async def submit_application(
        session: AsyncSession, data: FranchiseApplicationSubmitRequest
    ) -> FranchiseApplication:
        """Submit a new franchise application. Checks blacklist first."""
        # Check if applicant is blacklisted
        stmt = select(FranchiseApplication).where(
            FranchiseApplication.is_blacklisted == True,
            FranchiseApplication.is_deleted == False,
            or_(
                FranchiseApplication.email == data.email,
                FranchiseApplication.mobile_number == data.mobile_number,
            ),
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            raise ValueError(
                "This applicant has been blacklisted and cannot submit a new application."
            )

        application = FranchiseApplication(
            full_name=data.full_name,
            mobile_number=data.mobile_number,
            email=data.email,
            city=data.city,
            state=data.state,
            full_address=data.full_address,
            existing_business_name=data.existing_business_name,
            business_type=data.business_type,
            preferred_location=data.preferred_location,
            existing_office_availability=data.existing_office_availability,
            relevant_experience=data.relevant_experience,
            reason_for_applying=data.reason_for_applying,
            additional_information=data.additional_information,
            map_url=data.map_url,
            status="PENDING",
            is_blacklisted=False,
        )
        session.add(application)
        await session.commit()
        await session.refresh(application)
        return application

    @staticmethod
    async def get_all_applications(
        session: AsyncSession,
        status: Optional[str] = None,
        search: Optional[str] = None,
        blacklisted_only: bool = False,
    ) -> List[FranchiseApplication]:
        """Get all applications for admin with optional filters."""
        stmt = select(FranchiseApplication).where(
            FranchiseApplication.is_deleted == False
        )
        if blacklisted_only:
            stmt = stmt.where(FranchiseApplication.is_blacklisted == True)
        else:
            stmt = stmt.where(FranchiseApplication.is_blacklisted == False)
        if status:
            stmt = stmt.where(FranchiseApplication.status == status)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(
                or_(
                    FranchiseApplication.full_name.ilike(like),
                    FranchiseApplication.mobile_number.ilike(like),
                    FranchiseApplication.email.ilike(like),
                )
            )
        stmt = stmt.order_by(FranchiseApplication.created_at.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_application_by_id(
        session: AsyncSession, app_id: UUID
    ) -> Optional[FranchiseApplication]:
        """Get a single application by ID."""
        stmt = select(FranchiseApplication).where(
            FranchiseApplication.id == app_id,
            FranchiseApplication.is_deleted == False,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def update_status(
        session: AsyncSession,
        application: FranchiseApplication,
        status: str,
        blacklist_reason: Optional[str] = None,
    ) -> FranchiseApplication:
        """Update application status."""
        application.status = status
        if blacklist_reason:
            application.blacklist_reason = blacklist_reason
        await session.commit()
        await session.refresh(application)
        return application

    @staticmethod
    async def blacklist_applicant(
        session: AsyncSession,
        application: FranchiseApplication,
        reason: str,
    ) -> FranchiseApplication:
        """Mark an applicant as blacklisted."""
        application.is_blacklisted = True
        application.blacklist_reason = reason
        application.status = "REJECTED"
        await session.commit()
        await session.refresh(application)
        return application

    @staticmethod
    async def delete_application(
        session: AsyncSession,
        application: FranchiseApplication,
    ) -> None:
        """Permanently delete an application."""
        await session.delete(application)
        await session.commit()
