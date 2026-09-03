import logging
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from fastapi import Request
from fastapi import status
from fastapi.responses import JSONResponse, RedirectResponse
import httpx

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.bot_protection import enforce_bot_protection
from app.core.client_ip import get_client_ip
from app.core.config import settings
from app.core.route_logging import log_route_exception, request_payload_for_logging
from app.core.rate_limiter import (
    CHANGE_PASSWORD_RATE_LIMIT,
    FORGOT_PASSWORD_RATE_LIMIT,
    RESET_PASSWORD_RATE_LIMIT,
    limiter,
)

from app.core.database import get_db

from app.model.auth.login_request import LoginRequest
from app.model.auth.register_request import RegisterRequest

from app.model.common.api_response import ApiResponse

from app.service.auth.auth_exceptions import (
    AccountInactiveException,
    EmailNotVerifiedException,
    InvalidCredentialsException,
    InvalidPasswordResetTokenException,
    InvalidVerificationTokenException,
)

from app.service.auth.auth_service import AuthService
from app.model.auth.refresh_token_request import (
    RefreshTokenRequest
)

from app.model.auth.logout_request import (
    LogoutRequest
)

from app.core.dependencies import (
    get_current_user
)

from app.entity.user.app_user import AppUser

from app.model.auth.resend_verification_request import (
    ResendVerificationRequest
)

from app.core.dependencies import (
    require_role
)

from app.model.auth.forgot_password_request import (
    ForgotPasswordRequest,
)

from app.model.auth.reset_password_request import (
    ResetPasswordRequest,
)

from app.model.auth.change_password_request import (
    ChangePasswordRequest,
)

from app.model.auth.set_password_request import (
    SetPasswordRequest,
)

from app.model.auth.complete_profile_request import CompleteProfileRequest
from app.model.auth.update_profile_request import UpdateProfileRequest
from app.service.profile.profile_service import ProfileService

from app.core.oauth_state import (
    create_oauth_state,
    oauth_state_cookie_name,
    parse_oauth_state,
    verify_oauth_state,
)
from app.core.frontend_origins import (
    allowed_frontend_return_origin,
    gated_frontend_origin,
)
from app.integrations.oauth.google_oauth_redirect import (
    build_google_authorization_url,
    exchange_code_and_verify_id_token,
    google_oauth_redirect_uri,
)
from app.integrations.oauth.linkedin_oauth_redirect import (
    build_linkedin_authorization_url,
    exchange_code_and_get_linkedin_profile,
    linkedin_oauth_redirect_uri,
)
from app.integrations.oauth.facebook_oauth_redirect import (
    build_facebook_authorization_url,
    exchange_code_and_get_facebook_profile,
    facebook_oauth_redirect_uri,
)
from app.integrations.oauth.instagram_oauth_redirect import (
    build_instagram_authorization_url,
    exchange_code_and_get_instagram_profile,
    instagram_oauth_redirect_uri,
)
from app.core.auth_cookies import (
    attach_session_from_jwt_data,
    clear_session_cookies,
    get_refresh_token,
    require_csrf_for_cookie_session,
)
from app.model.auth.otp_request import OtpRequest
from app.model.auth.otp_verify import OtpVerify
from app.model.auth.register_otp_verify_request import RegisterOtpVerifyRequest

logger = logging.getLogger(__name__)

_GOOGLE_OAUTH_COOKIE_MAX_AGE = 600


router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Auth"]
)

legacy_router = APIRouter(
    prefix="/api/auth",
    tags=["Auth Legacy"]
)

# Back-compat: old /api/v1/profile/* URLs redirect or delegate to auth profile routes.
profile_compat_router = APIRouter(
    prefix="/api/v1/profile",
    tags=["Profile (deprecated)"],
    include_in_schema=False,
)


async def register_handler(
    request: RegisterRequest,
    db: Session
):

    return await AuthService.register(
        db,
        request.email,
        request.password
    )


async def login_handler(
    body: LoginRequest,
    db: Session,
    ip_address: str | None = None,
    user_agent: str | None = None,
    device_name: str | None = None,
):
    return await AuthService.login(
        db,
        body.email,
        body.password,
        ip_address=ip_address,
        user_agent=user_agent,
        device_name=device_name,
    )
    
def _google_oauth_frontend_redirect(
    *,
    success: bool,
    error: str | None = None,
    new_user: bool = False,
    session_data: dict | None = None,
    provider: str | None = None,
    include_tokens: bool = False,
    return_origin: str | None = None,
    request: Request | None = None,
) -> RedirectResponse:
    gated = gated_frontend_origin(return_origin=return_origin, request=request)
    frontend = (gated or settings.FRONTEND_BASE_URL).rstrip("/")

    if success:
        if gated:
            base = f"{gated}/auth/callback"
        else:
            base = settings.google_oauth_success_redirect_url()
        query_dict = {
            "success": "1",
            "newUser": str(new_user).lower(),
            "profileComplete": str(
                bool((session_data or {}).get("profileComplete"))
            ).lower(),
        }
        if provider:
            query_dict["provider"] = provider
        # Tokens are attached as HttpOnly cookies during the callback flow;
        # never expose them in the frontend redirect URL.
        params = urlencode(query_dict)
        url = f"{base}?{params}"
        return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)

    login_url = f"{frontend}/login?{urlencode({'error': error or 'oauth_failed'})}"
    return RedirectResponse(url=login_url, status_code=status.HTTP_302_FOUND)


