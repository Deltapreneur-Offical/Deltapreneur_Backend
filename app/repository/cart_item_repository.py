"""Cart item data access."""

from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.cart.cart_item_entity import CartItem
from app.utils.cart_enums import CartProductType


class CartItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, item: CartItem) -> CartItem:
        self._session.add(item)
        await self._session.flush()
        await self._session.refresh(item)
        return item

    async def save(self, item: CartItem) -> CartItem:
        await self._session.flush()
        await self._session.refresh(item)
        return item

    async def get_by_id(self, item_id: uuid.UUID) -> Optional[CartItem]:
        stmt = select(CartItem).where(CartItem.id == item_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_user(self, user_id: uuid.UUID) -> Sequence[CartItem]:
        stmt = (
            select(CartItem)
            .where(CartItem.user_id == user_id)
            .order_by(CartItem.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_by_user_for_update(self, user_id: uuid.UUID) -> Sequence[CartItem]:
        """Lock the buyer's cart rows for the duration of the current transaction."""
        stmt = (
            select(CartItem)
            .where(CartItem.user_id == user_id)
            .order_by(CartItem.created_at.asc())
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_by_user_and_product(
        self,
        user_id: uuid.UUID,
        product_type: CartProductType,
        product_id: uuid.UUID,
    ) -> Optional[CartItem]:
        stmt = select(CartItem).where(
            CartItem.user_id == user_id,
            CartItem.product_type == product_type,
            CartItem.product_id == product_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_by_id(self, item_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        stmt = (
            delete(CartItem)
            .where(CartItem.id == item_id, CartItem.user_id == user_id)
        )
        result = await self._session.execute(stmt)
        return result.rowcount > 0

    async def clear_user_cart(self, user_id: uuid.UUID) -> int:
        stmt = delete(CartItem).where(CartItem.user_id == user_id)
        result = await self._session.execute(stmt)
        return result.rowcount

    async def count_by_user(self, user_id: uuid.UUID) -> int:
        from sqlalchemy import func

        stmt = select(func.count(CartItem.id)).where(CartItem.user_id == user_id)
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def delete_items_by_ids(
        self, item_ids: list[uuid.UUID], user_id: uuid.UUID
    ) -> int:
        if not item_ids:
            return 0
        stmt = (
            delete(CartItem)
            .where(CartItem.id.in_(item_ids), CartItem.user_id == user_id)
        )
        result = await self._session.execute(stmt)
        return result.rowcount
