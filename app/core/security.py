import hashlib
import hmac
import secrets

from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from fastapi import HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings


ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


# --- Password ---

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    return pwd_context.verify(
        plain_password,
        hashed_password,
    )


# --- Refresh token ---

def generate_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def hash_refresh_token(raw_token: str) -> str:
    pepper = settings.JWT_REFRESH_TOKEN_PEPPER
    return hmac.digest(
        pepper.encode(),
        raw_token.encode(),
        hashlib.sha256,
    ).hex()


def verify_refresh_token_hash(
    raw_token: str,
    stored_hash: str,
) -> bool:
    computed_hash = hash_refresh_token(raw_token)
    return hmac.compare_digest(computed_hash, stored_hash)


# --- Password reset token ---

def generate_password_reset_token() -> str:
    return secrets.token_urlsafe(32)


def _hash_opaque_token(raw_token: str) -> str:
    pepper = settings.JWT_REFRESH_TOKEN_PEPPER
    return hmac.digest(
        pepper.encode(),
        raw_token.encode(),
        hashlib.sha256,
    ).hex()


def hash_reset_token(raw_token: str) -> str:
    return _hash_opaque_token(raw_token)


def hash_otp_code(raw_code: str) -> str:
    """Store only hashed OTP values (phone OTP — use when implemented)."""
    return _hash_opaque_token(raw_code)


# --- Access token ---

def create_access_token(
    subject: str,
    role: str,
    session_public_id: str,
    expires_delta: timedelta | None = None,
) -> str:

    expire = datetime.now(UTC) + (
        expires_delta
        if expires_delta
        else timedelta(
            milliseconds=settings.JWT_ACCESS_TOKEN_EXPIRE_MS
        )
    )

    now = datetime.now(UTC)
    to_encode = {
        "sub": subject,
        "role": role,
        "token_type": ACCESS_TOKEN_TYPE,
        "session_public_id": session_public_id,
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
    }

    return jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


if TYPE_CHECKING:
    from app.entity.user.app_user import AppUser


def access_token_invalidated_by_password_change(
    payload: dict,
    user: "AppUser",
) -> bool:
    if user.password_changed_at is None:
        return False
    iat = payload.get("iat")
    if iat is None:
        return False
    try:
        issued = datetime.fromtimestamp(int(iat), tz=UTC)
    except (TypeError, ValueError, OSError):
        return False
    return issued < user.password_changed_at


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


def validate_token_type(
    payload: dict,
    expected_type: str,
) -> None:
    token_type = payload.get("token_type")
    if token_type != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )


def decode_access_token_payload(token: str) -> dict:
    """Decode and validate an access JWT (shared by REST and WebSocket auth)."""
    payload = decode_token(token)
    validate_token_type(payload, ACCESS_TOKEN_TYPE)
    return payload


def extract_email(token: str) -> str:
    payload = decode_token(token)
    email = payload.get("sub")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )
    return email


def extract_role(token: str) -> Optional[str]:
    payload = decode_token(token)
    return payload.get("role")


def get_token_expiration(token: str):
    payload = decode_token(token)
    return payload.get("exp")


def is_token_expiring_soon(
    token: str,
    threshold_minutes: int = 5,
) -> bool:
    expiration = get_token_expiration(token)
    if not expiration:
        return True
    expiration_time = datetime.fromtimestamp(
        expiration,
        tz=timezone.utc,
    )
    remaining = expiration_time - datetime.now(timezone.utc)
    return remaining < timedelta(minutes=threshold_minutes)
