from typing import Optional

from pydantic import ConfigDict, EmailStr, Field

from app.model.common.bot_protection_fields import BotProtectionFields


class VirtualAssistantApplicationRequest(BotProtectionFields):
    model_config = ConfigDict(populate_by_name=True)

    fullName: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    phoneNumber: Optional[str] = Field(None, max_length=32)
    location: Optional[str] = Field(None, max_length=200)
    isAdult: bool = False

    bio: Optional[str] = Field(None, max_length=1000)
    roles: list[str] = Field(default_factory=list, min_length=1, max_length=1)
    skills: Optional[str] = Field(None, max_length=500)
    yearsOfExperience: Optional[str] = Field(None, max_length=50)
    languages: Optional[str] = Field(None, max_length=300)
    linkedinUrl: Optional[str] = Field(None, max_length=500)
    portfolioUrl: Optional[str] = Field(None, max_length=500)

    availability: Optional[str] = Field(None, max_length=50)
    hoursPerWeek: Optional[str] = Field(None, max_length=50)
    expectedCompensation: Optional[str] = Field(None, max_length=100)

    infoAccurate: bool = False
    agreeTerms: bool = False
