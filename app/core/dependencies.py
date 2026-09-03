from typing import Any, Optional
import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.auth_cookies import (
    ACCESS_TOKEN_COOKIE,
    get_access_token,
    require_csrf_for_cookie_session,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    ACCESS_TOKEN_TYPE,
    access_token_invalidated_by_password_change,
    validate_token_type,
)
from app.entity.user.app_user import AppUser
from app.repository.refresh_token_repository import RefreshTokenRepository
from app.repository.user_repository import UserRepository


security = HTTPBearer(auto_error=False)
optional_security = HTTPBearer(auto_error=False)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def _enforce_cookie_csrf_if_needed(request: Request, bearer: str | None) -> None:
    """When auth is carried by cookies on a mutating request, require CSRF."""
    if bearer:
        return
    if request.method.upper() in _SAFE_METHODS:
        return
    if not request.cookies.get(ACCESS_TOKEN_COOKIE):
        return
    require_csrf_for_cookie_session(request)


def _resolve_current_user(
    token: str,
    db: Session,
) -> AppUser:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )

    validate_token_type(payload, ACCESS_TOKEN_TYPE)

    email = payload.get("sub")
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )

    session_public_id = payload.get("session_public_id")
    if not session_public_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
        )
    try:
        session_uuid = uuid.UUID(str(session_public_id))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
        )
    active_sessions = RefreshTokenRepository.find_active_by_session(db, session_uuid)
    if not active_sessions:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
        )

    user = UserRepository.find_by_email(db, email)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated",
        )

    if user.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account no longer exists",
        )

    if access_token_invalidated_by_password_change(payload, user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
        )

    # Bind session to the authenticated user (prevents token/session mixups).
    session_user_ids = {t.user_id for t in active_sessions}
    if user.id not in session_user_ids:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
        )

    return user


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> AppUser:
    bearer = credentials.credentials if credentials else None
    _enforce_cookie_csrf_if_needed(request, bearer)
    token = get_access_token(request, bearer_token=bearer)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _resolve_current_user(token, db)


def get_optional_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        optional_security
    ),
    db: Session = Depends(get_db),
) -> Optional[AppUser]:
    bearer = credentials.credentials if credentials else None
    token = get_access_token(request, bearer_token=bearer)
    if token is None:
        return None
    try:
        _enforce_cookie_csrf_if_needed(request, bearer)
        return _resolve_current_user(token, db)
    except HTTPException:
        return None


def _role_is_allowed(role_val: str, allowed_roles: Any) -> bool:
    """Exact match, plus SUPER_ADMIN may access routes that allow ADMIN only.

    AUCTION_MODERATOR must be listed explicitly — it does not inherit ADMIN.
    """
    if not isinstance(allowed_roles, (list, tuple, set)):
        roles_iterable = [allowed_roles]
    else:
        roles_iterable = allowed_roles

    allowed = set()
    for r in roles_iterable:
        val = r.value if hasattr(r, "value") else str(r)
        allowed.add(str(val))

    if role_val in allowed:
        return True
    if role_val == "SUPER_ADMIN" and "ADMIN" in allowed:
        return True
    return False


def require_role(allowed_roles: Any):

    def role_checker(
        current_user: AppUser = Depends(get_current_user),
    ) -> AppUser:
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )

        role_val = current_user.role.value if hasattr(current_user.role, "value") else current_user.role

        if not _role_is_allowed(str(role_val), allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        return current_user

    return role_checker
