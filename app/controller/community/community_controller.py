import logging
import traceback
import uuid
from urllib.parse import quote as url_quote

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, get_optional_current_user
from app.entity.user.app_user import AppUser
from app.model.common.api_response import ApiResponse
from app.model.community.community_create_request import CommunityCreateRequest
from app.model.community.community_update_request import CommunityUpdateRequest
from app.entity.likes.like_type import LikeType
from app.service.community.community_service import CommunityService
from app.service.community.creator_follow_service import CreatorFollowService
from app.service.likes.like_service import LikeService


router = APIRouter(tags=["Creator"])
logger = logging.getLogger(__name__)


@router.get("/test", response_model=ApiResponse)
def test_community():
    redirect_uri = settings.resolved_linkedin_redirect_uri()
    return ApiResponse(
        success=True,
        message="Creator module is connected successfully",
        data={
            "module": "community",
            "status": "ready",
            "linkedinConfigured": bool(
                settings.LINKEDIN_CLIENT_ID
                and settings.LINKEDIN_CLIENT_SECRET
                and redirect_uri
            ),
            "linkedinRedirectUri": redirect_uri,
        },
    )


@router.get("/all", response_model=ApiResponse)
def get_all_profiles(
    request: Request,
    db: Session = Depends(get_db),
    featured_only: bool = Query(default=False),
    page_size: int | None = Query(default=None, ge=1, le=500),
):
    try:
        profiles = CommunityService.get_all_profiles(
            db,
            featured_only=featured_only,
            page_size=page_size,
        )
        LikeService.attach_like_counts(db, LikeType.COMMUNITY.value, profiles)
        CreatorFollowService.attach_follow_counts(db, profiles)

        logger.info(
            "Creator All response schema ok profiles_count=%s",
            len(profiles) if hasattr(profiles, "__len__") else "unknown",
        )
        return ApiResponse(
            success=True,
            message="Creator profiles fetched successfully",
            data=profiles,
        )
    except Exception as exc:
        payload = {
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "path_params": dict(request.path_params),
        }
        logger.exception(
            "Creator All failed\nrequest_payload=%r\nexception_type=%s\nexception_message=%s\ntraceback=%s",
            payload,
            type(exc).__name__,
            str(exc),
            traceback.format_exc(),
        )
        raise