def _oauth_state_payload(state: str | None, provider: str) -> dict:
    if not state:
        return {}
    return parse_oauth_state(state, provider=provider) or {}


def _oauth_state_cookie_kwargs() -> dict:
    return {
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "max_age": _GOOGLE_OAUTH_COOKIE_MAX_AGE,
        "secure": settings.ENVIRONMENT == "production",
    }


def _oauth_state_matches(state: str | None, cookie_state: str | None) -> bool:
    """Signed state must verify; cookie must match except in local dev cookie loss."""
    if not state or not verify_oauth_state(state, provider="google"):
        return False
    if state == cookie_state:
        return True
    # Local dev: Vite proxy or localhost vs 127.0.0.1 can drop the oauth_state cookie.
    if settings.ENVIRONMENT == "development" and not cookie_state:
        return True
    return False


async def google_oauth_login_redirect_handler(
    request: Request | None = None,
    return_origin: str | None = None,
) -> RedirectResponse:
    if request is not None and not return_origin:
        return_origin = request.query_params.get("return_origin")
    if not settings.GOOGLE_CLIENT_ID.strip():
        return _google_oauth_frontend_redirect(
            success=False,
            error="google_oauth_not_configured",
            return_origin=return_origin,
            request=request,
        )
    if not settings.GOOGLE_CLIENT_SECRET.strip():
        return _google_oauth_frontend_redirect(
            success=False,
            error="google_oauth_secret_missing",
            return_origin=return_origin,
            request=request,
        )

    redirect_uri = google_oauth_redirect_uri(request)
    state = create_oauth_state(
        "google",
        return_origin=allowed_frontend_return_origin(return_origin),
        redirect_uri=redirect_uri,
    )
    logger.info("Starting Google OAuth; redirect_uri=%s", redirect_uri)
    response = RedirectResponse(
        url=build_google_authorization_url(state, redirect_uri=redirect_uri),
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        oauth_state_cookie_name(),
        state,
        **_oauth_state_cookie_kwargs(),
    )
    return response


async def google_oauth_callback_handler(
    request: Request,
    db: Session,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    cookie_name = oauth_state_cookie_name()
    cookie_state = request.cookies.get(cookie_name)
    payload = _oauth_state_payload(state, "google")
    return_origin = payload.get("return_origin")
    stored_redirect_uri = payload.get("redirect_uri")

    logger.info(
        "[OAUTH DEBUG] google callback received: code=%s state=%s error=%s "
        "cookie_state=%s remote=%s",
        bool(code),
        bool(state),
        error,
        bool(cookie_state),
        request.client.host if request.client else None,
    )

    def finish(
        redirect: RedirectResponse,
        *,
        clear_session: bool = False,
    ) -> RedirectResponse:
        redirect.delete_cookie(cookie_name, path="/")
        if clear_session:
            clear_session_cookies(redirect, request=request)
        return redirect

    if error:
        logger.warning("[OAUTH DEBUG] google returned error param: %s", error)
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error=error,
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )

    if not code or not _oauth_state_matches(state, cookie_state):
        logger.warning(
            "[OAUTH DEBUG] rejecting: code_present=%s state_matches=%s "
            "env=%s cookie_state_present=%s",
            bool(code),
            _oauth_state_matches(state, cookie_state),
            settings.ENVIRONMENT,
            bool(cookie_state),
        )
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error="invalid_oauth_state",
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )

    try:
        callback_redirect_uri = google_oauth_redirect_uri(
            request,
            stored_uri=stored_redirect_uri,
        )
        logger.info(
            "[OAUTH DEBUG] exchanging code with Google; redirect_uri=%s",
            callback_redirect_uri,
        )
        oauth_data = exchange_code_and_verify_id_token(
            code,
            redirect_uri=callback_redirect_uri,
        )
        logger.info(
            "[OAUTH DEBUG] token exchange ok; email=%s sub=%s",
            oauth_data.get("profile", {}).get("email"),
            oauth_data.get("profile", {}).get("sub"),
        )
        google_profile = oauth_data.get("profile") or {}
        google_tokens = oauth_data.get("tokens") or {}
        result = await AuthService.login_with_google_profile(
            db=db,
            google_user=google_profile,
            google_tokens=google_tokens,
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            device_name=None,
        )
    except InvalidCredentialsException as e:
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error=str(e),
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )
    except AccountInactiveException as e:
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error=str(e),
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )
    except ValueError as e:
        logger.warning("Google OAuth validation failed: %s", e)
        msg = str(e).lower()
        if "token exchange failed" in msg:
            code = "oauth_token_exchange_failed"
        elif "clock" in msg or "too early" in msg or "too late" in msg:
            code = "oauth_clock_skew"
        elif "id_token" in msg or "issuer" in msg:
            code = "google_id_token_invalid"
        else:
            code = "google_authentication_failed"
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error=code,
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )
    except OperationalError:
        logger.exception("Google OAuth callback database connection failed")
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error="database_unavailable",
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )
    except (httpx.ConnectError, httpx.TimeoutException):
        logger.exception("Google OAuth callback network error")
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error="oauth_network_error",
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )
    except Exception:
        logger.exception("Google OAuth callback failed")
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error="google_authentication_failed",
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )

    if not result.get("success"):
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error=result.get("error", "google_authentication_failed"),
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )

    session_data = result.get("data") or {}
    redirect = _google_oauth_frontend_redirect(
        success=True,
        new_user=bool(session_data.get("newUser")),
        session_data=session_data,
        provider="google",
        include_tokens=True,
        return_origin=return_origin,
        request=request,
    )
    attach_session_from_jwt_data(redirect, session_data, request=request)
    return finish(redirect)


