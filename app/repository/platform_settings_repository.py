"""Platform settings persistence."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.platform.platform_setting_entity import PlatformSetting


class PlatformSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str) -> str | None:
        from sqlalchemy.exc import ProgrammingError, OperationalError
        import logging
        try:
            stmt = select(PlatformSetting).where(PlatformSetting.setting_key == key)
            result = await self._session.execute(stmt)
            row = result.scalar_one_or_none()
            return row.setting_value if row else None
        except (ProgrammingError, OperationalError) as e:
            logging.getLogger(__name__).warning("Failed to fetch platform setting '%s': %s", key, e)
            return None

    async def insert_if_absent(self, key: str, value: str) -> None:
        """Insert a row ONLY when the key does not exist (never overwrites).

        Used to seed the showcase_config row with defaults before the
        generation-lock UPDATE, so the claim can never be lost to a missing
        row. ``ON CONFLICT DO NOTHING`` keeps any already-saved config intact.
        """
        from datetime import datetime, timezone

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = (
            pg_insert(PlatformSetting)
            .values(
                setting_key=key,
                setting_value=value,
                updated_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(index_elements=["setting_key"])
        )
        await self._session.execute(stmt)

    async def set(self, key: str, value: str) -> PlatformSetting:
        stmt = select(PlatformSetting).where(PlatformSetting.setting_key == key)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if row is None:
            row = PlatformSetting(setting_key=key, setting_value=value, updated_at=now)
            self._session.add(row)
        else:
            row.setting_value = value
            row.updated_at = now
        await self._session.flush()
        return row
