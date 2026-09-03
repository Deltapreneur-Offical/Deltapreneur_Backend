import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.entity.notification.notification import Notification


class NotificationRepository:
    @staticmethod
    def _not_deleted_filter(query):
        return query.filter(Notification.is_deleted.is_(False))

    @staticmethod
    def find_by_user_id(
        db: Session,
        app_user_id: uuid.UUID,
    ) -> list[Notification]:
        query = (
            db.query(Notification)
            .filter(Notification.app_user_id == app_user_id)
            .order_by(Notification.created_at.desc())
        )
        return NotificationRepository._not_deleted_filter(query).all()

    @staticmethod
    def find_unread_by_user_id(
        db: Session,
        app_user_id: uuid.UUID,
    ) -> list[Notification]:
        query = (
            db.query(Notification)
            .filter(
                Notification.app_user_id == app_user_id,
                Notification.is_read.is_(False),
            )
            .order_by(Notification.created_at.desc())
        )
        return NotificationRepository._not_deleted_filter(query).all()

    @staticmethod
    def find_by_id_and_user_id(
        db: Session,
        notification_id: uuid.UUID,
        app_user_id: uuid.UUID,
    ) -> Optional[Notification]:
        query = db.query(Notification).filter(
            Notification.id == notification_id,
            Notification.app_user_id == app_user_id,
        )
        return NotificationRepository._not_deleted_filter(query).first()

    @staticmethod
    def save(
        db: Session,
        notification: Notification,
    ) -> Notification:
        db.add(notification)
        db.commit()
        db.refresh(notification)
        return notification

    @staticmethod
    def count_unread_by_user_id(
        db: Session,
        app_user_id: uuid.UUID,
    ) -> int:
        query = db.query(Notification).filter(
            Notification.app_user_id == app_user_id,
            Notification.is_read.is_(False),
        )
        return NotificationRepository._not_deleted_filter(query).count()

    @staticmethod
    def mark_all_read(
        db: Session,
        app_user_id: uuid.UUID,
    ) -> int:
        notifications = NotificationRepository.find_unread_by_user_id(
            db=db,
            app_user_id=app_user_id,
        )

        for notification in notifications:
            notification.is_read = True

        db.commit()
        return len(notifications)

    @staticmethod
    def soft_delete(
        db: Session,
        notification: Notification,
        deleted_by: uuid.UUID,
    ) -> None:
        notification.is_deleted = True
        notification.deleted_at = datetime.now(timezone.utc)
        notification.deleted_by = deleted_by

        db.add(notification)
        db.commit()

    @staticmethod
    def soft_delete_selected(
        db: Session,
        app_user_id: uuid.UUID,
        notification_ids: list[uuid.UUID],
    ) -> int:
        now = datetime.now(timezone.utc)
        count = (
            db.query(Notification)
            .filter(
                Notification.app_user_id == app_user_id,
                Notification.id.in_(notification_ids),
                Notification.is_deleted.is_(False),
            )
            .update(
                {
                    Notification.is_deleted: True,
                    Notification.deleted_at: now,
                    Notification.deleted_by: app_user_id,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        return count

    @staticmethod
    def soft_delete_all(
        db: Session,
        app_user_id: uuid.UUID,
    ) -> int:
        now = datetime.now(timezone.utc)
        count = (
            db.query(Notification)
            .filter(
                Notification.app_user_id == app_user_id,
                Notification.is_deleted.is_(False),
            )
            .update(
                {
                    Notification.is_deleted: True,
                    Notification.deleted_at: now,
                    Notification.deleted_by: app_user_id,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        return count