def _oauth_state_matches_generic(state: str | None, cookie_state: str | None, provider: str) -> bool:
    if not state or not verify_oauth_state(state, provider=provider):
        return False
    if state == cookie_state:
        return True
    if settings.ENVIRONMENT == "development" and not cookie_state:
        return True
    return False


async def linkedin_oauth_login_redirect_handler(
    request: Request | None = None,
    return_origin: str | None = None,
) -> RedirectResponse:
    if request is not None and not return_origin:
        return_origin = request.query_params.get("return_origin")
    if not settings.LINKEDIN_CLIENT_ID or not settings.LINKEDIN_CLIENT_ID.strip():
        return _google_oauth_frontend_redirect(
            success=False,
            error="linkedin_oauth_not_configured",
            return_origin=return_origin,
            request=request,
        )
    if not settings.LINKEDIN_CLIENT_SECRET or not settings.LINKEDIN_CLIENT_SECRET.strip():
        return _google_oauth_frontend_redirect(
            success=False,
            error="linkedin_oauth_secret_missing",
            return_origin=return_origin,
            request=request,
        )

    redirect_uri = linkedin_oauth_redirect_uri(request)
    state = create_oauth_state(
        "linkedin",
        return_origin=allowed_frontend_return_origin(return_origin),
        redirect_uri=redirect_uri,
    )
    logger.info("Starting LinkedIn OAuth; redirect_uri=%s", redirect_uri)
    response = RedirectResponse(
        url=build_linkedin_authorization_url(state, redirect_uri=redirect_uri),
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        oauth_state_cookie_name(),
        state,
        **_oauth_state_cookie_kwargs(),
    )
    return response


async def linkedin_oauth_callback_handler(
    request: Request,
    db: Session,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    cookie_name = oauth_state_cookie_name()
    cookie_state = request.cookies.get(cookie_name)
    payload = _oauth_state_payload(state, "linkedin")
    return_origin = payload.get("return_origin")
    stored_redirect_uri = payload.get("redirect_uri")

    def finish(
        redirect: RedirectResponse,
        *,
        clear_session: bool = False,
    ) -> RedirectResponse:
        redirect.delete_cookie(cookie_name, path="/")
        if clear_session:
            clear_session_cookies(redirect, request=request)
        return redirect

    if error:
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error=error,
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )

    if not code or not _oauth_state_matches_generic(state, cookie_state, "linkedin"):
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error="invalid_oauth_state",
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )

    try:
        callback_redirect_uri = linkedin_oauth_redirect_uri(
            request,
            stored_uri=stored_redirect_uri,
        )
        logger.info(
            "LinkedIn OAuth: exchanging authorization code for access token; redirect_uri=%s",
            callback_redirect_uri,
        )
        oauth_data = exchange_code_and_get_linkedin_profile(
            code,
            redirect_uri=callback_redirect_uri,
        )
        profile = oauth_data.get("profile") or {}
        logger.info(
            "LinkedIn OAuth: token exchange succeeded; profile id=%s email=%s",
            profile.get("id"),
            profile.get("email"),
        )
        result = await AuthService.login_with_oauth_profile(
            db=db,
            provider="linkedin",
            provider_id=profile.get("id"),
            email=profile.get("email"),
            firstname=profile.get("first_name"),
            lastname=profile.get("last_name"),
            picture=profile.get("picture"),
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            device_name=None,
        )
        logger.info("LinkedIn OAuth: login_with_oauth_profile result=%s", result)
    except Exception as e:
        logger.exception("LinkedIn OAuth callback failed")
        error_message = f"{type(e).__name__}: {str(e)}"
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error=error_message,
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )

    if not result.get("success"):
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error=result.get("error", "linkedin_authentication_failed"),
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )

    session_data = result.get("data") or {}
    redirect = _google_oauth_frontend_redirect(
        success=True,
        new_user=bool(session_data.get("newUser")),
        session_data=session_data,
        provider="linkedin",
        include_tokens=True,
        return_origin=return_origin,
        request=request,
    )
    attach_session_from_jwt_data(redirect, session_data, request=request)
    return finish(redirect)


async def facebook_oauth_login_redirect_handler(
    request: Request | None = None,
    return_origin: str | None = None,
) -> RedirectResponse:
    if request is not None and not return_origin:
        return_origin = request.query_params.get("return_origin")
    if not settings.FACEBOOK_CLIENT_ID or not settings.FACEBOOK_CLIENT_ID.strip():
        logger.error("Facebook OAuth login attempted but FACEBOOK_CLIENT_ID is not configured")
        return _google_oauth_frontend_redirect(
            success=False,
            error="facebook_oauth_not_configured",
            return_origin=return_origin,
            request=request,
        )
    if not settings.FACEBOOK_CLIENT_SECRET or not settings.FACEBOOK_CLIENT_SECRET.strip():
        logger.error("Facebook OAuth login attempted but FACEBOOK_CLIENT_SECRET is not configured")
        return _google_oauth_frontend_redirect(
            success=False,
            error="facebook_oauth_secret_missing",
            return_origin=return_origin,
            request=request,
        )

    state = create_oauth_state(
        "facebook",
        return_origin=allowed_frontend_return_origin(return_origin),
    )
    redirect_uri = facebook_oauth_redirect_uri()
    logger.info("Starting Facebook OAuth; redirect_uri=%s", redirect_uri)
    response = RedirectResponse(
        url=build_facebook_authorization_url(state),
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        oauth_state_cookie_name(),
        state,
        **_oauth_state_cookie_kwargs(),
    )
    logger.info("Facebook OAuth login redirect response sent; state=%s", state[:32])
    return response


