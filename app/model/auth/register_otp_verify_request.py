from pydantic import ConfigDict, EmailStr, Field

from app.model.common.bot_protection_fields import BotProtectionFields


class RegisterOtpVerifyRequest(BotProtectionFields):
    model_config = ConfigDict(populate_by_name=True)

    email: EmailStr
    otpCode: str = Field(..., min_length=4, max_length=10, alias="otpCode")

    @property
    def otp_code(self) -> str:
        return self.otpCode
