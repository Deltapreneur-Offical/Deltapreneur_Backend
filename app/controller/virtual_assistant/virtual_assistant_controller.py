import logging
import traceback
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.core.bot_protection import enforce_bot_protection
from app.core.database import get_db
from app.core.dependencies import get_current_user, get_optional_current_user
from app.core.rate_limiter import limiter
from app.entity.user.app_user import AppUser
from app.entity.virtual_assistant.virtual_assistant_entity import (
    VirtualAssistantApplication,
)
from app.service.admin.virtual_assistant_admin_service import (
    VirtualAssistantAdminService,
)
from app.service.likes.like_service import LikeService
from app.entity.likes.like_type import LikeType
from app.service.virtual_assistant.va_media import resolve_va_profile_photo_url
from app.service.virtual_assistant.virtual_assistant_service import (
    VirtualAssistantService,
)

router = APIRouter(prefix="/api/v1/virtual-assistant", tags=["VirtualAssistant"])
logger = logging.getLogger(__name__)


@router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def submit_application(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    phone_number: str = Form(""),
    location: str = Form(""),
    is_adult: bool = Form(False),
    bio: str = Form(""),
    roles: str = Form(""),
    skills: str = Form(""),
    years_of_experience: str = Form(""),
    languages: str = Form(""),
    linkedin_url: str = Form(""),
    portfolio_url: str = Form(""),
    availability: str = Form(""),
    hours_per_week: str = Form(""),
    expected_compensation: str = Form(""),
    info_accurate: bool = Form(False),
    agree_terms: bool = Form(False),
    turnstile_token: str = Form(""),
    website: str = Form(""),
    profile_photo: UploadFile | None = File(None),
    resume_url: str = Form(""),
    db: Session = Depends(get_db),
    current_user: AppUser | None = Depends(get_optional_current_user),
):
    logger.info("=== VA APPLICATION ENDPOINT HIT v2 ===")
    user_id = str(current_user.id) if current_user else None
    role_list = [r.strip() for r in roles.split(",") if r.strip()] if roles else []
    logger.info(
        "virtual_assistant.application.submit.start email=%s has_photo=%s has_resume_link=%s user_id=%s full_name=%s roles=%s bio_len=%d is_adult=%s info_accurate=%s agree_terms=%s phone=%s location=%s availability=%s hours=%s compensation=%s",
        email.strip().lower(),
        bool(profile_photo),
        bool((resume_url or "").strip()),
        user_id,
        full_name.strip(),
        role_list,
        len(bio or ""),
        is_adult,
        info_accurate,
        agree_terms,
        phone_number,
        location,
        availability,
        hours_per_week,
        expected_compensation,
    )
    try:
        await enforce_bot_protection(
            request,
            turnstile_token=turnstile_token or None,
            honeypot=website or None,
        )
        logger.info("virtual_assistant.application.bot_protection.passed email=%s", email.strip().lower())
    except Exception as exc:
        logger.warning("virtual_assistant.application.bot_protection.failed email=%s error=%s", email.strip().lower(), exc)
        raise
    validation_errors = []
    if not full_name or not full_name.strip():
        validation_errors.append("full_name is required")
    if not email or not email.strip():
        validation_errors.append("email is required")
    if not profile_photo:
        validation_errors.append("profile_photo is required")
    if not (resume_url or "").strip():
        validation_errors.append("resume_url is required")
    if not is_adult:
        validation_errors.append("is_adult must be true")
    if not info_accurate:
        validation_errors.append("info_accurate must be true")
    if not agree_terms:
        validation_errors.append("agree_terms must be true")
    if len(role_list) != 1:
        validation_errors.append("roles must contain exactly one value")
    if validation_errors:
        logger.warning("virtual_assistant.application.validation.failed errors=%s", validation_errors)
        raise HTTPException(
            status_code=400,
            detail=f"Validation failed: {', '.join(validation_errors)}",
        )
    logger.info("virtual_assistant.application.validation.passed email=%s roles=%s", email.strip().lower(), role_list)

    if not profile_photo:
        logger.warning("virtual_assistant.application.validation.failed field=profile_photo")
        raise HTTPException(status_code=400, detail="Profile photo is required")
    if not (resume_url or "").strip():
        logger.warning("virtual_assistant.application.validation.failed field=resume_url")
        raise HTTPException(status_code=400, detail="Resume link is required")
    try:
        logger.info("virtual_assistant.application.service.start email=%s", email.strip().lower())
        result = VirtualAssistantService.submit_application(
            db, full_name, email, phone_number, location,
            profile_photo, resume_url, bio, role_list, skills, years_of_experience,
            languages, linkedin_url, portfolio_url, availability, hours_per_week,
            expected_compensation, info_accurate, agree_terms, is_adult,
            user_id=user_id,
        )
        logger.info("virtual_assistant.application.service.success result=%s", result)
    except HTTPException:
        logger.warning("virtual_assistant.application.http_error email=%s", email.strip().lower(), exc_info=True)
        raise
    except Exception as exc:
        traceback.print_exc()
        logger.exception("virtual_assistant.application.submit.failed email=%s error=%s", email.strip().lower(), exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process application. Error: {type(exc).__name__}: {str(exc)}",
        )
    logger.info(
        "virtual_assistant.application.submit.success ref=%s email=%s",
        result.get("reference_number"),
        result.get("email"),
    )
    response_payload = {
        "status": "success",
        "message": "Application submitted successfully",
        "data": {
            "referenceNumber": result["reference_number"],
            "email": result["email"],
            "newRoles": result.get("new_roles", []),
        },
    }
    return response_payload