async def facebook_oauth_callback_handler(
    request: Request,
    db: Session,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    cookie_name = oauth_state_cookie_name()
    cookie_state = request.cookies.get(cookie_name)
    payload = _oauth_state_payload(state, "facebook")
    return_origin = payload.get("return_origin")
    logger.info(
        "Facebook OAuth callback entered; error=%s code=%s state=%s cookie_state=%s",
        error,
        bool(code),
        bool(state),
        bool(cookie_state),
    )

    def finish(
        redirect: RedirectResponse,
        *,
        clear_session: bool = False,
    ) -> RedirectResponse:
        redirect.delete_cookie(cookie_name, path="/")
        if clear_session:
            clear_session_cookies(redirect, request=request)
        logger.info(
            "Facebook OAuth callback finishing; clear_session=%s location=%s",
            clear_session,
            redirect.headers.get("location"),
        )
        return redirect

    if error:
        logger.error("Facebook OAuth returned error=%s", error)
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error=error,
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )

    if not code or not _oauth_state_matches_generic(state, cookie_state, "facebook"):
        logger.error(
            "Facebook OAuth state/code validation failed; code=%s state=%s cookie_state=%s",
            bool(code),
            bool(state),
            bool(cookie_state),
        )
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error="invalid_oauth_state",
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )

    try:
        logger.info("Exchanging Facebook authorization code for access token")
        oauth_data = exchange_code_and_get_facebook_profile(code)
        profile = oauth_data.get("profile") or {}
        provider_id = profile.get("id")
        logger.info(
            "Facebook profile fetched; provider_id=%s email=%s",
            provider_id,
            profile.get("email"),
        )
        if not provider_id:
            logger.error("Facebook profile missing id: %s", profile)
            return finish(
                _google_oauth_frontend_redirect(
                    success=False,
                    error="facebook_profile_invalid",
                    return_origin=return_origin,
                    request=request,
                ),
                clear_session=True,
            )
        logger.info("Logging in Facebook user provider_id=%s", provider_id)
        result = await AuthService.login_with_oauth_profile(
            db=db,
            provider="facebook",
            provider_id=str(provider_id).strip(),
            email=profile.get("email"),
            firstname=profile.get("first_name"),
            lastname=profile.get("last_name"),
            picture=profile.get("picture"),
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            device_name=None,
        )
        logger.info("Facebook login_with_oauth_profile result success=%s", result.get("success"))
    except ValueError as e:
        logger.error("Facebook OAuth value error: %s", str(e))
        error_code = "facebook_authentication_failed"
        if "token" in str(e).lower():
            error_code = "facebook_token_error"
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error=error_code,
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )
    except Exception as e:
        logger.exception("Facebook OAuth callback failed")
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error="facebook_authentication_failed",
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )

    if not result.get("success"):
        logger.error("Facebook OAuth login failed: %s", result.get("error"))
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error=result.get("error", "facebook_authentication_failed"),
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )

    session_data = result.get("data") or {}
    redirect = _google_oauth_frontend_redirect(
        success=True,
        new_user=bool(session_data.get("newUser")),
        session_data=session_data,
        provider="facebook",
        include_tokens=True,
        return_origin=return_origin,
        request=request,
    )
    attach_session_from_jwt_data(redirect, session_data, request=request)
    logger.info(
        "Facebook OAuth success; redirecting to %s",
        redirect.headers.get("location"),
    )
    return finish(redirect)


async def instagram_oauth_login_redirect_handler(
    request: Request | None = None,
    return_origin: str | None = None,
) -> RedirectResponse:
    if request is not None and not return_origin:
        return_origin = request.query_params.get("return_origin")
    if not settings.INSTAGRAM_CLIENT_ID or not settings.INSTAGRAM_CLIENT_ID.strip():
        return _google_oauth_frontend_redirect(
            success=False,
            error="instagram_oauth_not_configured",
            return_origin=return_origin,
            request=request,
        )
    if not settings.INSTAGRAM_CLIENT_SECRET or not settings.INSTAGRAM_CLIENT_SECRET.strip():
        return _google_oauth_frontend_redirect(
            success=False,
            error="instagram_oauth_secret_missing",
            return_origin=return_origin,
            request=request,
        )

    state = create_oauth_state(
        "instagram",
        return_origin=allowed_frontend_return_origin(return_origin),
    )
    redirect_uri = instagram_oauth_redirect_uri()
    logger.info("Starting Instagram OAuth; redirect_uri=%s", redirect_uri)
    response = RedirectResponse(
        url=build_instagram_authorization_url(state),
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        oauth_state_cookie_name(),
        state,
        **_oauth_state_cookie_kwargs(),
    )
    return response


