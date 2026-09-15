"""HTTP middleware that renders unhandled exceptions inside the CORS layer.

Starlette runs ``@app.exception_handler(Exception)`` from ``ServerErrorMiddleware``,
which wraps the whole stack and therefore sits outside ``CORSMiddleware``. A 500
built there never receives ``Access-Control-Allow-Origin``, so browsers report a
CORS failure and hide the real status and body. Handling the exception here keeps
the response inside the CORS layer, where the headers are still applied.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.exceptions import build_unhandled_exception_response


class UnhandledExceptionMiddleware:
    """Convert unhandled route exceptions into the standard JSON 500 body."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            if response_started:
                # Headers are already on the wire; let ServerErrorMiddleware abort.
                raise
            response = build_unhandled_exception_response(Request(scope, receive), exc)
            await response(scope, receive, send)
