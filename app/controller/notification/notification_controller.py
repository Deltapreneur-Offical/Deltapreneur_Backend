import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.model.common.api_response import ApiResponse
from app.service.notification.notification_service import NotificationService


router = APIRouter(
    prefix="/api/v1/notifications",
    tags=["Notifications"],
)
logger = logging.getLogger(__name__)


@router.get("/test", response_model=ApiResponse)
def test_notifications():
    return ApiResponse(
        success=True,
        message="Notification module is connected successfully",
        data={
            "module": "notifications",
            "status": "ready",
        },
    )


@router.get("/my", response_model=ApiResponse)
def get_my_notifications(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    notifications = NotificationService.get_my_notifications(
        db=db,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Notifications fetched successfully",
        data=notifications,
    )


@router.get("/unread", response_model=ApiResponse)
def get_my_unread_notifications(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    notifications = NotificationService.get_my_unread_notifications(
        db=db,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Unread notifications fetched successfully",
        data=notifications,
    )


@router.put("/{notification_id}/read", response_model=ApiResponse)
def mark_notification_as_read(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    notification = NotificationService.mark_as_read(
        db=db,
        notification_id=notification_id,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Notification marked as read successfully",
        data=notification,
    )


@router.put("/read-all", response_model=ApiResponse)
def mark_all_notifications_as_read(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    result = NotificationService.mark_all_as_read(
        db=db,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="All notifications marked as read successfully",
        data=result,
    )


def _frontend_notifications(
    db: Session,
    current_user: AppUser,
    *,
    unread_only: bool = False,
    limit: int | None = None,
) -> list[dict]:
    from app.repository.notification_repository import NotificationRepository

    if unread_only:
        notifications = NotificationRepository.find_unread_by_user_id(
            db, current_user.id,
        )
    else:
        notifications = NotificationRepository.find_by_user_id(
            db, current_user.id,
        )

    payload = [
        NotificationService._to_frontend(notification)
        for notification in notifications
    ]
    if limit is not None:
        return payload[:limit]
    return payload


@router.get("/recent")
def get_recent_notifications_frontend(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    return _frontend_notifications(db, current_user, limit=15)


@router.get("/all")
def get_all_notifications_frontend(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    return _frontend_notifications(db, current_user)


@router.get("/unread-count")
def get_unread_count_frontend(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    try:
        count = NotificationService.get_unread_count(
            db=db,
            current_user=current_user,
        )
    except Exception as exc:
        logger.exception(
            "Unread notification count failed user_id=%s error=%s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load unread notification count.",
        ) from exc

    return {
        "count": int(count or 0),
    }


@router.put("/mark-all-read", response_model=ApiResponse)
def mark_all_read_frontend_alias(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    return mark_all_notifications_as_read(db=db, current_user=current_user)


from pydantic import BaseModel, Field


class DeleteSelectedNotificationsSchema(BaseModel):
    ids: list[uuid.UUID] = Field(default_factory=list)


@router.post("/delete-multiple", response_model=ApiResponse)
@router.delete("/selected", response_model=ApiResponse)
def delete_selected_notifications(
    body: DeleteSelectedNotificationsSchema,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    count = NotificationService.delete_selected_notifications(
        db=db,
        notification_ids=body.ids,
        current_user=current_user,
    )
    return ApiResponse(
        success=True,
        message=f"{count} notification(s) deleted successfully",
        data={"deleted_count": count},
    )


@router.delete("/delete-all", response_model=ApiResponse)
@router.delete("/all-notifications", response_model=ApiResponse)
def delete_all_notifications(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    count = NotificationService.delete_all_notifications(
        db=db,
        current_user=current_user,
    )
    return ApiResponse(
        success=True,
        message="All notifications deleted successfully",
        data={"deleted_count": count},
    )


@router.delete("/{notification_id}", response_model=ApiResponse)
def delete_notification(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    NotificationService.delete_notification(
        db=db,
        notification_id=notification_id,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Notification deleted successfully",
        data=None,
    )