async def instagram_oauth_callback_handler(
    request: Request,
    db: Session,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    cookie_name = oauth_state_cookie_name()
    cookie_state = request.cookies.get(cookie_name)
    payload = _oauth_state_payload(state, "instagram")
    return_origin = payload.get("return_origin")

    def finish(
        redirect: RedirectResponse,
        *,
        clear_session: bool = False,
    ) -> RedirectResponse:
        redirect.delete_cookie(cookie_name, path="/")
        if clear_session:
            clear_session_cookies(redirect, request=request)
        return redirect

    if error:
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error=error,
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )

    if not code or not _oauth_state_matches_generic(state, cookie_state, "instagram"):
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error="invalid_oauth_state",
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )

    try:
        oauth_data = exchange_code_and_get_instagram_profile(code)
        profile = oauth_data.get("profile") or {}
        result = await AuthService.login_with_oauth_profile(
            db=db,
            provider="instagram",
            provider_id=profile.get("id"),
            email=profile.get("email"),
            firstname=profile.get("username"),
            lastname=None,
            picture=None,
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            device_name=None,
        )
    except Exception as e:
        logger.exception("Instagram OAuth callback failed")
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error="instagram_authentication_failed",
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )

    if not result.get("success"):
        return finish(
            _google_oauth_frontend_redirect(
                success=False,
                error=result.get("error", "instagram_authentication_failed"),
                return_origin=return_origin,
                request=request,
            ),
            clear_session=True,
        )

    session_data = result.get("data") or {}
    redirect = _google_oauth_frontend_redirect(
        success=True,
        new_user=bool(session_data.get("newUser")),
        session_data=session_data,
        provider="instagram",
        include_tokens=True,
        return_origin=return_origin,
        request=request,
    )
    attach_session_from_jwt_data(redirect, session_data, request=request)
    return finish(redirect)


def _json_with_session_cookies(
    payload: dict,
    request: Request | None = None,
) -> JSONResponse:
    response = JSONResponse(content=payload)
    if payload.get("success") and payload.get("data"):
        attach_session_from_jwt_data(response, payload["data"], request=request)
    return response


