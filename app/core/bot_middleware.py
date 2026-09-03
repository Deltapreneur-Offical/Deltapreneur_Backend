"""Middleware that blocks obvious bots on sensitive public POST endpoints."""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.bot_protection import is_blocked_user_agent, is_protected_post_path

logger = logging.getLogger(__name__)


class BotGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "POST" and is_protected_post_path(request.url.path):
            user_agent = request.headers.get("user-agent")
            if is_blocked_user_agent(user_agent):
                logger.warning(
                    "Blocked bot request path=%s ua=%s",
                    request.url.path,
                    user_agent,
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "success": False,
                        "message": "Request blocked.",
                        "data": None,
                    },
                )

        return await call_next(request)
