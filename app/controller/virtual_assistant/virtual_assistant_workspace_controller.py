import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.entity.virtual_assistant.virtual_assistant_entity import (
    VirtualAssistantApplication,
)
from app.entity.virtual_assistant.workspace_entity import (
    VAAssignment,
    VAClient,
    VANotification,
)
from app.service.admin.virtual_assistant_admin_service import (
    VirtualAssistantAdminService,
)
from app.service.virtual_assistant.va_media import resolve_va_profile_photo_url

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/virtual-assistant/workspace",
    tags=["VirtualAssistantWorkspace"],
)


def _applicant_email(current_user: AppUser) -> str:
    return (current_user.email or "").strip().lower()


def _link_user_to_applications(db: Session, apps: list[VirtualAssistantApplication], user_id) -> None:
    if not user_id:
        return
    changed = False
    for app in apps:
        if not app.user_id:
            app.user_id = user_id
            changed = True
    if changed:
        db.commit()


def _require_unlocked_workspace(
    db: Session, current_user: AppUser
) -> tuple[list[VirtualAssistantApplication], VirtualAssistantApplication]:
    """Resolve all applicant applications and enforce workspace unlock."""
    email = _applicant_email(current_user)
    apps = VirtualAssistantAdminService.get_applicant_applications(db, email)
    if not apps:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    _link_user_to_applications(db, apps, current_user.id)

    if not VirtualAssistantAdminService.applicant_workspace_unlocked(db, email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace is locked. At least one role must be approved to access it.",
        )

    primary = VirtualAssistantAdminService.get_primary_workspace_application(db, email)
    if not primary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return apps, primary


def _application_ids(apps: list[VirtualAssistantApplication]) -> list[uuid.UUID]:
    return [app.id for app in apps]


def _workspace_locked_for_email(db: Session, email: str) -> bool:
    return not VirtualAssistantAdminService.applicant_workspace_unlocked(db, email)


def _unique_client_count(clients: list[VAClient]) -> int:
    keys = {
        ((c.client_name or "").strip().lower(), (c.company_name or "").strip().lower())
        for c in clients
    }
    return len(keys)


def _assignment_stats(db: Session, app_ids: list[uuid.UUID]) -> tuple[list[VAAssignment], int, int]:
    items = (
        db.query(VAAssignment)
        .filter(
            VAAssignment.application_id.in_(app_ids),
            VAAssignment.is_deleted.is_(False),
        )
        .order_by(VAAssignment.created_at.desc())
        .all()
    )
    active_count = sum(1 for item in items if item.status == "active")
    return items, active_count, len(items)


def _serialize_assignment(a: VAAssignment) -> dict:
    return {
        "id": str(a.id),
        "assignedCompany": a.assigned_company,
        "assignedRole": a.assigned_role,
        "status": a.status,
        "startDate": a.start_date.isoformat() if a.start_date else None,
        "endDate": a.end_date.isoformat() if a.end_date else None,
        "notes": a.notes,
    }


def _set_availability_for_applicant(
    db: Session, email: str, availability: str
) -> VirtualAssistantApplication:
    apps = VirtualAssistantAdminService.get_applicant_applications(db, email)
    if not apps:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    normalized = (availability or "available").strip().lower()
    for app in apps:
        app.availability = normalized
    db.commit()
    primary = VirtualAssistantAdminService.get_primary_workspace_application(db, email)
    if not primary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    db.refresh(primary)
    return primary


