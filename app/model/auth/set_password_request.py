from pydantic import BaseModel, field_validator


class SetPasswordRequest(BaseModel):

    newPassword: str

    @field_validator("newPassword")
    @classmethod
    def validate_new_password(cls, v: str) -> str:

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
