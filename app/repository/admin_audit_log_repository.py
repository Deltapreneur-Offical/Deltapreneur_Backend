"""Repository for AdminAuditLog."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.platform.admin_audit_log import AdminAuditLog


class AdminAuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, log: AdminAuditLog) -> AdminAuditLog:
        self._session.add(log)
        await self._session.flush()
        return log

    async def list_by_admin(self, admin_id: uuid.UUID) -> Sequence[AdminAuditLog]:
        result = await self._session.execute(
            select(AdminAuditLog)
            .where(AdminAuditLog.admin_id == admin_id)
            .order_by(AdminAuditLog.created_at.desc())
        )
        return result.scalars().all()
