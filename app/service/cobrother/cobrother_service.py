"""HubRegistrar request assignment and response workflows."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.cobrother.cobrother_request_entity import CoBrotherRequest
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.repository.cobrother_request_repository import CoBrotherRequestRepository
from app.utils.marketplace_enums import CoBrotherRequestStatus


class CoBrotherService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = CoBrotherRequestRepository(session)

    def _require_cobrother(self, user: AppUser) -> None:
        if user.role != UserRole.COBROTHER:
            raise AppException("HubRegistrar role required.", status_code=403)

    async def list_my_requests(self, cobrother: AppUser) -> list[CoBrotherRequest]:
        self._require_cobrother(cobrother)
        return list(await self._repo.list_by_assignee(cobrother.id))

    async def respond(
        self,
        request_id: uuid.UUID,
        *,
        accepted: bool,
        note: str,
        cobrother: AppUser,
    ) -> CoBrotherRequest:
        self._require_cobrother(cobrother)

        request = await self._repo.get_by_id(request_id)
        if request is None:
            raise AppException("Request not found.", status_code=404)

        if request.assigned_cobrother_id != cobrother.id:
            raise AppException("Not assigned to you.", status_code=403)

        request.status = (
            CoBrotherRequestStatus.ACCEPTED
            if accepted
            else CoBrotherRequestStatus.REJECTED
        )
        request.response_note = note
        request.updated_at = datetime.now(timezone.utc)

        if accepted:
            pending = await self._repo.list_pending_for_entity(request.entity_id)
            for other in pending:
                if other.id != request.id:
                    other.status = CoBrotherRequestStatus.CANCELLED
                    other.updated_at = datetime.now(timezone.utc)

        await self._repo.save(request)
        await self._session.commit()
        return request
