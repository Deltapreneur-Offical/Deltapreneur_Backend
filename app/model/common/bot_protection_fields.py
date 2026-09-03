from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class BotProtectionFields(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    turnstile_token: Optional[str] = Field(None, alias="turnstileToken")
    website: Optional[str] = Field(None, description="Honeypot — must stay empty")
