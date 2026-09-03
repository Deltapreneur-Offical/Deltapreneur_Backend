from typing import Optional

from pydantic import ConfigDict, EmailStr, Field

from app.model.common.bot_protection_fields import BotProtectionFields


class BeCoBrother(BotProtectionFields):
    model_config = ConfigDict(populate_by_name=True)

    fullName: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    phoneNumber: Optional[str] = Field(None, max_length=20)
    pinCode: Optional[str] = Field(None, max_length=50)
    skill: Optional[str] = Field(None, max_length=100)
    equipment: bool = False
    message: Optional[str] = Field(None, max_length=2000)
