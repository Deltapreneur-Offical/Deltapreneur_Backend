"""Repository for OpenProvider showcase domains.

All filtering/sorting/pagination is performed at the SQL level so the admin
candidate list stays fast and NEVER triggers OpenProvider API calls. OpenProvider
is only ever called by the controlled generation/refresh process.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional, Sequence

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.domain.openprovider_showcase_entity import OpenProviderShowcaseDomain

# Matches the existing managed-acquisition payable gate (strictly greater than 5L).
MANAGED_GATE_INR = 500_000.0


class ShowcaseDomainRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _not_deleted():
        return or_(
            OpenProviderShowcaseDomain.is_deleted.is_(False),
            OpenProviderShowcaseDomain.is_deleted.is_(None),
        )

    # ------------------------------------------------------------------ writes

    async def create(
        self, row: OpenProviderShowcaseDomain
    ) -> OpenProviderShowcaseDomain:
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def save(
        self, row: OpenProviderShowcaseDomain
    ) -> OpenProviderShowcaseDomain:
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def upsert_by_domain_name(
        self, row: OpenProviderShowcaseDomain
    ) -> OpenProviderShowcaseDomain:
        """Insert a candidate, or REVIVE a soft-deleted row with the same name.

        Used by the generator so concurrent/repeated scans can never create
        duplicate rows (unique constraint on domain_name is the backstop). A
        soft-deleted row still occupies the unique key, so instead of skipping
        silently (which would make a deleted domain impossible to re-discover
        and inflate the generator's "found" count), the conflict is resolved by
        restoring the row (is_deleted=False, deleted_at=None) with the fresh
        candidate data. The DO UPDATE is scoped to deleted rows only, so an
        existing live row (e.g. already selected) is never overwritten.
        """
        stmt = (
            pg_insert(OpenProviderShowcaseDomain)
            .values(
                id=row.id,
                domain_name=row.domain_name,
                label=row.label,
                tld=row.tld,
                is_premium=row.is_premium,
                source=row.source,
                create_price_inr=row.create_price_inr,
                renewal_price_inr=row.renewal_price_inr,
                payable_inr=row.payable_inr,
                price_snapshot_json=row.price_snapshot_json,
                available=row.available,
                last_checked_at=row.last_checked_at,
                is_selected=row.is_selected,
                display_order=row.display_order,
            )
            .on_conflict_do_update(
                index_elements=["domain_name"],
                where=OpenProviderShowcaseDomain.is_deleted.is_(True),
                set_={
                    "label": row.label,
                    "tld": row.tld,
                    "is_premium": row.is_premium,
                    "source": row.source,
                    "create_price_inr": row.create_price_inr,
                    "renewal_price_inr": row.renewal_price_inr,
                    "payable_inr": row.payable_inr,
                    "price_snapshot_json": row.price_snapshot_json,
                    "available": row.available,
                    "last_checked_at": row.last_checked_at,
                    "is_selected": row.is_selected,
                    "display_order": row.display_order,
                    "is_deleted": False,
                    "deleted_at": None,
                },
            )
            .returning(OpenProviderShowcaseDomain.id)
        )
        result = await self._session.execute(stmt)
        existing_id = result.scalar_one_or_none()
        if existing_id is not None:
            return row
        return await self.get_by_domain_name(row.domain_name)

    async def soft_delete_by_id(self, row_id: uuid.UUID) -> bool:
        row = await self.get_by_id(row_id)
        if row is None:
            return False
        row.is_deleted = True
        row.deleted_at = datetime.now()
        await self._session.flush()
        return True

    # ------------------------------------------------------------------ reads

    async def get_by_id(
        self, row_id: uuid.UUID
    ) -> Optional[OpenProviderShowcaseDomain]:
        stmt = select(OpenProviderShowcaseDomain).where(
            OpenProviderShowcaseDomain.id == row_id,
            self._not_deleted(),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_domain_name(
        self, domain_name: str
    ) -> Optional[OpenProviderShowcaseDomain]:
        stmt = select(OpenProviderShowcaseDomain).where(
            OpenProviderShowcaseDomain.domain_name == domain_name.lower().strip(),
            self._not_deleted(),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_selected(self) -> Sequence[OpenProviderShowcaseDomain]:
        """Public feed source: only selected, not-deleted, available rows."""
        stmt = (
            select(OpenProviderShowcaseDomain)
            .where(
                OpenProviderShowcaseDomain.is_selected.is_(True),
                OpenProviderShowcaseDomain.available.is_(True),
                self._not_deleted(),
            )
            .order_by(
                OpenProviderShowcaseDomain.display_order.asc(),
                OpenProviderShowcaseDomain.domain_name.asc(),
            )
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def list_selected_for_refresh(
        self,
    ) -> Sequence[OpenProviderShowcaseDomain]:
        """Refresh source: selected + not-deleted rows REGARDLESS of availability.

        Revalidation must re-check every admin-approved domain — including ones
        currently hidden (``available=False``) — so a transient provider/API
        failure can never permanently strand a selected domain in the hidden
        state. Availability is a live status, not a filter here; the public
        feed (``list_selected``) remains the only strict selected+available
        query.
        """
        stmt = (
            select(OpenProviderShowcaseDomain)
            .where(
                OpenProviderShowcaseDomain.is_selected.is_(True),
                self._not_deleted(),
            )
            .order_by(
                OpenProviderShowcaseDomain.display_order.asc(),
                OpenProviderShowcaseDomain.domain_name.asc(),
            )
        )
        return (await self._session.execute(stmt)).scalars().all()

    # ------------------------------------------------------- filter + paginate

    @staticmethod
    def _apply_filters(
        stmt: Select, filters: dict[str, Any] | None
    ) -> Select:
        f = filters or {}
        conds = []

        search = (f.get("search") or "").strip().lower()
        if search:
            conds.append(
                OpenProviderShowcaseDomain.domain_name.ilike(f"%{search}%")
            )

        tlds = f.get("tlds") or []
        if tlds:
            conds.append(
                OpenProviderShowcaseDomain.tld.in_(
                    [str(t).lstrip(".").lower() for t in tlds]
                )
            )

        price_min = f.get("price_min")
        if price_min is not None:
            conds.append(OpenProviderShowcaseDomain.create_price_inr >= float(price_min))
        price_max = f.get("price_max")
        if price_max is not None:
            conds.append(OpenProviderShowcaseDomain.create_price_inr <= float(price_max))

        if f.get("under_5l"):
            conds.append(
                or_(
                    OpenProviderShowcaseDomain.payable_inr.is_(None),
                    OpenProviderShowcaseDomain.payable_inr <= MANAGED_GATE_INR,
                )
            )
        if f.get("over_5l"):
            conds.append(OpenProviderShowcaseDomain.payable_inr > MANAGED_GATE_INR)

        if f.get("available") is not None:
            conds.append(OpenProviderShowcaseDomain.available.is_(bool(f["available"])))
        if f.get("is_selected") is not None:
            conds.append(
                OpenProviderShowcaseDomain.is_selected.is_(bool(f["is_selected"]))
            )
        if f.get("premium_only"):
            conds.append(OpenProviderShowcaseDomain.is_premium.is_(True))

        generated_since = f.get("generated_since")
        if generated_since is not None:
            conds.append(OpenProviderShowcaseDomain.created_at >= generated_since)
        checked_since = f.get("checked_since")
        if checked_since is not None:
            conds.append(OpenProviderShowcaseDomain.last_checked_at >= checked_since)

        length_min = f.get("length_min")
        if length_min is not None:
            conds.append(
                func.char_length(OpenProviderShowcaseDomain.domain_name) >= int(length_min)
            )
        length_max = f.get("length_max")
        if length_max is not None:
            conds.append(
                func.char_length(OpenProviderShowcaseDomain.domain_name) <= int(length_max)
            )

        if f.get("with_numbers"):
            conds.append(OpenProviderShowcaseDomain.domain_name.op("~")("[0-9]"))
        if f.get("with_hyphen"):
            conds.append(OpenProviderShowcaseDomain.domain_name.like("%-%"))

        if conds:
            stmt = stmt.where(and_(*conds))
        return stmt

    @staticmethod
    def _apply_sort(stmt: Select, sort: str | None) -> Select:
        col = OpenProviderShowcaseDomain
        sort = (sort or "newest").strip().lower()
        if sort == "price_asc":
            return stmt.order_by(col.create_price_inr.asc().nulls_last())
        if sort == "price_desc":
            return stmt.order_by(col.create_price_inr.desc().nulls_last())
        if sort == "oldest":
            return stmt.order_by(col.created_at.asc())
        if sort == "alphabetical":
            return stmt.order_by(col.domain_name.asc())
        # default: newest
        return stmt.order_by(col.created_at.desc())

    async def list_rows(
        self,
        *,
        filters: dict[str, Any] | None = None,
        sort: str | None = "newest",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[Sequence[OpenProviderShowcaseDomain], int]:
        """Paginated, SQL-filtered listing for the admin candidate list."""
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 200))

        base = select(OpenProviderShowcaseDomain).where(self._not_deleted())
        base = self._apply_filters(base, filters)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = int((await self._session.execute(count_stmt)).scalar_one())

        stmt = self._apply_sort(base, sort)
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(stmt)).scalars().all()
        return rows, total
