from enum import Enum


class AuthProvider(str, Enum):

    OAUTH = "OAUTH"

    PHONE_OTP = "PHONE_OTP"

    EMAIL = "EMAIL"
