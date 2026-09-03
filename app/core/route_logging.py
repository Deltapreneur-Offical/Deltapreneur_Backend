"""Helpers for route-level diagnostic logging."""

from __future__ import annotations

import logging
import traceback
from typing import Any

from fastapi import Request


async def request_payload_for_logging(request: Request) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "method": request.method,
        "path": request.url.path,
        "query_params": dict(request.query_params),
        "path_params": dict(request.path_params),
    }
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        try:
            payload["body"] = await request.json()
        except Exception:
            body = await request.body()
            payload["body"] = body.decode("utf-8", errors="replace") if body else None
    return payload


async def log_route_exception(
    logger: logging.Logger,
    endpoint_name: str,
    request: Request,
    exc: Exception,
    *,
    payload: Any | None = None,
) -> None:
    if payload is None:
        payload = await request_payload_for_logging(request)
    logger.exception(
        "%s failed\nrequest_payload=%r\nexception_type=%s\nexception_message=%s\ntraceback=%s",
        endpoint_name,
        payload,
        type(exc).__name__,
        str(exc),
        traceback.format_exc(),
    )
