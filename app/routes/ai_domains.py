"""AI Domains API route."""

from __future__ import annotations

import logging
import time
import traceback

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_optional_current_user
from app.core.exceptions import AppException
from app.core.route_logging import log_route_exception, request_payload_for_logging
from app.entity.user.app_user import AppUser
from app.schemas.ai_domains import AIDomainGenerateRequest, AIDomainGenerateResponse
from app.service.domain.domain_registration_service import DomainRegistrationService
from app.services.ai_domain_analytics import ai_domain_analytics
from app.services.ai_domain_engine import build_ai_domain_engine
from app.services.ai_domain_rate_limiter import ai_domain_rate_limiter

router = APIRouter(prefix="/api/ai-domains", tags=["AI Domains"])
v1_router = APIRouter(prefix="/api/v1/ai-domains", tags=["AI Domains"])
logger = logging.getLogger(__name__)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": message,
            },
        },
    )


def _code_for_app_exception(exc: AppException) -> str:
    if exc.status_code == 400:
        return "INVALID_INPUT"
    if exc.status_code == 429:
        return "RATE_LIMITED"
    if exc.status_code == 503:
        return "OPENROUTER_ERROR"
    return "AI_DOMAIN_ERROR"


async def _read_payload(request: Request) -> AIDomainGenerateRequest:
    raw = None
    try:
        raw = await request.json()
    except Exception as exc:
        logger.exception(
            "AI Domains payload read failed\nrequest_payload=%r\nexception_type=%s\nexception_message=%s\ntraceback=%s",
            {"method": request.method, "path": request.url.path},
            type(exc).__name__,
            str(exc),
            traceback.format_exc(),
        )
        raise AppException("Invalid JSON request body.", status_code=400) from exc
    try:
        payload = AIDomainGenerateRequest.model_validate(raw)
        logger.info(
            "AI Domains payload received idea_length=%s payload_keys=%s",
            len(payload.idea),
            sorted(raw.keys()) if isinstance(raw, dict) else type(raw).__name__,
        )
        return payload
    except ValidationError as exc:
        message = "Invalid business idea."
        if exc.errors():
            message = str(exc.errors()[0].get("msg") or message)
        logger.exception(
            "AI Domains payload validation failed\nrequest_payload=%r\nexception_type=%s\nexception_message=%s\ntraceback=%s",
            raw,
            type(exc).__name__,
            str(exc),
            traceback.format_exc(),
        )
        raise AppException(message, status_code=400) from exc


async def _generate(
    request: Request,
    db: AsyncSession,
    current_user: AppUser | None,
) -> AIDomainGenerateResponse:
    payload = await _read_payload(request)
    started = time.perf_counter()
    remaining = await ai_domain_rate_limiter.check(request, current_user)
    guest_session = request.headers.get("x-guest-session") or request.cookies.get("guest_session")
    engine = build_ai_domain_engine(DomainRegistrationService(db))
    try:
        response = await engine.generate(
            payload.idea,
            request_id=getattr(request.state, "request_id", None),
        )
    except AppException as exc:
        await ai_domain_analytics.track_search(
            request=request,
            idea=payload.idea,
            names=[],
            user=current_user,
            guest_session=guest_session,
            success=False,
            failure_reason=exc.message,
        )
        raise

    response.rate_limit_remaining = remaining
    elapsed_ms = (time.perf_counter() - started) * 1000
    await ai_domain_analytics.track_search(
        request=request,
        idea=payload.idea,
        names=[item.name for item in response.results],
        user=current_user,
        guest_session=guest_session,
        success=True,
        cached=response.cached,
        response_time_ms=elapsed_ms,
    )
    return response


async def _generate_or_error(
    request: Request,
    db: AsyncSession,
    current_user: AppUser | None,
) -> object:
    request_payload = await request_payload_for_logging(request)
    try:
        response = await _generate(request, db, current_user)
        logger.info(
            "AI Domains response success=%s idea=%r results_count=%s cached=%s category=%s names=%s",
            response.success,
            response.idea,
            len(response.results),
            response.cached,
            response.category,
            [item.name for item in response.results],
        )
        return response
    except AppException as exc:
        await log_route_exception(logger, "AI Domains", request, exc, payload=request_payload)
        return _error_response(
            exc.status_code,
            _code_for_app_exception(exc),
            exc.message,
        )
    except Exception as exc:
        await log_route_exception(logger, "AI Domains", request, exc, payload=request_payload)
        raise


@router.post("/generate", response_model=None)
async def generate_ai_domains(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: AppUser | None = Depends(get_optional_current_user),
) -> object:
    return await _generate_or_error(request, db, current_user)


@v1_router.post("/generate", response_model=None)
async def generate_ai_domains_v1(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: AppUser | None = Depends(get_optional_current_user),
) -> object:
    return await _generate_or_error(request, db, current_user)
