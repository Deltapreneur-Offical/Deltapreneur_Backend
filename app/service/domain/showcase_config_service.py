"""Showcase configuration, persisted as JSON in the existing platform_settings table.

Stored under a single key (``showcase_config``) as a JSON string. The
platform_settings table is key-value per row, so writing this key never
conflicts with other features' settings. OpenProvider is never called here.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.platform.platform_setting_entity import PlatformSetting
from app.repository.platform_settings_repository import PlatformSettingsRepository

# If the generation lock has been held longer than this, assume the holder
# crashed and auto-release so the admin is not permanently blocked.
_STALE_LOCK_MAX_AGE = timedelta(minutes=30)

logger = logging.getLogger(__name__)

KEY_SHOWCASE_CONFIG = "showcase_config"

DEFAULT_SHOWCASE_CONFIG: dict[str, Any] = {
    "enabled": False,
    "seed_labels": [],
    # Empty = NO TLD restriction. Generation then discovers qualifying
    # Premium domains across the full OpenProvider catalog (priority TLDs
    # first, then bounded windows over the remaining catalog) instead of
    # silently limiting results to a tiny allow-list. An admin may still set
    # a list here to restrict discovery to specific TLDs.
    "allowed_tlds": [],
    "max_selected": 50,
    "refresh_interval_hours": 6,
    "last_refresh_at": None,
    "generation_lock": False,
    # Set while an admin asks Generate to stop; cleared when the lock is released.
    "cancel_generation_id": None,
}

_ALLOWED_KEYS = set(DEFAULT_SHOWCASE_CONFIG.keys())


class ShowcaseConfigService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = PlatformSettingsRepository(session)

    async def get(self) -> dict[str, Any]:
        raw = await self._repo.get(KEY_SHOWCASE_CONFIG)
        cfg: dict[str, Any] = {}
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    cfg = parsed
            except (TypeError, ValueError):
                logger.warning("showcase_config is not valid JSON; using defaults")
        # Merge over defaults so unknown/missing keys never crash callers.
        merged = dict(DEFAULT_SHOWCASE_CONFIG)
        merged.update(cfg)
        return merged

    async def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Validate + deep-merge a patch into the stored config."""
        if not isinstance(patch, dict):
            raise ValueError("Config patch must be an object.")

        unknown = set(patch.keys()) - _ALLOWED_KEYS
        if unknown:
            raise ValueError(f"Unknown showcase config keys: {sorted(unknown)}")

        validated: dict[str, Any] = {}
        if "enabled" in patch:
            validated["enabled"] = bool(patch["enabled"])
        if "seed_labels" in patch:
            labels = [str(x).strip().lower() for x in patch["seed_labels"] if str(x).strip()]
            if len(labels) > 500:
                raise ValueError("Too many seed labels (max 500).")
            validated["seed_labels"] = labels
        if "allowed_tlds" in patch:
            tlds = [
                str(x).lstrip(".").lower()
                for x in patch["allowed_tlds"]
                if str(x).strip()
            ]
            # Empty list = no TLD restriction (full-catalog discovery). This
            # is the new default; admins may still restrict via the UI.
            validated["allowed_tlds"] = tlds
        if "max_selected" in patch:
            max_selected = int(patch["max_selected"])
            if max_selected < 1 or max_selected > 200:
                raise ValueError("max_selected must be between 1 and 200.")
            validated["max_selected"] = max_selected
        if "refresh_interval_hours" in patch:
            hours = int(patch["refresh_interval_hours"])
            if hours < 1 or hours > 168:
                raise ValueError("refresh_interval_hours must be between 1 and 168.")
            validated["refresh_interval_hours"] = hours
        if "last_refresh_at" in patch:
            value = patch["last_refresh_at"]
            validated["last_refresh_at"] = value if value is None else str(value)
        if "cancel_generation_id" in patch:
            raw_id = patch["cancel_generation_id"]
            validated["cancel_generation_id"] = (
                str(raw_id).strip()[:64] if raw_id else None
            )

        current = await self.get()
        current.update(validated)
        await self._repo.set(KEY_SHOWCASE_CONFIG, json.dumps(current))
        await self._session.flush()
        return current

    # ------------------------------------------------------------------ locks

    async def claim_generation_lock(self) -> bool:
        """Atomically claim the generation lock (cross-process safe).

        Only one generator/refresh can run at a time, even with multiple
        uvicorn workers: the claim is a single UPDATE guarded by the current
        flag value. Returns True when this caller won the claim.

        The config row is seeded with defaults first (insert-if-absent) so a
        missing row can never cause the claim to match 0 rows and surface a
        misleading 409 before any settings have been saved.

        Fast-path read: a running generation commits its claim as soon as it
        wins, so a concurrent caller sees ``generation_lock=true`` here and
        returns False immediately — instead of blocking on the row lock held
        by the running transaction until it finishes (which previously made
        the second Generate stall for the entire generation duration before
        failing with 409).
        """
        await self._repo.insert_if_absent(
            KEY_SHOWCASE_CONFIG, json.dumps(DEFAULT_SHOWCASE_CONFIG)
        )
        try:
            current = await self.get()
        except Exception:
            current = {}
        if current.get("generation_lock"):
            # Auto-release stale locks (e.g. server crashed mid-generation).
            updated_at = current.get("updated_at")
            if updated_at:
                try:
                    if isinstance(updated_at, str):
                        updated_at = datetime.fromisoformat(updated_at)
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) - updated_at > _STALE_LOCK_MAX_AGE:
                        logger.warning("showcase.lock.stale_auto_release age=%s", datetime.now(timezone.utc) - updated_at)
                        await self.release_generation_lock()
                        # Re-check after release
                        current = await self.get()
                        if current.get("generation_lock"):
                            return False
                except Exception:
                    logger.exception("showcase.lock.stale_check_failed")
                    return False
            else:
                return False
        if current.get("generation_lock"):
            return False
        now = datetime.now(timezone.utc)
        stmt = (
            update(PlatformSetting)
            .where(
                PlatformSetting.setting_key == KEY_SHOWCASE_CONFIG,
                # The OR must stay grouped INSIDE the AND: without these outer
                # parens, AND binds tighter than OR and the condition matches
                # every row whose JSON lacks a 'generation_lock' key, so the
                # jsonb_set SET clause runs on unrelated scalar rows.
                text(
                    "((setting_value::jsonb->>'generation_lock')::boolean = false "
                    "OR setting_value::jsonb->>'generation_lock' IS NULL)"
                ),
            )
            .values(
                setting_value=text(
                    "jsonb_set(setting_value::jsonb, '{generation_lock}', 'true')::text"
                ),
                updated_at=now,
            )
        )
        result = await self._session.execute(stmt)
        return result.rowcount == 1

    async def release_generation_lock(self) -> None:
        """Clear the generation lock and COMMIT it.

        The claim is committed by the caller's main commit, but this release
        runs after that commit — without an explicit commit here the release
        UPDATE is rolled back on session close, leaving the lock stuck forever
        and every later Generate/Refresh returning a false 409.
        """
        now = datetime.now(timezone.utc)
        stmt = (
            update(PlatformSetting)
            .where(PlatformSetting.setting_key == KEY_SHOWCASE_CONFIG)
            .values(
                setting_value=text(
                    "jsonb_set("
                    "jsonb_set(setting_value::jsonb, '{generation_lock}', 'false'), "
                    "'{cancel_generation_id}', 'null'"
                    ")::text"
                ),
                updated_at=now,
            )
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def request_cancel(self, generation_id: str) -> bool:
        """Ask the in-flight Generate to stop at the next label/chunk.

        Cross-worker: stored on showcase_config so the worker running OpenProvider
        sees it even if Cancel hit a different process. Persist even when
        ``generation_lock`` is not yet true so a Cancel that arrives before the
        lock commit still stops the run. Does not drop candidates already
        written. Returns False only when the id is empty.
        """
        gid = (generation_id or "").strip()
        if not gid:
            return False
        await self.update({"cancel_generation_id": gid})
        await self._session.commit()
        return True

    async def is_cancel_requested(self, generation_id: str) -> bool:
        gid = (generation_id or "").strip()
        if not gid:
            return False
        current = await self.get()
        return (current.get("cancel_generation_id") or "") == gid
