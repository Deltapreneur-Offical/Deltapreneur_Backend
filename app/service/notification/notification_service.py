import logging
import uuid

import anyio
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.entity.notification.notification import Notification
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.repository.notification_repository import NotificationRepository
from app.websocket.manager import notification_connection_manager


class NotificationService:
    @staticmethod
    def _to_response(notification: Notification) -> dict:
        return {
            "id": str(notification.id),
            "app_user_id": str(notification.app_user_id),
            "notification_type": notification.notification_type,
            "title": notification.title,
            "message": notification.message,
            "target_url": notification.target_url,
            "is_read": notification.is_read,
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
            "updated_at": notification.updated_at.isoformat() if notification.updated_at else None,
        }

    @staticmethod
    def _to_frontend(notification: Notification) -> dict:
        base = NotificationService._to_response(notification)
        return {
            "id": base["id"],
            "type": base["notification_type"],
            "title": base["title"],
            "message": base["message"] or base["title"],
            "link": base["target_url"],
            "read": base["is_read"],
            "createdAt": base["created_at"],
        }

    @staticmethod
    def get_unread_count(
        db: Session,
        current_user: AppUser,
    ) -> int:
        return NotificationRepository.count_unread_by_user_id(
            db=db,
            app_user_id=current_user.id,
        )

    @staticmethod
    def _broadcast_notification(
        user_id: uuid.UUID,
        notification_data: dict,
    ) -> None:
        try:
            anyio.from_thread.run(
                notification_connection_manager.send_personal_notification,
                user_id,
                notification_data,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Notification saved but live WebSocket broadcast failed"
            )

    @staticmethod
    def notify(
        db: Session,
        user: AppUser,
        notification_type: NotificationType,
        title: str,
        message: str | None = None,
        target_url: str | None = None,
    ) -> dict:
        notification = Notification(
            app_user_id=user.id,
            notification_type=notification_type.value,
            title=title,
            message=message,
            target_url=target_url,
        )

        saved_notification = NotificationRepository.save(
            db=db,
            notification=notification,
        )

        notification_data = NotificationService._to_response(
            saved_notification,
        )
        frontend_payload = NotificationService._to_frontend(saved_notification)

        NotificationService._broadcast_notification(
            user_id=user.id,
            notification_data={
                "event": "notification_created",
                "data": frontend_payload,
            },
        )

        return notification_data

    @staticmethod
    def get_my_notifications(
        db: Session,
        current_user: AppUser,
    ) -> list[dict]:
        notifications = NotificationRepository.find_by_user_id(
            db=db,
            app_user_id=current_user.id,
        )

        return [
            NotificationService._to_response(notification)
            for notification in notifications
        ]

    @staticmethod
    def get_my_unread_notifications(
        db: Session,
        current_user: AppUser,
    ) -> list[dict]:
        notifications = NotificationRepository.find_unread_by_user_id(
            db=db,
            app_user_id=current_user.id,
        )

        return [
            NotificationService._to_response(notification)
            for notification in notifications
        ]

    @staticmethod
    def mark_as_read(
        db: Session,
        notification_id: uuid.UUID,
        current_user: AppUser,
    ) -> dict:
        notification = NotificationRepository.find_by_id_and_user_id(
            db=db,
            notification_id=notification_id,
            app_user_id=current_user.id,
        )

        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )

        notification.is_read = True

        saved_notification = NotificationRepository.save(
            db=db,
            notification=notification,
        )

        return NotificationService._to_response(saved_notification)

    @staticmethod
    def mark_all_as_read(
        db: Session,
        current_user: AppUser,
    ) -> dict:
        updated_count = NotificationRepository.mark_all_read(
            db=db,
            app_user_id=current_user.id,
        )

        return {
            "updated_count": updated_count,
        }

    @staticmethod
    def delete_notification(
        db: Session,
        notification_id: uuid.UUID,
        current_user: AppUser,
    ) -> None:
        notification = NotificationRepository.find_by_id_and_user_id(
            db=db,
            notification_id=notification_id,
            app_user_id=current_user.id,
        )

        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )

        NotificationRepository.soft_delete(
            db=db,
            notification=notification,
            deleted_by=current_user.id,
        )

    @staticmethod
    def delete_selected_notifications(
        db: Session,
        notification_ids: list[uuid.UUID],
        current_user: AppUser,
    ) -> int:
        if not notification_ids:
            return 0
        return NotificationRepository.soft_delete_selected(
            db=db,
            app_user_id=current_user.id,
            notification_ids=notification_ids,
        )

    @staticmethod
    def delete_all_notifications(
        db: Session,
        current_user: AppUser,
    ) -> int:
        return NotificationRepository.soft_delete_all(
            db=db,
            app_user_id=current_user.id,
        )