from typing import Optional

from pydantic import BaseModel, Field


class CommunityPostRequest(BaseModel):
    community_id: str

    title: str = Field(
        min_length=3,
        max_length=255,
    )

    content: str = Field(
        min_length=1,
        max_length=5000,
    )

    image_url: Optional[str] = Field(
        default=None,
        max_length=1000,
    )
