from app.model.common.bot_protection_fields import BotProtectionFields


class LoginRequest(BotProtectionFields):

    email: str

    password: str
