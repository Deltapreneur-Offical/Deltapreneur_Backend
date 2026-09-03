from typing import Optional

from pydantic import ConfigDict, EmailStr, Field

from app.model.common.bot_protection_fields import BotProtectionFields


class FeedbackRequest(BotProtectionFields):
    model_config = ConfigDict(populate_by_name=True)

    email: Optional[EmailStr] = None
    subject: Optional[str] = Field(None, max_length=200)
    message: str = Field(..., min_length=1, max_length=5000)
    feedback_type: Optional[str] = Field(None, alias="feedbackType")
    page_url: Optional[str] = Field(None, alias="pageUrl")
