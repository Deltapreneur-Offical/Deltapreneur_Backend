from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.repository.user_repository import UserRepository

if TYPE_CHECKING:
    from app.model.auth.complete_profile_request import CompleteProfileRequest
    from app.model.auth.update_profile_request import UpdateProfileRequest

logger = logging.getLogger(__name__)


class ProfileService:
    @staticmethod
    def _to_response(user: AppUser) -> dict:
        return {
            "id": str(user.id),
            "email": user.email,
            "firstname": user.firstname,
            "lastname": user.lastname,
            "username": user.username,
            "phoneNumber": user.phone_number,
            "phoneVerified": user.phone_verified,
            "address": user.address,
            "role": user.role.value,
            "profileComplete": user.profile_complete,
            "emailVerified": user.email_verified,
            "active": user.active,
        }

    @staticmethod
    async def get_my_profile(db: Session, user: AppUser) -> dict:
        return {
            "success": True,
            "message": "Profile fetched successfully",
            "data": ProfileService._to_response(user),
        }

    @staticmethod
    async def complete_profile(
        db: Session,
        user: AppUser,
        body: CompleteProfileRequest,
    ) -> dict:
        if user.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account no longer exists",
            )

        if not user.active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is deactivated",
            )

        username = getattr(body, "username", None)
        phone_number = body.phone_number
        address = body.address

        if not phone_number:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number is required",
            )

        if username:
            existing = (
                db.query(AppUser)
                .filter(
                    AppUser.username == username,
                    AppUser.id != user.id,
                    AppUser.is_deleted.is_(False),
                )
                .first()
            )
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Username is already taken",
                )

        user.firstname = body.firstname
        user.lastname = body.lastname
        if username:
            user.username = username
        if phone_number:
            user.phone_number = phone_number
        user.address = address
        user.profile_complete = True

        if user.role == UserRole.GUEST:
            user.role = UserRole.USER

        try:
            UserRepository.save(db, user)
        except Exception:
            db.rollback()
            logger.exception("complete_profile failed for user_id=%s", user.id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to save profile",
            ) from None

        return {
            "success": True,
            "message": "Profile completed successfully",
            "data": ProfileService._to_response(user),
        }

    @staticmethod
    async def update_profile(
        db: Session,
        user: AppUser,
        body: UpdateProfileRequest,
    ) -> dict:
        """Partial profile update (Java PUT /api/v1/auth/profile/update)."""
        if user.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account no longer exists",
            )

        if not user.active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is deactivated",
            )

        username = body.username
        phone_number = body.phone_number

        if username:
            existing = (
                db.query(AppUser)
                .filter(
                    AppUser.username == username,
                    AppUser.id != user.id,
                    AppUser.is_deleted.is_(False),
                )
                .first()
            )
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Username is already taken",
                )

        if body.firstname is not None:
            user.firstname = body.firstname
        if body.lastname is not None:
            user.lastname = body.lastname
        if username is not None:
            user.username = username
        if phone_number is not None:
            user.phone_number = phone_number
        if body.address is not None:
            user.address = body.address

        if ProfileService._profile_is_complete(user):
            user.profile_complete = True
        else:
            user.profile_complete = False

        if user.role == UserRole.GUEST and user.profile_complete:
            user.role = UserRole.USER

        try:
            UserRepository.save(db, user)
        except Exception:
            db.rollback()
            logger.exception("update_profile failed for user_id=%s", user.id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to save profile",
            ) from None

        profile = ProfileService._to_response(user)
        return {
            "success": True,
            "message": "Profile updated successfully",
            "user": {
                "id": profile["id"],
                "email": profile["email"],
                "role": profile["role"],
            },
            "data": profile,
        }

    @staticmethod
    def _names_allow_profile_complete(firstname: str | None, lastname: str | None) -> bool:
        return bool((firstname or "").strip() and (lastname or "").strip())

    @staticmethod
    def _profile_is_complete(user: AppUser) -> bool:
        return ProfileService._names_allow_profile_complete(
            user.firstname,
            user.lastname,
        ) and bool((user.phone_number or "").strip())