async def refresh_handler(
    http_request: Request,
    body: RefreshTokenRequest,
    db: Session,
):

    require_csrf_for_cookie_session(http_request)

    raw_refresh = get_refresh_token(
        http_request,
        body.refreshToken,
    )
    if not raw_refresh:
        return JSONResponse(
            content={
                "success": False,
                "error": "Refresh token required",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    try:
        response = await AuthService.refresh_access_token(
            db,
            raw_refresh,
        )
    except InvalidCredentialsException as e:
        resp = JSONResponse(
            content={"success": False, "error": str(e)},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
        clear_session_cookies(resp, request=http_request)
        return resp
    except AccountInactiveException as e:
        resp = JSONResponse(
            content={"success": False, "error": str(e)},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
        clear_session_cookies(resp, request=http_request)
        return resp

    resp = JSONResponse(content=response)
    if response.get("success") and response.get("data"):
        data = response["data"]
        attach_session_from_jwt_data(
            resp,
            {
                "accessToken": data.get("accessToken"),
                "refreshToken": data.get("refreshToken"),
            },
            request=http_request,
        )
    return resp


async def logout_handler(
    http_request: Request,
    body: LogoutRequest,
    db: Session,
):

    require_csrf_for_cookie_session(http_request)

    raw_refresh = get_refresh_token(
        http_request,
        body.refreshToken,
    )
    if raw_refresh:
        response = await AuthService.logout(db, raw_refresh)
    else:
        response = {
            "success": True,
            "message": "Logout successful",
        }

    resp = JSONResponse(content=response)
    clear_session_cookies(resp, request=http_request)
    return resp

async def resend_verification_handler(
    request: ResendVerificationRequest,
    db: Session
):

    return await AuthService.resend_verification_email(
        db,
        request.email,
    )

async def forgot_password_handler(
    body: ForgotPasswordRequest,
    db: Session,
    ip_address: str | None = None,
    user_agent: str | None = None,
):

    return await AuthService.forgot_password(
        db,
        body.email,
        ip_address=ip_address,
        user_agent=user_agent,
    )


async def reset_password_handler(
    body: ResetPasswordRequest,
    db: Session,
):
    return await AuthService.reset_password(
        db,
        body.token,
        body.password,
    )


async def change_password_handler(
    body: ChangePasswordRequest,
    db: Session,
    current_user: AppUser,
    request: Request | None = None,
):
    result = await AuthService.change_password(
        db,
        current_user,
        body.currentPassword,
        body.newPassword,
    )

    resp = JSONResponse(content=result)
    if result.get("success"):
        clear_session_cookies(resp, request=request)
    return resp


async def set_password_handler(
    body: SetPasswordRequest,
    db: Session,
    current_user: AppUser,
    request: Request | None = None,
):
    result = await AuthService.set_password(
        db,
        current_user,
        body.newPassword,
    )

    resp = JSONResponse(content=result)
    if result.get("success"):
        clear_session_cookies(resp, request=request)
    return resp


async def verify_email_handler(
    request: Request,
    token: str,
    db: Session,
):
    frontend = settings.FRONTEND_BASE_URL.rstrip("/")

    def login_error(code: str) -> RedirectResponse:
        return RedirectResponse(
            url=f"{frontend}/login?{urlencode({'error': code})}",
            status_code=status.HTTP_302_FOUND,
        )

    try:
        result = await AuthService.verify_email(
            db,
            token,
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            device_name=None,
        )
    except InvalidVerificationTokenException:
        return login_error("verification_failed")
    except (AccountInactiveException, InvalidCredentialsException):
        return login_error("account_unavailable")

    session_data = result.get("data") or {}
    redirect = _google_oauth_frontend_redirect(
        success=True,
        new_user=False,
        session_data=session_data,
        request=request,
    )
    attach_session_from_jwt_data(redirect, session_data, request=request)
    return redirect


async def complete_profile_handler(
    body: CompleteProfileRequest,
    db: Session,
    current_user: AppUser,
):
    return await AuthService.complete_profile(
        db,
        current_user.email,
        body,
    )


@router.post(
    "/register",
    status_code=status.HTTP_200_OK
)
@limiter.limit("3/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    db: Session = Depends(get_db)
):
    await enforce_bot_protection(
        request,
        turnstile_token=body.turnstile_token,
        honeypot=body.website,
    )

    return await register_handler(
        body,
        db
    )


@router.post(
    "/register/otp/send",
    status_code=status.HTTP_200_OK,
)
@limiter.limit("3/minute")
async def send_register_otp(
    request: Request,
    body: RegisterRequest,
    db: Session = Depends(get_db),
):
    await enforce_bot_protection(
        request,
        turnstile_token=body.turnstile_token,
        honeypot=body.website,
    )
    return await AuthService.send_otp_for_registration(
        db,
        body.email,
        body.password,
    )


@router.post(
    "/register/otp/resend",
    status_code=status.HTTP_200_OK,
)
@limiter.limit("3/minute")
async def resend_register_otp(
    request: Request,
    body: OtpRequest,
):
    await enforce_bot_protection(
        request,
        turnstile_token=body.turnstile_token,
        honeypot=body.website,
    )
    return await AuthService.resend_otp_for_registration(body.email)


@router.post(
    "/register/otp/verify",
    status_code=status.HTTP_200_OK,
)
@limiter.limit("5/minute")
async def verify_register_otp(
    request: Request,
    body: RegisterOtpVerifyRequest,
    db: Session = Depends(get_db),
):
    await enforce_bot_protection(
        request,
        turnstile_token=body.turnstile_token,
        honeypot=body.website,
    )
    result = await AuthService.verify_otp_and_register(
        db,
        body.email,
        body.otp_code,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return _json_with_session_cookies(result, request=request)


@legacy_router.post(
    "/register",
    status_code=status.HTTP_200_OK
)
@limiter.limit("3/minute")
async def legacy_register(
    request: Request,
    body: RegisterRequest,
    db: Session = Depends(get_db)
):
    await enforce_bot_protection(
        request,
        turnstile_token=body.turnstile_token,
        honeypot=body.website,
    )

    return await register_handler(
        body,
        db
    )

@router.get(
    "/oauth/google/login",
    status_code=status.HTTP_302_FOUND,
)
@limiter.limit("10/minute")
async def google_oauth_login(request: Request):
    return await google_oauth_login_redirect_handler(request)


@legacy_router.get(
    "/oauth/google/login",
    status_code=status.HTTP_302_FOUND,
)
@limiter.limit("10/minute")
async def legacy_google_oauth_login(request: Request):
    return await google_oauth_login_redirect_handler(request)


@router.get(
    "/oauth/google/callback",
    status_code=status.HTTP_302_FOUND,
)
@limiter.limit("10/minute")
async def google_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
):
    return await google_oauth_callback_handler(
        request,
        db,
        code=code,
        state=state,
        error=error,
    )


@legacy_router.get(
    "/oauth/google/callback",
    status_code=status.HTTP_302_FOUND,
)
@limiter.limit("10/minute")
async def legacy_google_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
):
    return await google_oauth_callback_handler(
        request,
        db,
        code=code,
        state=state,
        error=error,
    )


# --- LinkedIn OAuth Routes ---
@router.get(
    "/oauth/linkedin/login",
    status_code=status.HTTP_302_FOUND,
)
@limiter.limit("10/minute")
async def linkedin_oauth_login(request: Request):
    return await linkedin_oauth_login_redirect_handler(request)


@legacy_router.get(
    "/oauth/linkedin/login",
    status_code=status.HTTP_302_FOUND,
)
@limiter.limit("10/minute")
async def legacy_linkedin_oauth_login(request: Request):
    return await linkedin_oauth_login_redirect_handler(request)


@router.get(
    "/oauth/linkedin/callback",
    status_code=status.HTTP_302_FOUND,
)
@limiter.limit("10/minute")
async def linkedin_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
):
    return await linkedin_oauth_callback_handler(
        request,
        db,
        code=code,
        state=state,
        error=error,
    )


@legacy_router.get(
    "/oauth/linkedin/callback",
    status_code=status.HTTP_302_FOUND,
)
@limiter.limit("10/minute")
async def legacy_linkedin_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
):
    return await linkedin_oauth_callback_handler(
        request,
        db,
        code=code,
        state=state,
        error=error,
    )


# --- Facebook OAuth Routes ---
@router.get(
    "/oauth/facebook/login",
    status_code=status.HTTP_302_FOUND,
)
@limiter.limit("10/minute")
async def facebook_oauth_login(request: Request):
    return await facebook_oauth_login_redirect_handler(request)


@legacy_router.get(
    "/oauth/facebook/login",
    status_code=status.HTTP_302_FOUND,
)
@limiter.limit("10/minute")
async def legacy_facebook_oauth_login(request: Request):
    return await facebook_oauth_login_redirect_handler(request)


@router.get(
    "/oauth/facebook/callback",
    status_code=status.HTTP_302_FOUND,
)
@limiter.limit("10/minute")
async def facebook_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
):
    return await facebook_oauth_callback_handler(
        request,
        db,
        code=code,
        state=state,
        error=error,
    )


