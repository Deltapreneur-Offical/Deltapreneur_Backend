"""Unified buyer managed acquisitions (Marketplace + OpenProvider)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entity.cobranding.domain_enquiry_entity import DomainEnquiry
from app.repository.openprovider_managed_acquisition_repository import (
    OpenProviderManagedAcquisitionRepository,
)
from app.service.domain.managed_acquisition_serializers import (
    buyer_facing_acquisition,
    serialize_marketplace_enquiry_as_acquisition,
    serialize_op_managed_acquisition,
)

logger = logging.getLogger(__name__)


class ManagedAcquisitionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._op = OpenProviderManagedAcquisitionRepository(session)

    async def list_mine(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        try:
            op_rows = await self._op.list_by_user(user_id)
        except Exception:
            logger.exception("managed_acquisitions.list_mine.op_failed user=%s", user_id)
            op_rows = []

        for row in op_rows:
            try:
                items.append(buyer_facing_acquisition(serialize_op_managed_acquisition(row)))
            except Exception:
                logger.exception(
                    "managed_acquisitions.serialize_op_failed id=%s",
                    getattr(row, "id", None),
                )

        try:
            stmt = (
                select(DomainEnquiry)
                .options(selectinload(DomainEnquiry.domain_listing))
                .where(
                    DomainEnquiry.enquirer_user_id == user_id,
                    or_(
                        DomainEnquiry.is_deleted.is_(False),
                        DomainEnquiry.is_deleted.is_(None),
                    ),
                )
                .order_by(DomainEnquiry.created_at.desc())
            )
            enquiry_rows = (await self._session.execute(stmt)).scalars().all()
        except Exception:
            logger.exception(
                "managed_acquisitions.list_mine.enquiries_failed user=%s", user_id
            )
            enquiry_rows = []

        for enquiry in enquiry_rows:
            try:
                dto = serialize_marketplace_enquiry_as_acquisition(enquiry)
                if dto is not None:
                    items.append(buyer_facing_acquisition(dto))
            except Exception:
                logger.exception(
                    "managed_acquisitions.serialize_enquiry_failed id=%s",
                    getattr(enquiry, "id", None),
                )

        items.sort(key=lambda x: x.get("createdAt") or "", reverse=True)
        return items
