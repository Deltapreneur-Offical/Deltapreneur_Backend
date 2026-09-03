from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entity.ai.cobrother_ai import (
    AiAnalyticsEvent,
    ChatMessage,
    ChatSession,
    Favorite,
    UserPreference,
)
from app.entity.user.app_user import AppUser
from app.model.ai.cobrother_ai import FavoriteRequest, UserPreferenceRequest


class ChatPersistenceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_session(
        self,
        *,
        user: AppUser | None,
        conversation_id: uuid.UUID | None,
        mode: str,
        first_message: str,
    ) -> ChatSession:
        if conversation_id:
            stmt = select(ChatSession).options(selectinload(ChatSession.messages)).where(
                ChatSession.id == conversation_id,
                ChatSession.is_deleted.is_(False),
            )
            if user is not None:
                stmt = stmt.where(ChatSession.user_id == user.id)
            session = (await self.db.execute(stmt)).scalars().unique().one_or_none()
            if session is not None:
                return session

        session = ChatSession(
            user_id=user.id if user else None,
            title=self.generate_title(first_message),
            mode=mode,
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def add_message(
        self,
        session: ChatSession,
        *,
        role: str,
        content: str,
        mode: str,
        context_snapshot: dict[str, Any] | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> ChatMessage:
        message = ChatMessage(
            session_id=session.id,
            role=role,
            content=content,
            mode=mode,
            context_snapshot=context_snapshot,
            metadata_json=metadata_json,
        )
        session.updated_at = datetime.now(timezone.utc)
        self.db.add(message)
        await self.db.flush()
        return message

    async def list_sessions(self, user: AppUser) -> list[ChatSession]:
        stmt = (
            select(ChatSession)
            .options(selectinload(ChatSession.messages))
            .where(ChatSession.user_id == user.id, ChatSession.is_deleted.is_(False))
            .order_by(desc(ChatSession.updated_at))
            .limit(50)
        )
        return list((await self.db.execute(stmt)).scalars().unique().all())

    async def recent_messages(self, session_id: uuid.UUID, limit: int = 10) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(desc(ChatMessage.created_at))
            .limit(limit)
        )
        rows = list((await self.db.execute(stmt)).scalars().all())
        return list(reversed(rows))

    async def rename_session(self, user: AppUser, session_id: uuid.UUID, title: str) -> ChatSession | None:
        session = await self._owned_session(user, session_id)
        if session is None:
            return None
        session.title = title.strip()
        await self.db.flush()
        return session

    async def delete_session(self, user: AppUser, session_id: uuid.UUID) -> bool:
        session = await self._owned_session(user, session_id)
        if session is None:
            return False
        session.is_deleted = True
        session.deleted_at = datetime.now(timezone.utc)
        session.deleted_by = user.id
        await self.db.flush()
        return True

    async def get_preferences(self, user: AppUser) -> UserPreference | None:
        stmt = select(UserPreference).where(UserPreference.user_id == user.id)
        return (await self.db.execute(stmt)).scalars().one_or_none()

    async def get_activity_summary(self, user: AppUser | None) -> dict[str, Any]:
        if user is None:
            return {}

        preferences = await self.get_preferences(user)
        favorites_stmt = (
            select(Favorite)
            .where(Favorite.user_id == user.id, Favorite.is_deleted.is_(False))
            .order_by(desc(Favorite.created_at))
            .limit(20)
        )
        events_stmt = (
            select(AiAnalyticsEvent)
            .where(AiAnalyticsEvent.user_id == user.id)
            .order_by(desc(AiAnalyticsEvent.created_at))
            .limit(30)
        )
        favorites = list((await self.db.execute(favorites_stmt)).scalars().all())
        events = list((await self.db.execute(events_stmt)).scalars().all())

        recent_queries = []
        for event in events:
            if event.query:
                recent_queries.append(event.query)
            if len(recent_queries) >= 8:
                break

        return {
            "favorite_categories": preferences.favorite_categories if preferences else [],
            "domain_interests": preferences.domain_interests if preferences else [],
            "venture_interests": preferences.venture_interests if preferences else [],
            "naming_preferences": preferences.naming_preferences if preferences else {},
            "voice_enabled": preferences.voice_enabled if preferences else False,
            "favorite_asset_types": [favorite.asset_type for favorite in favorites],
            "favorite_labels": [favorite.label for favorite in favorites if favorite.label],
            "recent_queries": recent_queries,
            "recent_event_types": [event.event_type for event in events[:12]],
        }

    async def upsert_preferences(self, user: AppUser, payload: UserPreferenceRequest) -> UserPreference:
        preferences = await self.get_preferences(user)
        if preferences is None:
            preferences = UserPreference(user_id=user.id, voice_enabled=False)
            self.db.add(preferences)
        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            setattr(preferences, key, value)
        await self.db.flush()
        return preferences

    async def save_favorite(self, user: AppUser, payload: FavoriteRequest) -> Favorite:
        stmt = select(Favorite).where(
            Favorite.user_id == user.id,
            Favorite.asset_type == payload.asset_type,
            Favorite.asset_id == payload.asset_id,
        )
        favorite = (await self.db.execute(stmt)).scalars().one_or_none()
        if favorite is None:
            favorite = Favorite(
                user_id=user.id,
                asset_type=payload.asset_type,
                asset_id=payload.asset_id,
            )
            self.db.add(favorite)
        favorite.is_deleted = False
        favorite.deleted_at = None
        favorite.label = payload.label
        favorite.notes = payload.notes
        await self.track(user, "saved_item", asset_type=payload.asset_type, asset_id=payload.asset_id)
        await self.db.flush()
        return favorite

    async def list_favorites(self, user: AppUser) -> list[Favorite]:
        stmt = (
            select(Favorite)
            .where(Favorite.user_id == user.id, Favorite.is_deleted.is_(False))
            .order_by(desc(Favorite.created_at))
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def delete_favorite(self, user: AppUser, favorite_id: uuid.UUID) -> bool:
        stmt = select(Favorite).where(
            Favorite.id == favorite_id,
            Favorite.user_id == user.id,
            Favorite.is_deleted.is_(False),
        )
        favorite = (await self.db.execute(stmt)).scalars().one_or_none()
        if favorite is None:
            return False
        favorite.is_deleted = True
        favorite.deleted_at = datetime.now(timezone.utc)
        favorite.deleted_by = user.id
        await self.db.flush()
        return True

    async def track(
        self,
        user: AppUser | None,
        event_type: str,
        *,
        mode: str | None = None,
        query: str | None = None,
        asset_type: str | None = None,
        asset_id: uuid.UUID | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> None:
        self.db.add(
            AiAnalyticsEvent(
                user_id=user.id if user else None,
                event_type=event_type,
                prompt=query[:4000] if query else None,
                input_mode="voice" if event_type == "voice_usage" else "text",
                assistant_mode=mode or "marketplace",
                categories=[],
                legacy_metadata=metadata_json or {},
                mode=mode,
                query=query[:4000] if query else None,
                asset_type=asset_type,
                asset_id=asset_id,
                metadata_json=metadata_json,
            )
        )
        await self.db.flush()

    def generate_title(self, message: str) -> str:
        cleaned = re.sub(r"\s+", " ", message).strip()
        words = [w for w in re.findall(r"[A-Za-z0-9.]+", cleaned) if len(w) > 1][:5]
        if not words:
            return "Marketplace Intelligence"
        title = " ".join(words).title()
        replacements = {"Ai": "AI", "Saas": "SaaS"}
        for old, new in replacements.items():
            title = title.replace(old, new)
        return title[:80]

    async def _owned_session(self, user: AppUser, session_id: uuid.UUID) -> ChatSession | None:
        stmt = select(ChatSession).options(selectinload(ChatSession.messages)).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
            ChatSession.is_deleted.is_(False),
        )
        return (await self.db.execute(stmt)).scalars().unique().one_or_none()