@legacy_router.get(
    "/oauth/facebook/callback",
    status_code=status.HTTP_302_FOUND,
)
@limiter.limit("10/minute")
async def legacy_facebook_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
):
    return await facebook_oauth_callback_handler(
        request,
        db,
        code=code,
        state=state,
        error=error,
    )


# --- Instagram OAuth Routes ---
@router.get(
    "/oauth/instagram/login",
    status_code=status.HTTP_302_FOUND,
)
@limiter.limit("10/minute")
async def instagram_oauth_login(request: Request):
    return await instagram_oauth_login_redirect_handler(request)


@legacy_router.get(
    "/oauth/instagram/login",
    status_code=status.HTTP_302_FOUND,
)
@limiter.limit("10/minute")
async def legacy_instagram_oauth_login(request: Request):
    return await instagram_oauth_login_redirect_handler(request)


@router.get(
    "/oauth/instagram/callback",
    status_code=status.HTTP_302_FOUND,
)
@limiter.limit("10/minute")
async def instagram_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
):
    return await instagram_oauth_callback_handler(
        request,
        db,
        code=code,
        state=state,
        error=error,
    )


@legacy_router.get(
    "/oauth/instagram/callback",
    status_code=status.HTTP_302_FOUND,
)
@limiter.limit("10/minute")
async def legacy_instagram_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
):
    return await instagram_oauth_callback_handler(
        request,
        db,
        code=code,
        state=state,
        error=error,
    )


@router.post(
    "/login",
    status_code=status.HTTP_200_OK
)
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: Session = Depends(get_db)
):
    await enforce_bot_protection(
        request,
        turnstile_token=body.turnstile_token,
        honeypot=body.website,
    )

    result = await login_handler(
        body,
        db,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        device_name=None,
    )
    return _json_with_session_cookies(result, request=request)


@router.post(
    "/refresh",
    status_code=status.HTTP_200_OK
)
@limiter.limit("20/minute")
async def refresh(
    request: Request,
    body: RefreshTokenRequest,
    db: Session = Depends(get_db)
):

    return await refresh_handler(
        request,
        body,
        db,
    )


@legacy_router.post(
    "/refresh",
    status_code=status.HTTP_200_OK
)
@limiter.limit("20/minute")
async def legacy_refresh(
    request: Request,
    body: RefreshTokenRequest,
    db: Session = Depends(get_db),
):

    return await refresh_handler(
        request,
        body,
        db,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK
)
async def logout(
    http_request: Request,
    body: LogoutRequest,
    db: Session = Depends(get_db),
):

    return await logout_handler(
        http_request,
        body,
        db,
    )


@legacy_router.post(
    "/logout",
    status_code=status.HTTP_200_OK
)
async def legacy_logout(
    http_request: Request,
    body: LogoutRequest,
    db: Session = Depends(get_db),
):

    return await logout_handler(
        http_request,
        body,
        db,
    )


@router.post(
    "/forgot-password",
    status_code=status.HTTP_200_OK,
)
@limiter.limit(FORGOT_PASSWORD_RATE_LIMIT)
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    await enforce_bot_protection(
        request,
        turnstile_token=body.turnstile_token,
        honeypot=body.website,
    )

    return await forgot_password_handler(
        body,
        db,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


@legacy_router.post(
    "/forgot-password",
    status_code=status.HTTP_200_OK,
)
@limiter.limit(FORGOT_PASSWORD_RATE_LIMIT)
async def legacy_forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    await enforce_bot_protection(
        request,
        turnstile_token=body.turnstile_token,
        honeypot=body.website,
    )

    return await forgot_password_handler(
        body,
        db,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


@router.post(
    "/reset-password",
    status_code=status.HTTP_200_OK,
)
@limiter.limit(RESET_PASSWORD_RATE_LIMIT)
async def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
):

    return await reset_password_handler(body, db)


@legacy_router.post(
    "/reset-password",
    status_code=status.HTTP_200_OK,
)
@limiter.limit(RESET_PASSWORD_RATE_LIMIT)
async def legacy_reset_password(
    request: Request,
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
):

    return await reset_password_handler(body, db)


@router.post(
    "/resend-verification",
    status_code=status.HTTP_200_OK
)
@limiter.limit("3/minute")
async def resend_verification(
    request: Request,
    body: ResendVerificationRequest,
    db: Session = Depends(get_db)
):
    await enforce_bot_protection(
        request,
        turnstile_token=body.turnstile_token,
        honeypot=body.website,
    )

    return await (
        resend_verification_handler(
            body,
            db
        )
    )


@legacy_router.post(
    "/resend-verification",
    status_code=status.HTTP_200_OK
)
@limiter.limit("3/minute")
async def legacy_resend_verification(
    request: Request,
    body: ResendVerificationRequest,
    db: Session = Depends(get_db)
):

    return await (
        resend_verification_handler(
            body,
            db
        )
    )

@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    operation_id="auth_get_my_profile",
)
async def me(
    request: Request,
    current_user: AppUser = Depends(
        get_current_user
    ),
):
    request_payload = await request_payload_for_logging(request)
    try:
        payload = AuthService.user_profile_payload(current_user)
        logger.info(
            "Auth Me response schema ok user_id=%s email=%s role=%s",
            payload.get("id"),
            payload.get("email"),
            payload.get("role"),
        )
        return {
            "success": True,
            "message": "Profile fetched successfully",
            "data": payload,
        }
    except Exception as exc:
        await log_route_exception(logger, "Auth Me", request, exc, payload=request_payload)
        raise


