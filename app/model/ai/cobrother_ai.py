from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


AiMode = Literal["marketplace", "naming", "broker", "brand", "auction", "founder"]


class PageContext(BaseModel):
    current_route: str | None = Field(None, max_length=512)
    transaction_id: uuid.UUID | None = None
    domain_fqdn: str | None = Field(None, max_length=255)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=6000)
    mode: AiMode = "marketplace"
    conversation_id: uuid.UUID | None = None
    regenerate_message_id: uuid.UUID | None = None
    voice: bool = False
    page_context: PageContext | None = None


class RenameChatRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=160)


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    mode: str
    created_at: datetime
    metadata_json: dict[str, Any] | None = None


class ChatSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    mode: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessageResponse] = []


class FavoriteRequest(BaseModel):
    asset_type: Literal["domain", "venture", "auction", "creator", "software"]
    asset_id: uuid.UUID
    label: str | None = Field(None, max_length=255)
    notes: str | None = Field(None, max_length=2000)


class FavoriteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_type: str
    asset_id: uuid.UUID
    label: str | None = None
    notes: str | None = None
    created_at: datetime


class UserPreferenceRequest(BaseModel):
    favorite_categories: list[str] | None = None
    naming_preferences: dict[str, Any] | None = None
    venture_interests: list[str] | None = None
    domain_interests: list[str] | None = None
    voice_enabled: bool | None = None


class UserPreferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    favorite_categories: list[str] | None = None
    naming_preferences: dict[str, Any] | None = None
    venture_interests: list[str] | None = None
    domain_interests: list[str] | None = None
    voice_enabled: bool
