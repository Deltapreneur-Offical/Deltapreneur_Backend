from pydantic import BaseModel, field_validator


class ResetPasswordRequest(BaseModel):

    token: str
    password: str

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        token = v.strip()
        if not token:
            raise ValueError("Reset token is required")
        return token

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:

        if len(v) < 8:
            raise ValueError(
                "Password must be at least 8 characters"
            )

        if len(v) > 128:
            raise ValueError(
                "Password must be at most 128 characters"
            )

        if not any(c.isdigit() for c in v):
            raise ValueError(
                "Password must contain at least one number"
            )

        if not any(c.isalpha() for c in v):
            raise ValueError(
                "Password must contain at least one letter"
            )

        return v
