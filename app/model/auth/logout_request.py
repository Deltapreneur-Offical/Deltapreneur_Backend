from pydantic import BaseModel, Field
from typing import Optional

class LogoutRequest(BaseModel):

    refreshToken: str = Field(
        default="",
        description="Optional when refresh_token HttpOnly cookie is set",
    )