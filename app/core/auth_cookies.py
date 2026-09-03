"""HttpOnly session cookies for access and refresh tokens."""

import secrets

from fastapi import HTTPException, Request, Response, status

from app.core.config import settings
from app.core.frontend_origins import cookie_domain_for_request

ACCESS_TOKEN_COOKIE = "access_token"
REFRESH_TOKEN_COOKIE = "refresh_token"
CSRF_TOKEN_COOKIE = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"


def _cookie_domain(request: Request | None = None) -> str | None:
    if request is not None:
        return cookie_domain_for_request(request)
    domain = (settings.AUTH_COOKIE_DOMAIN or "").strip()
    return domain or None


def _secure_flag() -> bool:
    return settings.ENVIRONMENT == "production" or (
        settings.AUTH_COOKIE_SAMESITE == "none"
    )


def _shared_cookie_kwargs(
    *,
    max_age: int | None = None,
    request: Request | None = None,
) -> dict:
    kwargs: dict = {
        "path": "/",
        "samesite": settings.AUTH_COOKIE_SAMESITE,
        "secure": _secure_flag(),
    }
    if max_age is not None:
        kwargs["max_age"] = max_age
    domain = _cookie_domain(request)
    if domain:
        kwargs["domain"] = domain
    return kwargs


def _session_cookie_kwargs(*, max_age: int, request: Request | None = None) -> dict:
    return {
        "httponly": True,
        **_shared_cookie_kwargs(max_age=max_age, request=request),
    }


def _delete_cookie_kwargs(*, request: Request | None = None) -> dict:
    return {
        "httponly": True,
        **_shared_cookie_kwargs(request=request),
    }


def _csrf_cookie_kwargs(*, max_age: int, request: Request | None = None) -> dict:
    return {
        "httponly": False,
        **_shared_cookie_kwargs(max_age=max_age, request=request),
    }


def attach_session_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: str,
    request: Request | None = None,
) -> None:
    access_max = max(1, settings.JWT_ACCESS_TOKEN_EXPIRE_MS // 1000)
    refresh_max = max(1, settings.JWT_REFRESH_TOKEN_EXPIRE_MS // 1000)
    response.set_cookie(
        ACCESS_TOKEN_COOKIE,
        access_token,
        **_session_cookie_kwargs(max_age=access_max, request=request),
    )
    response.set_cookie(
        REFRESH_TOKEN_COOKIE,
        refresh_token,
        **_session_cookie_kwargs(max_age=refresh_max, request=request),
    )
    response.set_cookie(
        CSRF_TOKEN_COOKIE,
        secrets.token_urlsafe(32),
        **_csrf_cookie_kwargs(max_age=refresh_max, request=request),
    )


def attach_session_from_jwt_data(
    response: Response,
    jwt_data: dict,
    request: Request | None = None,
) -> None:
    access = jwt_data.get("accessToken")
    refresh = jwt_data.get("refreshToken")
    if access and refresh:
        attach_session_cookies(
            response,
            access_token=access,
            refresh_token=refresh,
            request=request,
        )


def clear_session_cookies(
    response: Response,
    request: Request | None = None,
) -> None:
    delete_kwargs = _delete_cookie_kwargs(request=request)
    response.delete_cookie(ACCESS_TOKEN_COOKIE, **delete_kwargs)
    response.delete_cookie(REFRESH_TOKEN_COOKIE, **delete_kwargs)
    csrf_delete = {
        "httponly": False,
        **_shared_cookie_kwargs(request=request),
    }
    response.delete_cookie(CSRF_TOKEN_COOKIE, **csrf_delete)


def get_refresh_token(
    request: Request,
    body_token: str | None = None,
) -> str | None:
    cookie_token = request.cookies.get(REFRESH_TOKEN_COOKIE)
    if cookie_token:
        return cookie_token
    if body_token and body_token.strip():
        return body_token.strip()
    return None


def get_access_token(
    request: Request,
    bearer_token: str | None = None,
) -> str | None:
    if bearer_token:
        return bearer_token
    cookie_token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if cookie_token:
        return cookie_token
    return None


def _refresh_token_from_cookie(request: Request) -> bool:
    return bool(request.cookies.get(REFRESH_TOKEN_COOKIE))


def require_csrf_for_cookie_session(request: Request) -> None:
    """Mitigate CSRF when the browser sends access/refresh session cookies."""
    has_cookie_session = bool(
        request.cookies.get(ACCESS_TOKEN_COOKIE)
        or request.cookies.get(REFRESH_TOKEN_COOKIE)
    )
    if not has_cookie_session:
        return
    header = request.headers.get(CSRF_HEADER_NAME)
    cookie = request.cookies.get(CSRF_TOKEN_COOKIE)
    if (
        not header
        or not cookie
        or not secrets.compare_digest(str(header), str(cookie))
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed",
        )
