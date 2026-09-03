"""DomainService — CRUD for owned domain records (soft-delete only)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.auction.domain_entity import Domain
from app.entity.user.app_user import AppUser
from app.model.domain.domain_request import CreateDomainRequest, UpdateDomainRequest
from app.repository.domain_repository import DomainRepository


class DomainService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DomainRepository(session)

    async def create_domain(
        self,
        payload: CreateDomainRequest,
        *,
        owner: AppUser,
    ) -> Domain:
        name = payload.domain_name
        if await self._repo.exists_active_domain_name(name):
            raise AppException(
                "A domain with this name already exists.",
                status_code=409,
            )

        domain = Domain(
            owner_id=owner.id,
            domain_name=name,
            description=payload.description,
            is_verified=False,
        )
        domain = await self._repo.create(domain)
        await self._session.commit()
        await self._session.refresh(domain)
        return domain

    async def list_my_domains(
        self,
        *,
        owner: AppUser,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[int, list[Domain]]:
        offset = max(0, (page - 1) * page_size)
        total = await self._repo.count_by_owner(owner.id)
        items = list(
            await self._repo.list_by_owner(
                owner.id, offset=offset, limit=page_size
            )
        )
        return total, items

    async def get_domain(
        self,
        domain_id: uuid.UUID,
        *,
        actor: AppUser,
    ) -> Domain:
        d = await self._repo.get_by_id_for_owner(domain_id, actor.id)
        if d is None:
            raise AppException("Domain not found.", status_code=404)
        return d

    async def update_domain(
        self,
        domain_id: uuid.UUID,
        payload: UpdateDomainRequest,
        *,
        actor: AppUser,
    ) -> Domain:
        domain = await self._repo.get_by_id_for_owner(domain_id, actor.id)
        if domain is None:
            raise AppException("Domain not found.", status_code=404)

        if payload.domain_name is not None:
            if await self._repo.exists_active_domain_name(
                payload.domain_name,
                exclude_id=domain.id,
            ):
                raise AppException(
                    "A domain with this name already exists.",
                    status_code=409,
                )
            domain.domain_name = payload.domain_name

        if payload.description is not None:
            domain.description = payload.description

        domain.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        await self._session.commit()
        await self._session.refresh(domain)
        return domain

    async def soft_delete_domain(
        self,
        domain_id: uuid.UUID,
        *,
        actor: AppUser,
    ) -> None:
        domain = await self._repo.get_by_id_for_owner(domain_id, actor.id)
        if domain is None:
            raise AppException("Domain not found.", status_code=404)

        now = datetime.now(timezone.utc)
        domain.is_deleted = True
        domain.deleted_at = now
        domain.deleted_by = actor.id
        domain.updated_at = now
        await self._session.flush()
        await self._session.commit()
