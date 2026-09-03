from pydantic import EmailStr

from app.model.common.bot_protection_fields import BotProtectionFields


class ForgotPasswordRequest(BotProtectionFields):

    email: EmailStr