@router.get("/me")
def my_application(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    """Return the authenticated applicant's own Virtual Assistant application.

    Scoped by the applicant's email (applications are submitted with the
    applicant's email). Returns overall status, workspace lock state, and the
    per-role decisions so the applicant can track their journey.
    """
    row = (
        db.query(VirtualAssistantApplication)
        .filter(VirtualAssistantApplication.email == (current_user.email or "").strip().lower())
        .filter(VirtualAssistantApplication.is_deleted.is_(False))
        .order_by(VirtualAssistantApplication.created_at.desc())
        .first()
    )
    if not row:
        return {
            "status": "success",
            "data": None,
        }
    VirtualAssistantAdminService._ensure_roles(db, row)
    data = VirtualAssistantAdminService._serialize_detail(db, row)
    role_summaries = VirtualAssistantAdminService.list_applicant_role_summaries(
        db, current_user.email or ""
    )
    data["roleSummaries"] = role_summaries
    data["workspaceLocked"] = not any(s.get("status") == "approved" for s in role_summaries)
    return {
        "status": "success",
        "data": data,
    }


@router.get("/published")
def list_published_profiles(
    search: str | None = Query(None),
    role: str | None = Query(None),
    skills: str | None = Query(None),
    languages: str | None = Query(None),
    availability: str | None = Query(None),
    min_price: int | None = Query(None, ge=0),
    max_price: int | None = Query(None, ge=0),
    experience: str | None = Query(None),
    sort_by: str | None = Query("recently_published"),
    featured_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=50),
    db: Session = Depends(get_db),
):
    result = VirtualAssistantAdminService.list_public_profiles(
        db,
        search=search,
        role=role,
        skills=skills,
        languages=languages,
        availability=availability,
        min_price=min_price,
        max_price=max_price,
        experience=experience,
        sort_by=sort_by,
        featured_only=featured_only,
        page=page,
        page_size=page_size,
    )
    # Keep VA likes in their own like_type bucket (not COMMUNITY / Creators).
    LikeService.attach_like_counts(
        db,
        LikeType.VIRTUAL_ASSISTANT.value,
        result["items"],
    )
    return {
        "status": "success",
        "data": result["items"],
        "meta": {
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
            "total_pages": result["total_pages"],
        },
    }


@router.get("/{application_id}/public")
def get_public_profile(
    application_id: str,
    request: Request,
    db: Session = Depends(get_db),
    viewer: AppUser | None = Depends(get_optional_current_user),
):
    from app.service.analytics.viewer_metadata import viewer_analytics_metadata

    industry, role = viewer_analytics_metadata(db, viewer)
    profile = VirtualAssistantAdminService.get_public_profile_and_record_view(
        db,
        application_id,
        viewer=viewer,
        client_ip=request.client.host if request.client else None,
        viewer_industry=industry,
        viewer_role=role,
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Virtual Assistant profile not found")
    LikeService.attach_like_counts(
        db,
        LikeType.VIRTUAL_ASSISTANT.value,
        [profile],
    )
    return {
        "status": "success",
        "data": profile,
    }


@router.get("/{application_id}/profile-photo-url")
def get_public_profile_photo_url(
    application_id: str,
    db: Session = Depends(get_db),
):
    row = (
        db.query(VirtualAssistantApplication)
        .filter(VirtualAssistantApplication.id == application_id)
        .first()
    )
    if not row or row.is_deleted or not VirtualAssistantAdminService.is_publicly_listable(db, row):
        raise HTTPException(status_code=404, detail="Virtual Assistant profile not found")
    url = resolve_va_profile_photo_url(row.profile_photo_url, row.profile_photo_key)
    if not url:
        raise HTTPException(status_code=404, detail="Profile photo not uploaded")
    return {
        "status": "success",
        "data": {"profilePhotoUrl": url},
    }

