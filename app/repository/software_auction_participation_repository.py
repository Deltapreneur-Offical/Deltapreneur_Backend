"""Software auction participation fee records."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.cocreation.software_auction_participation_entity import (
    SoftwareAuctionParticipation,
    SoftwareAuctionParticipationStatus,
)


class SoftwareAuctionParticipationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        row: SoftwareAuctionParticipation,
    ) -> SoftwareAuctionParticipation:
        try:
            self._session.add(row)
            await self._session.flush()
            await self._session.refresh(row)
            return row
        except ProgrammingError as exc:
            if _is_missing_participation_table_error(exc):
                raise AppException(
                    "Participation fee setup is incomplete. Run database migrations (alembic upgrade head).",
                    status_code=503,
                ) from None
            raise

    async def save(
        self,
        row: SoftwareAuctionParticipation,
    ) -> SoftwareAuctionParticipation:
        try:
            await self._session.flush()
            await self._session.refresh(row)
            return row
        except ProgrammingError as exc:
            if _is_missing_participation_table_error(exc):
                raise AppException(
                    "Participation fee setup is incomplete. Run database migrations (alembic upgrade head).",
                    status_code=503,
                ) from None
            raise

    async def get_by_auction_and_user(
        self,
        auction_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Optional[SoftwareAuctionParticipation]:
        stmt = select(SoftwareAuctionParticipation).where(
            SoftwareAuctionParticipation.software_auction_id == auction_id,
            SoftwareAuctionParticipation.user_id == user_id,
        )
        try:
            result = await self._session.execute(stmt)
            return result.scalar_one_or_none()
        except ProgrammingError as exc:
            if _is_missing_participation_table_error(exc):
                raise AppException(
                    "Participation fee setup is incomplete. Run database migrations (alembic upgrade head).",
                    status_code=503,
                ) from None
            raise

    async def get_by_order_id(
        self,
        order_id: str,
    ) -> Optional[SoftwareAuctionParticipation]:
        stmt = select(SoftwareAuctionParticipation).where(
            SoftwareAuctionParticipation.razorpay_order_id == order_id,
        )
        try:
            result = await self._session.execute(stmt)
            return result.scalar_one_or_none()
        except ProgrammingError as exc:
            if _is_missing_participation_table_error(exc):
                raise AppException(
                    "Participation fee setup is incomplete. Run database migrations (alembic upgrade head).",
                    status_code=503,
                ) from None
            raise

    async def has_completed(
        self,
        auction_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        row = await self.get_by_auction_and_user(auction_id, user_id)
        return row is not None and row.status == SoftwareAuctionParticipationStatus.COMPLETED


def _is_missing_participation_table_error(exc: ProgrammingError) -> bool:
    text = str(getattr(exc, "orig", exc)).lower()
    return (
        "software_auction_participations" in text
        and ("does not exist" in text or "undefinedtableerror" in text)
    )
