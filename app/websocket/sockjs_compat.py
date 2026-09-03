"""
Lightweight SockJS/STOMP compatibility endpoints.

Purpose:
- eliminate noisy /ws/info 404s from SockJS clients
- accept basic STOMP CONNECT/SUBSCRIBE/DISCONNECT frames so frontend
  WebSocket clients don't hard-fail during pages that don't require
  real-time updates for core workflows.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

router = APIRouter(tags=["SockJS Compatibility"])

# /ws/info and WebSocket transport are provided by stomp_sockjs_compat.

@router.get("/ws")
@router.get("/ws/")
def sockjs_root() -> JSONResponse:
    return JSONResponse({"ok": True, "transport": "sockjs"})


@router.post("/ws")
@router.post("/ws/")
@router.options("/ws")
@router.options("/ws/")
def sockjs_root_noop() -> Response:
    return Response(status_code=204)


@router.get("/ws/iframe.html")
@router.get("/ws/iframe{suffix:path}")
def sockjs_iframe(suffix: str = "") -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='UTF-8'></head>"
        "<body><script>document.domain=document.domain;</script></body></html>"
    )


# WebSocket transport is handled by stomp_sockjs_compat (raw STOMP frames).


@router.get("/ws/{server_id}/{session_id}/xhr_streaming")
@router.post("/ws/{server_id}/{session_id}/xhr_streaming")
def sockjs_xhr_streaming(server_id: str, session_id: str) -> PlainTextResponse:
    return PlainTextResponse("o\n", media_type="application/javascript")


@router.post("/ws/{server_id}/{session_id}/xhr_send")
def sockjs_xhr_send(
    server_id: str,
    session_id: str,
    request: Request,
) -> PlainTextResponse:
    return PlainTextResponse("ok", media_type="text/plain")


@router.get("/ws/{server_id}/{session_id}/xhr")
@router.post("/ws/{server_id}/{session_id}/xhr")
def sockjs_xhr(server_id: str, session_id: str) -> PlainTextResponse:
    return PlainTextResponse("o\n", media_type="application/javascript")


@router.get("/ws/{server_id}/{session_id}/eventsource")
def sockjs_eventsource(server_id: str, session_id: str) -> PlainTextResponse:
    return PlainTextResponse("data: o\n\n", media_type="text/event-stream")


@router.get("/ws/{server_id}/{session_id}/jsonp")
@router.post("/ws/{server_id}/{session_id}/jsonp")
@router.get("/ws/{server_id}/{session_id}/jsonp_send")
@router.post("/ws/{server_id}/{session_id}/jsonp_send")
def sockjs_jsonp(server_id: str, session_id: str) -> PlainTextResponse:
    return PlainTextResponse("/**/callback('o');\r\n", media_type="application/javascript")


@router.api_route("/ws/{path:path}", methods=["GET", "POST", "OPTIONS"])
def sockjs_unknown_probe(path: str) -> Response:
    if path.endswith("/websocket"):
        return Response(status_code=426)
    return Response(status_code=204)
