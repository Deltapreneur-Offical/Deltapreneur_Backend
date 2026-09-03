import traceback
import uuid
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, File, UploadFile, Form
from fastapi.responses import RedirectResponse
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_role
from app.entity.platform.admin_audit_log import AdminAuditLog
from app.entity.user.app_user import AppUser
from app.entity.virtual_assistant.virtual_assistant_entity import (
    VirtualAssistantApplication,
)
from app.entity.virtual_assistant.workspace_entity import VANotification
from app.service.admin.virtual_assistant_admin_service import VirtualAssistantAdminService
from app.service.virtual_assistant.va_media import (
    resolve_va_profile_photo_url,
    resolve_va_storage_media_url,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/virtual-assistant", tags=["AdminVirtualAssistant"])


def _parse_assignment_datetime(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        normalized = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid datetime value: {value}",
        ) from exc


def _assignment_db_error_detail(exc: SQLAlchemyError) -> str:
    orig = getattr(exc, "orig", exc)
    message = str(orig).strip()
    lowered = message.lower()
    if isinstance(exc, IntegrityError) or "foreign key" in lowered or "violates" in lowered:
        return (
            "Virtual Assistant profile not found or invalid. "
            "Assignments must reference an existing Virtual Assistant application profile."
        )
    if "undefinedcolumn" in lowered or "does not exist" in lowered:
        return "Assignment storage schema is out of date. Run database migrations and try again."
    if message:
        return message
    return "Failed to save assignment."


@router.get("/applications")
def list_applications(
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    role_filter: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    publish_status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    return VirtualAssistantAdminService.list_applications(
        db,
        search,
        status_filter,
        role_filter,
        date_from,
        date_to,
        page,
        page_size,
        publish_status=publish_status,
    )


@router.get("/applications/counts")
def application_counts(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    return VirtualAssistantAdminService.count_by_status(db)


@router.post("/applications")
def create_application(
    full_name: str = Form(...),
    email: str = Form(...),
    phone_number: str = Form(""),
    location: str = Form(...),
    bio: str = Form(...),
    roles: str = Form(""),
    skills: str = Form(...),
    years_of_experience: str = Form(...),
    languages: str = Form(...),
    linkedin_url: str = Form(""),
    portfolio_url: str = Form(""),
    availability: str = Form("available"),
    hours_per_week: str = Form(""),
    expected_compensation: str = Form(""),
    max_client_capacity: Optional[int] = Form(None),
    current_assigned_clients: int = Form(0),
    public_monthly_price_inr: Optional[int] = Form(None),
    pricing_currency: str = Form("INR"),
    publish_immediately: bool = Form(False),
    profile_photo: UploadFile | None = File(None),
    resume_url: str = Form(""),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    role_list = [r.strip() for r in roles.split(",") if r.strip()] if roles else []
    admin_user_name = (
        getattr(current_user, "full_name", None)
        or getattr(current_user, "name", None)
        or getattr(current_user, "email", None)
        or "Admin"
    )
    try:
        result = VirtualAssistantAdminService.create_application(
            db,
            full_name=full_name,
            email=email,
            phone_number=phone_number,
            location=location,
            profile_photo=profile_photo,
            bio=bio,
            roles=role_list,
            skills=skills,
            years_experience=years_of_experience,
            languages=languages,
            linkedin_url=linkedin_url,
            portfolio_url=portfolio_url,
            resume_url=resume_url,
            availability=availability,
            hours_per_week=hours_per_week,
            expected_compensation=expected_compensation,
            max_client_capacity=max_client_capacity,
            current_assigned_clients=current_assigned_clients,
            publish_immediately=publish_immediately,
            public_monthly_price_inr=public_monthly_price_inr,
            pricing_currency=pricing_currency,
            admin_user_id=str(current_user.id),
            admin_user_name=admin_user_name,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        logger.warning("virtual_assistant.admin.create.validation_error email=%s error=%s", email.strip().lower(), exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        logger.warning("virtual_assistant.admin.create.integrity_error email=%s error=%s", email.strip().lower(), exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unable to save Virtual Assistant profile. Please verify the details and try again.",
        ) from exc
    except Exception as exc:
        db.rollback()
        traceback.print_exc()
        logger.exception("admin.virtual_assistant.create.failed email=%s", email.strip().lower())
        raise HTTPException(status_code=500, detail="Failed to create Virtual Assistant profile.") from exc
    return result


@router.get("/applications/{application_id}")
def get_application(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    app = VirtualAssistantAdminService.get_application(db, application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


@router.delete("/applications/{application_id}")
def delete_application(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    deleted = VirtualAssistantAdminService.delete_application(
        db,
        application_id,
        deleted_by_user_id=str(current_user.id),
        deleted_by_user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", None),
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return {"status": "success", "message": "Application deleted successfully"}


@router.get("/applications/{application_id}/roles")
def list_application_roles(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    app = db.query(VirtualAssistantApplication).filter(
        VirtualAssistantApplication.id == application_id,
        VirtualAssistantApplication.is_deleted.is_(False),
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return VirtualAssistantAdminService.list_application_roles(db, application_id)


@router.patch("/applications/{application_id}/status")
def update_application_status(
    application_id: uuid.UUID,
    body: dict,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    new_status = body.get("status")
    # FE / overall_status use "approved" and "under_review"; legacy app.status uses accepted/reviewing.
    if new_status == "under_review":
        new_status = "reviewing"
    elif new_status == "approved":
        new_status = "accepted"
    if not new_status or new_status not in {
        "pending",
        "reviewing",
        "accepted",
        "rejected",
        "partially_approved",
    }:
        raise HTTPException(
            status_code=400,
            detail="Invalid status. Allowed: pending, reviewing/under_review, accepted/approved, rejected, partially_approved",
        )
    app = VirtualAssistantAdminService.update_status(db, application_id, new_status)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


@router.patch("/applications/{application_id}/roles/{role_id}")
def update_application_role(
    application_id: uuid.UUID,
    role_id: uuid.UUID,
    body: dict,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    new_status = body.get("status")
    if not new_status or new_status not in {"pending", "approved", "rejected"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid role status. Allowed: pending, approved, rejected",
        )
    rejection_note = body.get("rejection_note")
    if new_status == "rejected" and not rejection_note:
        rejection_note = ""
    reviewer_id = str(current_user.id) if getattr(current_user, "id", None) else None
    reviewer_name = getattr(current_user, "full_name", None) or getattr(current_user, "email", None)
    updated_role = VirtualAssistantAdminService.update_role_status(
        db, application_id, role_id, new_status, rejection_note, reviewer_id, reviewer_name
    )
    if not updated_role:
        raise HTTPException(status_code=404, detail="Role not found")
    # Send a single combined decision email to the applicant (best-effort).
    VirtualAssistantAdminService.notify_role_decisions(
        db, application_id, [updated_role], reviewer_name
    )
    return updated_role


@router.get("/applications/{application_id}/resume")
def download_resume(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    row = db.query(VirtualAssistantApplication).filter(
        VirtualAssistantApplication.id == application_id
    ).first()
    if not row or row.is_deleted:
        raise HTTPException(status_code=404, detail="Application not found")
    if not row.resume_key and not row.resume_url:
        raise HTTPException(status_code=404, detail="Resume not uploaded")
    # External resume links (Drive / OneDrive / Dropbox) — open as stored.
    if row.resume_url and not row.resume_key:
        return RedirectResponse(url=row.resume_url.strip())
    # Legacy S3-stored resume files
    url = resolve_va_storage_media_url(row.resume_url, row.resume_key)
    if not url:
        raise HTTPException(status_code=500, detail="Could not generate download link")
    return RedirectResponse(url=url)


@router.get("/applications/{application_id}/profile-photo-url")
def get_application_profile_photo_url(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    row = db.query(VirtualAssistantApplication).filter(
        VirtualAssistantApplication.id == application_id
    ).first()
    if not row or row.is_deleted:
        raise HTTPException(status_code=404, detail="Application not found")
    url = resolve_va_profile_photo_url(row.profile_photo_url, row.profile_photo_key)
    if not url:
        raise HTTPException(status_code=404, detail="Profile photo not uploaded")
    return {"profilePhotoUrl": url}


@router.patch("/applications/{application_id}/pricing")
def update_pricing(
    application_id: uuid.UUID,
    body: dict,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    public_monthly_price_inr = body.get("publicMonthlyPriceInr")
    pricing_currency = body.get("pricingCurrency", "INR")
    max_client_capacity = body.get("maxClientCapacity")
    if public_monthly_price_inr is not None:
        try:
            public_monthly_price_inr = int(public_monthly_price_inr)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="publicMonthlyPriceInr must be a positive integer")
        if public_monthly_price_inr < 0:
            raise HTTPException(status_code=400, detail="publicMonthlyPriceInr must be a positive integer")
    if max_client_capacity is not None:
        try:
            max_client_capacity = int(max_client_capacity)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="maxClientCapacity must be a positive integer")
        if max_client_capacity < 1:
            raise HTTPException(status_code=400, detail="maxClientCapacity must be a positive integer")
    app = VirtualAssistantAdminService.update_pricing(
        db,
        application_id,
        public_monthly_price_inr,
        pricing_currency,
        str(current_user.id) if getattr(current_user, "id", None) else None,
        getattr(current_user, "full_name", None) or getattr(current_user, "email", None),
        max_client_capacity=max_client_capacity,
    )
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


@router.patch("/applications/{application_id}/publish")
def publish_application(
    application_id: uuid.UUID,
    body: dict,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    action = body.get("action")
    if action not in {"publish", "unpublish", "draft"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid action. Allowed: publish, unpublish, draft",
        )
    reviewer_id = str(current_user.id) if getattr(current_user, "id", None) else None
    reviewer_name = getattr(current_user, "full_name", None) or getattr(current_user, "email", None)
    try:
        if action == "publish":
            app = VirtualAssistantAdminService.publish_application(db, application_id, reviewer_id, reviewer_name)
        elif action == "unpublish":
            app = VirtualAssistantAdminService.unpublish_application(db, application_id, reviewer_id, reviewer_name)
        else:
            row = db.query(VirtualAssistantApplication).filter(VirtualAssistantApplication.id == application_id).first()
            if not row or row.is_deleted:
                raise HTTPException(status_code=404, detail="Application not found")
            row.publish_status = "draft"
            row.published_at = None
            row.published_by_id = None
            row.published_by_name = None
            db.commit()
            db.refresh(row)
            app = VirtualAssistantAdminService._serialize_detail(db, row)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


@router.patch("/application-roles/{role_id}/capacity")
def update_role_capacity(
    role_id: uuid.UUID,
    body: dict,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    max_clients = body.get("maxClients")
    current_clients = body.get("currentClients")
    is_active = body.get("isActive")
    if max_clients is not None:
        try:
            max_clients = int(max_clients)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="maxClients must be an integer")
        if max_clients < 0:
            raise HTTPException(status_code=400, detail="maxClients must be non-negative")
    if current_clients is not None:
        try:
            current_clients = int(current_clients)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="currentClients must be an integer")
        if current_clients < 0:
            raise HTTPException(status_code=400, detail="currentClients must be non-negative")
    try:
        role = VirtualAssistantAdminService.update_role_capacity(
            db,
            role_id,
            max_clients=max_clients,
            current_clients=current_clients,
            is_active=is_active,
            updated_by_user_id=str(current_user.id) if getattr(current_user, "id", None) else None,
            updated_by_user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return role


@router.get("/applications/{application_id}/assignments")
def list_assignments(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    app = db.query(VirtualAssistantApplication).filter(
        VirtualAssistantApplication.id == application_id,
        VirtualAssistantApplication.is_deleted.is_(False),
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"status": "success", "data": VirtualAssistantAdminService.list_assignments(db, application_id)}


@router.post("/applications/{application_id}/assignments")
def create_assignment(
    application_id: uuid.UUID,
    body: dict,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    assigned_company = (body.get("assignedCompany") or body.get("company") or "").strip()
    assigned_role = (body.get("assignedRole") or body.get("role") or "").strip()
    if not assigned_company:
        raise HTTPException(status_code=400, detail="assignedCompany is required")
    if not assigned_role:
        raise HTTPException(status_code=400, detail="assignedRole is required")

    parsed_start = _parse_assignment_datetime(body.get("startDate"))
    parsed_end = _parse_assignment_datetime(body.get("endDate"))
    if parsed_start and parsed_end and parsed_end < parsed_start:
        raise HTTPException(status_code=400, detail="endDate must be on or after startDate")

    try:
        assignment = VirtualAssistantAdminService.create_assignment(
            db,
            application_id,
            assigned_company=assigned_company,
            assigned_role=assigned_role,
            start_date=parsed_start,
            end_date=parsed_end,
            notes=(body.get("notes") or None),
            created_by_user_id=str(current_user.id) if getattr(current_user, "id", None) else None,
            created_by_user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.exception("create_assignment failed application_id=%s", application_id)
        status_code = 400 if isinstance(exc, IntegrityError) else 500
        raise HTTPException(
            status_code=status_code,
            detail=_assignment_db_error_detail(exc),
        ) from exc

    if not assignment:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"status": "success", "data": assignment}


@router.patch("/assignments/{assignment_id}")
def update_assignment(
    assignment_id: uuid.UUID,
    body: dict,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    start_date = body.get("startDate")
    end_date = body.get("endDate")
    parsed_start = None
    parsed_end = None
    if start_date:
        try:
            parsed_start = datetime.fromisoformat(start_date)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="startDate must be a valid ISO datetime")
    if end_date:
        try:
            parsed_end = datetime.fromisoformat(end_date)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="endDate must be a valid ISO datetime")
    assignment = VirtualAssistantAdminService.update_assignment(
        db,
        assignment_id,
        assigned_company=body.get("assignedCompany"),
        assigned_role=body.get("assignedRole"),
        status=body.get("status"),
        start_date=parsed_start,
        end_date=parsed_end,
        notes=body.get("notes"),
        updated_by_user_id=str(current_user.id) if getattr(current_user, "id", None) else None,
        updated_by_user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", None),
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return assignment


@router.delete("/assignments/{assignment_id}")
def delete_assignment(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    deleted = VirtualAssistantAdminService.delete_assignment(
        db,
        assignment_id,
        deleted_by_user_id=str(current_user.id) if getattr(current_user, "id", None) else None,
        deleted_by_user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", None),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return {"status": "success", "message": "Assignment deleted"}


@router.patch("/applications/{application_id}/admin-notes")
def update_admin_notes(
    application_id: uuid.UUID,
    body: dict,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    admin_notes = body.get("adminNotes")
    app_row = db.query(VirtualAssistantApplication).filter(
        VirtualAssistantApplication.id == application_id,
        VirtualAssistantApplication.is_deleted.is_(False),
    ).first()
    if not app_row:
        raise HTTPException(status_code=404, detail="Application not found")
    app_row.admin_notes = admin_notes
    db.commit()
    db.refresh(app_row)
    return VirtualAssistantAdminService._serialize_detail(db, app_row)


@router.get("/applications/{application_id}/audit-logs")
def get_application_audit_logs(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    app_row = db.query(VirtualAssistantApplication).filter(
        VirtualAssistantApplication.id == application_id,
        VirtualAssistantApplication.is_deleted.is_(False),
    ).first()
    if not app_row:
        raise HTTPException(status_code=404, detail="Application not found")
    logs = (
        db.query(AdminAuditLog)
        .filter(
            AdminAuditLog.entity_id == str(application_id),
            AdminAuditLog.entity_type == "VIRTUAL_ASSISTANT",
        )
        .order_by(AdminAuditLog.created_at.desc())
        .all()
    )
    result = []
    for log in logs:
        result.append({
            "id": str(log.id),
            "action": log.action,
            "reason": log.reason,
            "details": log.details,
            "createdAt": log.created_at.isoformat() if log.created_at else None,
            "adminName": getattr(log.admin, "full_name", None) or getattr(log.admin, "email", None) if log.admin else None,
        })
    return result


@router.get("/applications/{application_id}/notifications")
def get_application_notifications(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN", "AUCTION_MODERATOR"])),
):
    app_row = db.query(VirtualAssistantApplication).filter(
        VirtualAssistantApplication.id == application_id,
        VirtualAssistantApplication.is_deleted.is_(False),
    ).first()
    if not app_row:
        raise HTTPException(status_code=404, detail="Application not found")
    notifications = (
        db.query(VANotification)
        .filter(
            VANotification.related_application_id == application_id,
            VANotification.is_deleted.is_(False),
        )
        .order_by(VANotification.created_at.desc())
        .all()
    )
    result = []
    for notif in notifications:
        result.append({
            "id": str(notif.id),
            "type": notif.notification_type,
            "title": notif.title,
            "message": notif.message,
            "isRead": notif.is_read,
            "createdAt": notif.created_at.isoformat() if notif.created_at else None,
        })
    return result