@router.post("/my", response_model=ApiResponse)
def create_my_profile(
    request: CommunityCreateRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    profile = CommunityService.create_my_profile(
        db=db,
        request=request,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Creator profile created successfully",
        data=profile,
    )


@router.get("/my", response_model=ApiResponse)
def get_my_profile(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    profile = CommunityService.get_my_profile(
        db=db,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="My creator profile fetched successfully",
        data=profile,
    )


@router.get("/linkedin/auth")
def linkedin_auth_url(
    request: Request,
    return_origin: str | None = None,
    current_user: AppUser = Depends(get_current_user),
):
    from app.service.community import linkedin_oauth

    redirect_uri = linkedin_oauth.resolve_linkedin_redirect_uri(
        request_host=request.headers.get("x-forwarded-host") or request.headers.get("host"),
        request_scheme=request.headers.get("x-forwarded-proto") or request.url.scheme,
    )
    linkedin_oauth.runtime_debug(
        f"LinkedIn auth URL requested by user={current_user.email} id={current_user.id} "
        f"return_origin={return_origin} redirect_uri={redirect_uri}",
    )
    url = CommunityService.get_linkedin_authorization_url(
        current_user=current_user,
        redirect_uri=redirect_uri,
        return_origin=return_origin,
    )
    # Keep ApiResponse compatibility while also exposing the URL at top level
    # for the React LinkedIn button.
    return {
        "success": True,
        "message": "LinkedIn authorization URL generated successfully",
        "data": {"url": url},
        "url": url,
        "authUrl": url,
    }


@router.get("/linkedin/sync-photo/auth")
def linkedin_sync_photo_auth_url(
    request: Request,
    return_origin: str | None = None,
    current_user: AppUser = Depends(get_current_user),
):
    """Generate a LinkedIn OAuth URL that will only update the user's profile photo."""
    from app.service.community import linkedin_oauth

    redirect_uri = linkedin_oauth.resolve_linkedin_redirect_uri(
        request_host=request.headers.get("x-forwarded-host") or request.headers.get("host"),
        request_scheme=request.headers.get("x-forwarded-proto") or request.url.scheme,
    )
    linkedin_oauth.runtime_debug(
        f"LinkedIn sync-photo auth URL requested by user={current_user.email} "
        f"id={current_user.id} return_origin={return_origin} redirect_uri={redirect_uri}",
    )
    url = CommunityService.get_sync_photo_authorization_url(
        current_user=current_user,
        redirect_uri=redirect_uri,
        return_origin=return_origin,
    )
    return {
        "success": True,
        "message": "LinkedIn sync-photo authorization URL generated successfully",
        "data": {"url": url},
        "url": url,
        "authUrl": url,
    }


def _linkedin_frontend_redirect(
    *,
    linkedin: str | None = None,
    profile_id=None,
    profile_url_imported: bool | None = None,
    error: str | None = None,
    frontend_base: str | None = None,
):
    base_origin = (frontend_base or settings.FRONTEND_BASE_URL).rstrip("/")
    base = f"{base_origin}/creator"
    if linkedin == "success" and profile_id is not None:
        query = f"linkedin=success&profileId={profile_id}"
        if profile_url_imported is False:
            query += "&linkedin_url=missing"
        return RedirectResponse(
            f"{base}?{query}",
            status_code=302,
        )
    if linkedin == "photo_synced" and profile_id is not None:
        return RedirectResponse(
            f"{base}?linkedin=photo_synced&profileId={profile_id}",
            status_code=302,
        )
    message = url_quote(error or "LinkedIn failed", safe="")
    return RedirectResponse(
        f"{base}?linkedin_error={message}",
        status_code=302,
    )


@router.get("/linkedin/callback")
async def linkedin_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    from app.core.oauth_state import verify_oauth_state
    if state and verify_oauth_state(state, provider="linkedin"):
        from app.controller.auth.auth_controller import linkedin_oauth_callback_handler
        return await linkedin_oauth_callback_handler(
            request,
            db,
            code=code,
            state=state,
            error=error,
        )

    _, return_origin = CommunityService._parse_linkedin_oauth_state(state or "")

    if error:
        message = (error_description or error or "LinkedIn authorization was denied").strip()
        logger.warning("LinkedIn OAuth denied: %s", message)
        return _linkedin_frontend_redirect(error=message, frontend_base=return_origin)

    if not code or not state:
        logger.warning("LinkedIn callback missing code or state")
        return _linkedin_frontend_redirect(
            error="LinkedIn authorization was cancelled or incomplete. Please try again.",
            frontend_base=return_origin,
        )

    from app.service.community import linkedin_oauth

    linkedin_oauth.runtime_debug(
        f"LinkedIn callback received code={'yes' if code else 'no'} state={state[:80]}",
    )

    # Check if this callback is for a sync-photo action.
    action = CommunityService._parse_linkedin_oauth_state_action(state)

    if action == "sync_photo":
        try:
            profile_id = CommunityService.sync_profile_photo_from_linkedin(
                db=db,
                code=code,
                state=state,
            )
            logger.info("LinkedIn sync-photo succeeded for profile_id=%s", profile_id)
            linkedin_oauth.runtime_debug(
                f"LinkedIn sync-photo callback SUCCESS profile_id={profile_id}",
            )
            return _linkedin_frontend_redirect(
                linkedin="photo_synced",
                profile_id=profile_id,
                frontend_base=return_origin,
            )
        except Exception as exc:
            logger.exception("LinkedIn sync-photo callback failed")
            linkedin_oauth.runtime_debug(f"LinkedIn sync-photo callback FAILED error={exc}")
            return _linkedin_frontend_redirect(
                error=str(exc) or "Unable to sync profile photo. Please try again.",
                frontend_base=return_origin,
            )

    try:
        profile_id, profile_url_imported = CommunityService.handle_linkedin_oauth_callback(
            db=db,
            code=code,
            state=state,
        )
        logger.info(
            "LinkedIn OAuth succeeded for profile_id=%s profile_url_imported=%s",
            profile_id,
            profile_url_imported,
        )
        linkedin_oauth.runtime_debug(
            f"LinkedIn callback SUCCESS profile_id={profile_id} profile_url_imported={profile_url_imported}",
        )
        return _linkedin_frontend_redirect(
            linkedin="success",
            profile_id=profile_id,
            profile_url_imported=profile_url_imported,
            frontend_base=return_origin,
        )

    except Exception as exc:
        logger.exception("LinkedIn OAuth callback failed")
        from app.service.community import linkedin_oauth

        linkedin_oauth.runtime_debug(f"LinkedIn callback FAILED error={exc}")
        return _linkedin_frontend_redirect(
            error=str(exc) or "LinkedIn failed",
            frontend_base=return_origin,
        )


@router.post("/follow/bulk-status", response_model=ApiResponse)
def get_bulk_follow_status(
    community_ids: list[str] = Body(..., embed=False),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    result = CreatorFollowService.get_bulk_status(
        db,
        community_ids=community_ids,
        current_user=current_user,
    )
    return ApiResponse(
        success=True,
        message="Creator follow status fetched successfully",
        data=result,
    )


@router.post("/follow/bulk-counts", response_model=ApiResponse)
def get_bulk_follow_counts(
    community_ids: list[str] = Body(..., embed=False),
    db: Session = Depends(get_db),
):
    result = CreatorFollowService.get_bulk_counts(db, community_ids=community_ids)
    return ApiResponse(
        success=True,
        message="Creator follower counts fetched successfully",
        data=result,
    )


@router.post("/{community_id}/follow/toggle", response_model=ApiResponse)
def toggle_creator_follow(
    community_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    result = CreatorFollowService.toggle_follow(
        db,
        community_id=community_id,
        current_user=current_user,
    )
    return ApiResponse(
        success=True,
        message="Creator follow status updated successfully",
        data=result,
    )


@router.get("/{community_id}/follow/status", response_model=ApiResponse)
def get_creator_follow_status(
    community_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    result = CreatorFollowService.get_follow_status(
        db,
        community_id=community_id,
        current_user=current_user,
    )
    return ApiResponse(
        success=True,
        message="Creator follow status fetched successfully",
        data=result,
    )


@router.get("/{community_id}", response_model=ApiResponse)
def get_profile_by_id(
    community_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser | None = Depends(get_optional_current_user),
):
    try:
        profile = CommunityService.get_profile_by_id(
            db=db,
            community_id=community_id,
            current_user=current_user,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Creator profile fetch failed community_id=%s path=%s error=%s",
            community_id,
            request.url.path,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Creator profile could not be loaded.",
        ) from exc

    return ApiResponse(
        success=True,
        message="Creator profile fetched successfully",
        data=profile,
    )


@router.put("/{community_id}", response_model=ApiResponse)
def update_profile(
    community_id: uuid.UUID,
    request: CommunityUpdateRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    updated_profile = CommunityService.update_profile(
        db=db,
        community_id=community_id,
        request=request,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Creator profile updated successfully",
        data=updated_profile,
    )


@router.delete("/{community_id}", response_model=ApiResponse)
def delete_profile(
    community_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    CommunityService.delete_profile(
        db=db,
        community_id=community_id,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Creator profile deleted successfully",
        data=None,
    )
