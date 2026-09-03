from pydantic import BaseModel, Field


class RefreshTokenRequest(BaseModel):

    refreshToken: str = Field(
        default="",
        description="Optional when refresh_token HttpOnly cookie is set",
    )
