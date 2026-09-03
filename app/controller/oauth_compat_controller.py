"""Spring Security–compatible OAuth entry points for the existing React app."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.controller.auth.auth_controller import (
    google_oauth_callback_handler,
    google_oauth_login_redirect_handler,
    linkedin_oauth_callback_handler,
    linkedin_oauth_login_redirect_handler,
    facebook_oauth_callback_handler,
    facebook_oauth_login_redirect_handler,
    instagram_oauth_callback_handler,
    instagram_oauth_login_redirect_handler,
)
from app.core.database import get_db

router = APIRouter(tags=["OAuth Compatibility"])


@router.get("/oauth2/authorization/google")
async def spring_google_oauth_login(
    request: Request,
    return_origin: str | None = Query(None),
):
    return await google_oauth_login_redirect_handler(
        request,
        return_origin=return_origin,
    )


@router.get("/login/oauth2/code/google")
async def spring_google_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
):
    """Legacy Spring redirect URI — forwards to the FastAPI Google callback."""
    return await google_oauth_callback_handler(
        request,
        db,
        code=code,
        state=state,
        error=error,
    )


@router.get("/oauth2/authorization/linkedin")
async def spring_linkedin_oauth_login(
    request: Request,
    return_origin: str | None = Query(None),
):
    return await linkedin_oauth_login_redirect_handler(
        request,
        return_origin=return_origin,
    )


@router.get("/login/oauth2/code/linkedin")
async def spring_linkedin_oauth_callback(
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


@router.get("/oauth2/authorization/facebook")
async def spring_facebook_oauth_login(
    request: Request,
    return_origin: str | None = Query(None),
):
    return await facebook_oauth_login_redirect_handler(
        request,
        return_origin=return_origin,
    )


@router.get("/login/oauth2/code/facebook")
async def spring_facebook_oauth_callback(
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


@router.get("/oauth2/authorization/instagram")
async def spring_instagram_oauth_login(
    request: Request,
    return_origin: str | None = Query(None),
):
    return await instagram_oauth_login_redirect_handler(
        request,
        return_origin=return_origin,
    )


@router.get("/login/oauth2/code/instagram")
async def spring_instagram_oauth_callback(
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
