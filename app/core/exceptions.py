import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import DBAPIError, OperationalError

from app.core.config import settings
from app.service.auth.auth_exceptions import (
    AuthException,
    EmailNotVerifiedException,
)

logger = logging.getLogger(__name__)

_DB_UNAVAILABLE_MESSAGE = (
    "Database is unavailable. For local development, ensure DATABASE_URL_DIRECT is reachable "
    "or run .\\run_rds_tunnel.ps1 then restart .\\run_dev.ps1 (or use .\\run_local.ps1)."
)


def _is_db_connection_error(exc: BaseException) -> bool:
    if isinstance(exc, OperationalError):
        return True
    if isinstance(exc, DBAPIError) and getattr(exc, "connection_invalidated", False):
        return True
    if isinstance(exc, (ConnectionRefusedError, OSError)):
        return True

    cause = exc
    seen: set[int] = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, OperationalError):
            return True
        if isinstance(cause, (ConnectionRefusedError, OSError)):
            return True
        cause = getattr(cause, "__cause__", None) or getattr(cause, "orig", None)

    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "connection refused",
            "refused the network connection",
            "could not connect",
            "server closed the connection",
            "connection timed out",
            "timeout expired",
            "no connection to the server",
            "actively refused",
            "winerror 10061",
            "winerror 1225",
            "winerror 10060",
            "could not translate host name",
            "name or service not known",
        )
    )


def _database_unavailable_response() -> JSONResponse:
    message = _DB_UNAVAILABLE_MESSAGE
    if settings.ENVIRONMENT == "production":
        message = "Service temporarily unavailable. Please try again shortly."
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "success": False,
            "message": message,
            "error": message,
            "data": None,
        },
    )


class AppException(Exception):

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        *,
        code: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


def register_exception_handlers(
    app: FastAPI
):

    @app.exception_handler(AuthException)
    async def auth_exception_handler(
        request: Request,
        exc: AuthException,
    ):
        content = {
            "success": False,
            "error": exc.message,
        }
        if isinstance(exc, EmailNotVerifiedException):
            content["emailVerified"] = False

        return JSONResponse(
            status_code=exc.status_code,
            content=content,
        )

    @app.exception_handler(AppException)
    async def app_exception_handler(
        request: Request,
        exc: AppException
    ):

        content = {
            "success": False,
            "message": exc.message,
            "error": exc.message,
            "data": None,
        }
        if getattr(exc, "code", None):
            content["code"] = exc.code
        failed = getattr(exc, "failed_domains", None)
        if failed:
            content["failedDomains"] = failed
        content["detail"] = exc.message

        return JSONResponse(
            status_code=exc.status_code,
            content=content,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request,
        exc: HTTPException,
    ):
        detail = exc.detail
        status_titles = {
            400: "Validation Error",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Resource Not Found",
            422: "Invalid Request",
            500: "Unexpected Server Error"
        }
        fallback = status_titles.get(exc.status_code, "Request failed")

        if isinstance(detail, str):
            # Use fallback if the detail is just a generic status phrase (like FastAPI does by default)
            if detail in ("Bad Request", "Not Found", "Method Not Allowed") and exc.status_code in status_titles:
                message = fallback
            else:
                message = detail
        elif isinstance(detail, dict):
            message = str(
                detail.get("error")
                or detail.get("message")
                or detail.get("detail")
                or fallback
            )
        else:
            message = fallback

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "message": message,
                "error": message,
                "detail": detail if isinstance(detail, str) else str(detail),
                "data": None,
            }
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError
    ):

        errors = []

        for error in exc.errors():

            errors.append({
                "field": ".".join(
                    map(str, error["loc"])
                ),
                "message": error["msg"]
            })

        message = "Validation failed"
        if errors:
            message = f"{message}: {errors[0]['message']}"

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "success": False,
                "message": message,
                "error": message,
                "data": errors
            }
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(
        request: Request,
        exc: RateLimitExceeded
    ):

        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "success": False,
                "message": "Too many requests. Please slow down and try again.",
                "data": None
            }
        )

    @app.exception_handler(OperationalError)
    async def database_operational_error_handler(
        request: Request,
        exc: OperationalError,
    ):
        logger.error(
            "Database operational error request_id=%s path=%s: %s",
            getattr(request.state, "request_id", None),
            request.url.path,
            exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return _database_unavailable_response()

    @app.exception_handler(Exception)
    async def global_exception_handler(
        request: Request,
        exc: Exception
    ):
        request_id = getattr(request.state, "request_id", None)
        user = getattr(request.state, "user", None)
        user_id = getattr(user, "id", "anonymous") if user else "anonymous"

        if _is_db_connection_error(exc):
            logger.error(
                "Database connection error request_id=%s user_id=%s path=%s exc_type=%s: %s",
                request_id,
                user_id,
                request.url.path,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return _database_unavailable_response()

        logger.error(
            "Unhandled exception request_id=%s user_id=%s path=%s exc_type=%s: %s",
            request_id,
            user_id,
            request.url.path,
            type(exc).__name__,
            exc,
            exc_info=True,
        )

        detail = "Unexpected Server Error"
        if settings.ENVIRONMENT != "production":
            detail = f"{type(exc).__name__}: {str(exc)}"

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": detail,
                "error": detail,
                "detail": detail,
                "data": None
            }
        )