@router.get(
    "/mee",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def mee_compat(
    current_user: AppUser = Depends(get_current_user),
):
    """Java GET /api/v1/auth/mee — flat user payload (typo preserved for compatibility)."""
    payload = AuthService.user_profile_payload(current_user)
    return {
        "id": payload["id"],
        "email": payload["email"],
        "role": payload["role"],
        "emailVerified": payload["emailVerified"],
    }


@router.put(
    "/profile/update",
    status_code=status.HTTP_200_OK,
    operation_id="auth_update_profile",
)
@limiter.limit("20/minute")
async def update_profile(
    request: Request,
    body: UpdateProfileRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    """Java PUT /api/v1/auth/profile/update — partial profile fields."""
    return await ProfileService.update_profile(db, current_user, body)


@router.post(
    "/complete-profile",
    status_code=status.HTTP_200_OK,
    operation_id="auth_complete_profile",
)
@limiter.limit("10/minute")
async def complete_profile(
    request: Request,
    body: CompleteProfileRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    return await complete_profile_handler(body, db, current_user)


@legacy_router.post(
    "/complete-profile",
    status_code=status.HTTP_200_OK,
)
@limiter.limit("10/minute")
async def legacy_complete_profile(
    request: Request,
    body: CompleteProfileRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    return await complete_profile_handler(body, db, current_user)


@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
)
@limiter.limit(CHANGE_PASSWORD_RATE_LIMIT)
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):

    return await change_password_handler(
        body,
        db,
        current_user,
        request=request,
    )


@legacy_router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
)
@limiter.limit(CHANGE_PASSWORD_RATE_LIMIT)
async def legacy_change_password(
    request: Request,
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):

    return await change_password_handler(
        body,
        db,
        current_user,
        request=request,
    )


@router.post(
    "/set-password",
    status_code=status.HTTP_200_OK,
)
@limiter.limit(CHANGE_PASSWORD_RATE_LIMIT)
async def set_password(
    request: Request,
    body: SetPasswordRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):

    return await set_password_handler(
        body,
        db,
        current_user,
        request=request,
    )


@legacy_router.post(
    "/set-password",
    status_code=status.HTTP_200_OK,
)
@limiter.limit(CHANGE_PASSWORD_RATE_LIMIT)
async def legacy_set_password(
    request: Request,
    body: SetPasswordRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):

    return await set_password_handler(
        body,
        db,
        current_user,
        request=request,
    )


if settings.ENVIRONMENT != "production":

    @router.get(
        "/admin-test",
        status_code=status.HTTP_200_OK
    )
    async def admin_test(

        current_user: AppUser = Depends(
            require_role(
                ["ADMIN"]
            )
        )
    ):

        return {
            "success": True,
            "message": (
                "Admin access granted"
            )
        }



@legacy_router.post(
    "/login",
    status_code=status.HTTP_200_OK
)
@limiter.limit("5/minute")
async def legacy_login(
    request: Request,
    body: LoginRequest,
    db: Session = Depends(get_db)
):
    await enforce_bot_protection(
        request,
        turnstile_token=body.turnstile_token,
        honeypot=body.website,
    )

    result = await login_handler(
        body,
        db,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        device_name=None,
    )
    return _json_with_session_cookies(result, request=request)


@router.get(
    "/verify-email",
    status_code=status.HTTP_302_FOUND,
)
async def verify_email(
    request: Request,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    return await verify_email_handler(request, token, db)


@legacy_router.get(
    "/verify-email",
    status_code=status.HTTP_302_FOUND,
)
async def legacy_verify_email(
    request: Request,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    return await verify_email_handler(request, token, db)

@router.post("/otp/send", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
async def send_otp(
    request: Request,
    body: OtpRequest,
    db: Session = Depends(get_db),
):
    await enforce_bot_protection(
        request,
        turnstile_token=body.turnstile_token,
        honeypot=body.website,
    )
    return await AuthService.send_otp_for_login(db, body.email)


@router.post("/otp/verify", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def verify_otp(
    request: Request,
    body: OtpVerify,
    db: Session = Depends(get_db),
):
    await enforce_bot_protection(
        request,
        turnstile_token=body.turnstile_token,
        honeypot=body.website,
    )
    result = await AuthService.verify_otp_and_login(
        db, body.email, body.otp_code,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return _json_with_session_cookies(result, request=request)


@router.post("/otp/resend", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
async def resend_otp(
    request: Request,
    body: OtpRequest,
    db: Session = Depends(get_db),
):
    await enforce_bot_protection(
        request,
        turnstile_token=body.turnstile_token,
        honeypot=body.website,
    )
    return await AuthService.send_otp_for_login(db, body.email)


@profile_compat_router.get("/me", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
async def profile_me_redirect() -> RedirectResponse:
    return RedirectResponse(
        url="/api/v1/auth/me",
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@profile_compat_router.put("/complete", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
async def profile_complete_compat(
    request: Request,
    body: CompleteProfileRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    return await complete_profile_handler(body, db, current_user)
