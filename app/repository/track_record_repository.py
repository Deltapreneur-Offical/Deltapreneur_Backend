"""Repository for TrackRecord queries and persistence."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Sequence, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.platform.track_record_entity import TrackRecord


async def _await_if_needed(value):
    if hasattr(value, "__await__"):
        return await value
    return value


class TrackRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, record: TrackRecord) -> TrackRecord:
        self._session.add(record)
        await self._session.flush()
        return record

    async def find_by_id(self, record_id: uuid.UUID) -> Optional[TrackRecord]:
        result = await self._session.execute(
            select(TrackRecord).where(TrackRecord.id == record_id)
        )
        return await _await_if_needed(result.scalar_one_or_none())

    async def find_by_internal_order_id(self, internal_order_id: str) -> Optional[TrackRecord]:
        result = await self._session.execute(
            select(TrackRecord).where(TrackRecord.internal_order_id == internal_order_id)
        )
        return await _await_if_needed(result.scalar_one_or_none())

    async def find_by_razorpay_order_id(self, razorpay_order_id: str) -> Optional[TrackRecord]:
        result = await self._session.execute(
            select(TrackRecord).where(TrackRecord.razorpay_order_id == razorpay_order_id)
        )
        return await _await_if_needed(result.scalars().first())

    async def find_by_razorpay_payment_id(self, razorpay_payment_id: str) -> Optional[TrackRecord]:
        result = await self._session.execute(
            select(TrackRecord).where(TrackRecord.razorpay_payment_id == razorpay_payment_id)
        )
        return await _await_if_needed(result.scalars().first())

    async def find_all_by_razorpay_payment_id(self, razorpay_payment_id: str) -> Sequence[TrackRecord]:
        """All records sharing a Razorpay payment id.

        One payment can cover multiple line items (multi-domain carts, domain +
        technology, …) so callers must resolve the matching line, never just
        ``.first()`` — that is how duplicate/misattributed records were born.
        """
        result = await self._session.execute(
            select(TrackRecord).where(TrackRecord.razorpay_payment_id == razorpay_payment_id)
        )
        return await _await_if_needed(result.scalars().all())

    async def query_records(
        self,
        *,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        category: Optional[str] = None,
        overall_status: Optional[str] = None,
        search_term: Optional[str] = None,
        sort_by: str = "timestamp",
        sort_dir: str = "desc",
        page: int = 1,
        limit: int = 20,
    ) -> Tuple[Sequence[TrackRecord], int]:
        conditions = []

        if start_date:
            conditions.append(TrackRecord.created_at >= start_date)
        if end_date:
            conditions.append(TrackRecord.created_at <= end_date)
        if category and category.strip() and category.lower() != "all":
            cat_clean = category.strip()
            cat_lower = cat_clean.lower()
            if cat_lower in ("openprovider", "domain registration (openprovider)"):
                conditions.append(
                    or_(
                        TrackRecord.category.ilike("%openprovider%"),
                        TrackRecord.provider_subcategory.ilike("%openprovider%"),
                    )
                )
            elif cat_lower in ("reseller", "domain registration (reseller)"):
                conditions.append(
                    or_(
                        TrackRecord.category.ilike("%reseller%"),
                        TrackRecord.provider_subcategory.ilike("%reseller%"),
                    )
                )
            else:
                conditions.append(
                    or_(
                        TrackRecord.category.ilike(f"%{cat_clean}%"),
                        TrackRecord.provider_subcategory.ilike(f"%{cat_clean}%"),
                    )
                )
        if overall_status and overall_status.strip() and overall_status.lower() != "all":
            st_clean = overall_status.strip()
            from sqlalchemy import cast, String
            conditions.append(cast(TrackRecord.overall_status, String).ilike(f"%{st_clean}%"))

        if search_term and search_term.strip():
            pattern = f"%{search_term.strip()}%"
            conditions.append(
                or_(
                    TrackRecord.buyer_name.ilike(pattern),
                    TrackRecord.buyer_email.ilike(pattern),
                    TrackRecord.buyer_phone.ilike(pattern),
                    TrackRecord.item_name.ilike(pattern),
                    TrackRecord.razorpay_payment_id.ilike(pattern),
                    TrackRecord.razorpay_order_id.ilike(pattern),
                    TrackRecord.internal_order_id.ilike(pattern),
                    TrackRecord.cart_batch_id.ilike(pattern),
                )
            )

        # Count total matching rows
        count_stmt = select(func.count(TrackRecord.id))
        if conditions:
            count_stmt = count_stmt.where(*conditions)
        total_res = await self._session.execute(count_stmt)
        total_count = total_res.scalar_one() or 0

        # Sorting
        is_asc = sort_dir.lower() == "asc"
        if sort_by == "amount":
            col = TrackRecord.amount_charged
        elif sort_by == "buyer_name":
            col = TrackRecord.buyer_name
        elif sort_by == "category":
            col = TrackRecord.category
        elif sort_by == "status":
            col = TrackRecord.overall_status
        elif sort_by == "updated":
            col = TrackRecord.updated_at
        else:
            col = TrackRecord.created_at

        stmt = select(TrackRecord)
        if conditions:
            stmt = stmt.where(*conditions)
        stmt = stmt.order_by(col.asc() if is_asc else col.desc())

        # Pagination
        offset = (max(1, page) - 1) * limit
        stmt = stmt.offset(offset).limit(limit)

        result = await self._session.execute(stmt)
        records = result.scalars().all()

        return records, total_count
