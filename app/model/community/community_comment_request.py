from pydantic import BaseModel, Field


class CommunityCommentRequest(BaseModel):
    content: str = Field(
        min_length=1,
        max_length=2000,
    )
