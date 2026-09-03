"""Request body for POST /api/v1/meetings/auction/{auctionId}."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class MeetingScheduleRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    scheduled_at: datetime = Field(..., alias="scheduledAt")
    topic: Optional[str] = None
    message: Optional[str] = None
    duration_minutes: Optional[int] = Field(None, alias="durationMinutes")