# ───────────────────────── Profile ─────────────────────────
@router.get("/profile")
def get_workspace_profile(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    apps, row = _require_unlocked_workspace(db, current_user)
    email = _applicant_email(current_user)
    return {
        "id": str(row.id),
        "fullName": row.full_name,
        "email": row.email,
        "profilePhotoUrl": resolve_va_profile_photo_url(
            row.profile_photo_url, row.profile_photo_key
        ),
        "bio": row.short_bio,
        "skills": row.skills,
        "languagesKnown": row.languages_known,
        "yearsExperience": row.years_experience,
        "linkedinUrl": row.linkedin_url,
        "portfolioUrl": row.portfolio_url,
        "availability": row.availability or "available",
        "location": row.location,
        "phoneNumber": row.phone_number,
        "workspaceLocked": _workspace_locked_for_email(db, email),
        "overallStatus": row.overall_status,
        "publicMonthlyPriceInr": row.public_monthly_price_inr,
        "pricingCurrency": row.pricing_currency,
        "pricingUpdatedById": row.pricing_updated_by_id,
        "pricingUpdatedAt": row.pricing_updated_at.isoformat() if row.pricing_updated_at else None,
        "publishStatus": row.publish_status,
        "publishedAt": row.published_at.isoformat() if row.published_at else None,
        "maxClientCapacity": row.max_client_capacity,
        "applicationCount": len(apps),
    }


@router.patch("/profile")
def update_workspace_profile(
    body: dict,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    apps, row = _require_unlocked_workspace(db, current_user)
    editable = {
        "bio": "short_bio",
        "skills": "skills",
        "languagesKnown": "languages_known",
        "portfolioUrl": "portfolio_url",
        "availability": "availability",
    }
    availability_value: Optional[str] = None
    for key, column in editable.items():
        if key in body:
            value = body[key]
            if key == "availability":
                availability_value = (value or "available").strip().lower() if isinstance(value, str) else "available"
            setattr(row, column, (value or None) if isinstance(value, str) else value)

    if availability_value is not None:
        for app in apps:
            app.availability = availability_value

    db.commit()
    db.refresh(row)
    return {
        "bio": row.short_bio,
        "skills": row.skills,
        "languagesKnown": row.languages_known,
        "portfolioUrl": row.portfolio_url,
        "availability": row.availability,
    }


@router.get("/profile-photo-url")
def get_workspace_profile_photo_url(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    _apps, row = _require_unlocked_workspace(db, current_user)
    url = resolve_va_profile_photo_url(row.profile_photo_url, row.profile_photo_key)
    if not url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile photo not uploaded")
    return {"profilePhotoUrl": url}


# ───────────────────────── Roles ─────────────────────────
@router.get("/roles")
def get_workspace_roles(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    from app.entity.virtual_assistant.application_role_entity import ApplicationRole

    apps, _row = _require_unlocked_workspace(db, current_user)
    all_roles = []
    for app in apps:
        VirtualAssistantAdminService._ensure_roles(db, app)
        roles = (
            db.query(ApplicationRole)
            .filter(ApplicationRole.application_id == app.id)
            .order_by(ApplicationRole.role_name)
            .all()
        )
        for role in roles:
            all_roles.append(
                {
                    "id": str(role.id),
                    "applicationId": str(app.id),
                    "referenceNumber": app.reference_number,
                    "roleName": role.role_name,
                    "status": role.status,
                    "reviewedAt": role.reviewed_at.isoformat() if role.reviewed_at else None,
                    "rejectionNote": role.rejection_note,
                    "maxClients": role.max_clients,
                    "currentClients": role.current_clients,
                    "isActive": role.is_active,
                    "availabilityStatus": VirtualAssistantAdminService._role_availability_status(role),
                }
            )
    return all_roles


# ───────────────────────── Assignments ─────────────────────────
@router.get("/assignments")
def get_workspace_assignments(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    apps, _row = _require_unlocked_workspace(db, current_user)
    items, _active_count, _total = _assignment_stats(db, _application_ids(apps))
    return [_serialize_assignment(a) for a in items]


# ───────────────────────── Clients ─────────────────────────
@router.get("/clients")
def get_workspace_clients(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    apps, _row = _require_unlocked_workspace(db, current_user)
    items = (
        db.query(VAClient)
        .filter(VAClient.application_id.in_(_application_ids(apps)))
        .order_by(VAClient.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(c.id),
            "clientName": c.client_name,
            "companyName": c.company_name,
            "assignedRole": c.assigned_role,
            "status": c.status,
        }
        for c in items
    ]


# ───────────────────────── Availability ─────────────────────────
@router.get("/availability")
def get_workspace_availability(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    apps, primary = _require_unlocked_workspace(db, current_user)
    app_ids = _application_ids(apps)
    _items, active_count, total_count = _assignment_stats(db, app_ids)
    client_rows = db.query(VAClient).filter(VAClient.application_id.in_(app_ids)).all()
    max_capacity_values = [app.max_client_capacity for app in apps if app.max_client_capacity is not None]
    max_capacity = sum(max_capacity_values) if max_capacity_values else primary.max_client_capacity

    return {
        "availability": primary.availability or "available",
        "activeAssignments": active_count,
        "totalAssignments": total_count,
        "maxClientCapacity": max_capacity,
        "currentClientCount": _unique_client_count(client_rows),
    }


@router.patch("/availability")
def update_workspace_availability(
    body: dict,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    _require_unlocked_workspace(db, current_user)
    availability = body.get("availability")
    if not isinstance(availability, str) or not availability.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="availability is required",
        )
    primary = _set_availability_for_applicant(db, _applicant_email(current_user), availability)
    apps = VirtualAssistantAdminService.get_applicant_applications(db, _applicant_email(current_user))
    app_ids = _application_ids(apps)
    _items, active_count, total_count = _assignment_stats(db, app_ids)
    client_rows = db.query(VAClient).filter(VAClient.application_id.in_(app_ids)).all()
    max_capacity_values = [app.max_client_capacity for app in apps if app.max_client_capacity is not None]
    max_capacity = sum(max_capacity_values) if max_capacity_values else primary.max_client_capacity

    return {
        "availability": primary.availability or "available",
        "activeAssignments": active_count,
        "totalAssignments": total_count,
        "maxClientCapacity": max_capacity,
        "currentClientCount": _unique_client_count(client_rows),
    }


# ───────────────────────── Settings ─────────────────────────
@router.get("/settings")
def get_workspace_settings(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    _apps, primary = _require_unlocked_workspace(db, current_user)
    return {
        "notificationsEnabled": True,
        "emailNotifications": True,
        "profileVisible": primary.publish_status == "published",
        "availability": primary.availability or "available",
    }


@router.patch("/settings")
def update_workspace_settings(
    body: dict,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    _require_unlocked_workspace(db, current_user)
    if "availability" in body and isinstance(body["availability"], str):
        _set_availability_for_applicant(db, _applicant_email(current_user), body["availability"])
    _apps, primary = _require_unlocked_workspace(db, current_user)
    return {
        "notificationsEnabled": bool(body.get("notificationsEnabled", True)),
        "emailNotifications": bool(body.get("emailNotifications", True)),
        "profileVisible": primary.publish_status == "published",
        "availability": primary.availability or "available",
    }


# ───────────────────────── Notifications ─────────────────────────
@router.get("/notifications")
def get_workspace_notifications(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    try:
        apps, _row = _require_unlocked_workspace(db, current_user)
        app_ids = _application_ids(apps)
        items = (
            db.query(VANotification)
            .filter(
                (VANotification.related_application_id.in_(app_ids))
                | (VANotification.va_id == current_user.id),
                VANotification.is_deleted.is_(False),
            )
            .order_by(VANotification.created_at.desc())
            .all()
        )
        result = []
        for n in items:
            raw_title = (n.title or "").strip()
            raw_msg = (n.message or "").strip()

            if raw_title and raw_msg:
                norm_title = raw_title.rstrip(".").lower()
                norm_msg = raw_msg.rstrip(".").lower()
                if norm_title == norm_msg:
                    title_str = raw_title
                    msg_str = None
                else:
                    title_str = raw_title
                    msg_str = raw_msg
            elif raw_title:
                title_str = raw_title
                msg_str = None
            elif raw_msg:
                title_str = raw_msg
                msg_str = None
            else:
                title_str = (n.notification_type or "Notification").replace("_", " ").title()
                msg_str = None

            result.append(
                {
                    "id": str(n.id),
                    "type": n.notification_type or "general",
                    "title": title_str,
                    "message": msg_str,
                    "isRead": bool(n.is_read),
                    "read": bool(n.is_read),
                    "createdAt": n.created_at.isoformat() if n.created_at else None,
                    "targetUrl": n.target_url,
                }
            )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch workspace notifications for user_id=%s: %s", current_user.id, exc)
        return []


@router.post("/notifications/{notification_id}/read")
def mark_workspace_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    try:
        try:
            notif_uuid = uuid.UUID(notification_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid notification ID format")

        apps, _row = _require_unlocked_workspace(db, current_user)
        app_ids = _application_ids(apps)
        notif = (
            db.query(VANotification)
            .filter(
                VANotification.id == notif_uuid,
                (VANotification.related_application_id.in_(app_ids))
                | (VANotification.va_id == current_user.id),
                VANotification.is_deleted.is_(False),
            )
            .first()
        )
        if not notif:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
        notif.is_read = True
        db.commit()
        return {"success": True, "id": str(notif.id), "isRead": True, "read": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to mark workspace notification read id=%s: %s", notification_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark notification as read",
        )
