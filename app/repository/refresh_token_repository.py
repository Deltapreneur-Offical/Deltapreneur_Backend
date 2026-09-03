import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.entity.user.app_user import AppUser
from app.entity.user.refresh_token import RefreshToken, RevocationReason


class RefreshTokenRepository:

    @staticmethod
    def find_by_id(
        db: Session,
        token_id: uuid.UUID,
    ) -> RefreshToken | None:
        if token_id is None:
            return None
        return db.query(RefreshToken).filter(RefreshToken.id == token_id).first()

    @staticmethod
    def find_by_token_hash(
        db: Session,
        token_hash: str,
    ) -> RefreshToken | None:
        return (
            db.query(RefreshToken)
            .filter(RefreshToken.token_hash == token_hash)
            .first()
        )

    @staticmethod
    def find_active_by_session(
        db: Session,
        session_public_id: uuid.UUID,
    ) -> list[RefreshToken]:
        now = datetime.now(UTC)
        return (
            db.query(RefreshToken)
            .filter(
                RefreshToken.session_public_id == session_public_id,
                RefreshToken.revoked.is_(False),
                RefreshToken.expires_at > now,
            )
            .all()
        )

    @staticmethod
    def find_by_user_and_revoked_false(
        db: Session,
        user: AppUser,
    ) -> RefreshToken | None:
        return (
            db.query(RefreshToken)
            .filter(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked.is_(False),
            )
            .first()
        )

    @staticmethod
    def save(
        db: Session,
        refresh_token: RefreshToken,
    ) -> RefreshToken:
        db.add(refresh_token)
        db.commit()
        db.refresh(refresh_token)
        return refresh_token

    @staticmethod
    def revoke_session_chain(
        db: Session,
        session_public_id: uuid.UUID,
        reason: RevocationReason,
    ) -> None:
        now = datetime.now(UTC)
        tokens = (
            db.query(RefreshToken)
            .filter(
                RefreshToken.session_public_id == session_public_id,
                RefreshToken.revoked.is_(False),
            )
            .all()
        )
        for token in tokens:
            token.revoked = True
            token.revoked_at = now
            token.revocation_reason = reason
        db.commit()

    @staticmethod
    def revoke_all_user_tokens(
        db: Session,
        user: AppUser,
        reason: RevocationReason,
        *,
        commit: bool = True,
    ) -> None:
        now = datetime.now(UTC)
        tokens = (
            db.query(RefreshToken)
            .filter(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked.is_(False),
            )
            .all()
        )
        for token in tokens:
            token.revoked = True
            token.revoked_at = now
            token.revocation_reason = reason
        if commit:
            db.commit()
