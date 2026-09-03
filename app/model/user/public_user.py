from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from app.entity.user.app_user import AppUser
from app.utils.user_identity import resolved_username


class PublicUserResponse(BaseModel):
    """Public marketplace identity — no account email."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str | None = None
    firstname: str | None = None
    lastname: str | None = None
    role: str | None = None


class OwnerUserSummaryResponse(PublicUserResponse):
    """Owner/admin view — includes account email."""

    email: str


def to_public_user(user: AppUser) -> PublicUserResponse:
    role = user.role.value if hasattr(user.role, "value") else user.role
    return PublicUserResponse(
        id=user.id,
        username=resolved_username(user),
        firstname=user.firstname,
        lastname=user.lastname,
        role=role,
    )


def to_owner_user(user: AppUser) -> OwnerUserSummaryResponse:
    role = user.role.value if hasattr(user.role, "value") else user.role
    return OwnerUserSummaryResponse(
        id=user.id,
        username=resolved_username(user),
        firstname=user.firstname,
        lastname=user.lastname,
        role=role,
        email=user.email,
    )
