import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole


class UserRepository:

    @staticmethod
    def find_by_email(
        db: Session,
        email: str,
        *,
        include_deleted: bool = False,
    ):

        query = (
            db.query(AppUser)
            .filter(
                AppUser.email == email
            )
        )

        if not include_deleted:

            query = query.filter(
                AppUser.is_deleted.is_(False)
            )

        return query.first()

    @staticmethod
    def find_by_email_insensitive(
        db: Session,
        email: str,
        *,
        include_deleted: bool = False,
    ):
        from sqlalchemy import func

        normalized = (email or "").strip().lower()
        if not normalized:
            return None

        query = db.query(AppUser).filter(func.lower(AppUser.email) == normalized)

        if not include_deleted:
            query = query.filter(AppUser.is_deleted.is_(False))

        return query.first()

    @staticmethod
    def exists_by_email(
        db: Session,
        email: str,
    ) -> bool:

        return (
            UserRepository.find_by_email(
                db=db,
                email=email,
                include_deleted=True,
            )
            is not None
        )

    @staticmethod
    def save(
        db: Session,
        user: AppUser,
    ):

        db.add(user)

        db.commit()

        db.refresh(user)

        return user

    @staticmethod
    def find_by_id(
        db: Session,
        user_id: uuid.UUID,
    ) -> Optional[AppUser]:

        return (
            db.query(AppUser)
            .filter(
                AppUser.id == user_id,
                AppUser.is_deleted.is_(False),
            )
            .first()
        )

    @staticmethod
    def find_by_verification_token(
        db: Session,
        token: str,
    ):

        return (
            db.query(AppUser)
            .filter(
                AppUser.verification_token == token,
                AppUser.is_deleted.is_(False),
            )
            .first()
        )

    @staticmethod
    def find_by_role(
        db: Session,
        role: UserRole,
    ):

        return (
            db.query(AppUser)
            .filter(
                AppUser.role == role,
                AppUser.is_deleted.is_(False),
            )
            .all()
        )

    @staticmethod
    def find_by_oauth_provider_and_provider_id(
        db: Session,
        oauth_provider: str,
        oauth_provider_id: str,
    ):

        return (
            db.query(AppUser)
            .filter(
                AppUser.oauth_provider == oauth_provider,
                AppUser.oauth_provider_id == oauth_provider_id,
                AppUser.is_deleted.is_(False),
            )
            .first()
        )