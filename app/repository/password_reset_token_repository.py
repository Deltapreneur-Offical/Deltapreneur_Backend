import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session, joinedload

from app.entity.user.password_reset_token import PasswordResetToken


class PasswordResetTokenRepository:

    @staticmethod
    def find_by_token_hash(
        db: Session,
        token_hash: str,
    ) -> PasswordResetToken | None:
        return (
            db.query(PasswordResetToken)
            .options(joinedload(PasswordResetToken.user))
            .filter(PasswordResetToken.token_hash == token_hash)
            .first()
        )

    @staticmethod
    def add(
        db: Session,
        token: PasswordResetToken,
        *,
        commit: bool = True,
    ) -> PasswordResetToken:
        db.add(token)
        if commit:
            db.commit()
            db.refresh(token)
        return token

    @staticmethod
    def delete_unused_for_user(
        db: Session,
        user_id: uuid.UUID,
        *,
        commit: bool = True,
    ) -> None:
        (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
            )
            .delete(synchronize_session=False)
        )
        if commit:
            db.commit()

    @staticmethod
    def delete_all_except(
        db: Session,
        user_id: uuid.UUID,
        keep_id: uuid.UUID,
        *,
        commit: bool = True,
    ) -> None:
        (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.id != keep_id,
            )
            .delete(synchronize_session=False)
        )
        if commit:
            db.commit()

    @staticmethod
    def delete_all_for_user(
        db: Session,
        user_id: uuid.UUID,
        *,
        commit: bool = True,
    ) -> None:
        (
            db.query(PasswordResetToken)
            .filter(PasswordResetToken.user_id == user_id)
            .delete(synchronize_session=False)
        )
        if commit:
            db.commit()

    @staticmethod
    def mark_used(
        db: Session,
        token: PasswordResetToken,
        used_at: datetime,
        *,
        commit: bool = True,
    ) -> None:
        token.used_at = used_at
        if commit:
            db.commit()
