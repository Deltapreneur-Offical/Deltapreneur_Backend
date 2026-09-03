"""Persistence for community auction meeting schedules."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.entity.community.meeting_schedule import MeetingSchedule


def _meeting_end(m: MeetingSchedule) -> datetime:
    return m.scheduled_at + timedelta(minutes=m.duration_minutes)


def _overlaps(start: datetime, end: datetime, m: MeetingSchedule) -> bool:
    ms = m.scheduled_at
    me = _meeting_end(m)
    return ms < end and me > start


class MeetingScheduleRepository:
    @staticmethod
    def save(db: Session, row: MeetingSchedule) -> MeetingSchedule:
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def get_by_id(db: Session, meeting_id: uuid.UUID) -> MeetingSchedule | None:
        return (
            db.query(MeetingSchedule)
            .options(
                joinedload(MeetingSchedule.auction),
                joinedload(MeetingSchedule.requester),
                joinedload(MeetingSchedule.lister),
            )
            .filter(MeetingSchedule.id == meeting_id)
            .first()
        )

    @staticmethod
    def find_by_requester_id(db: Session, user_id: uuid.UUID) -> list[MeetingSchedule]:
        return (
            db.query(MeetingSchedule)
            .options(joinedload(MeetingSchedule.auction))
            .filter(MeetingSchedule.requester_id == user_id)
            .order_by(MeetingSchedule.scheduled_at.asc())
            .all()
        )

    @staticmethod
    def find_by_lister_id(db: Session, user_id: uuid.UUID) -> list[MeetingSchedule]:
        return (
            db.query(MeetingSchedule)
            .options(joinedload(MeetingSchedule.auction))
            .filter(MeetingSchedule.lister_id == user_id)
            .order_by(MeetingSchedule.scheduled_at.asc())
            .all()
        )

    @staticmethod
    def find_all_for_user(db: Session, user_id: uuid.UUID) -> list[MeetingSchedule]:
        return (
            db.query(MeetingSchedule)
            .options(joinedload(MeetingSchedule.auction))
            .filter(
                or_(
                    MeetingSchedule.requester_id == user_id,
                    MeetingSchedule.lister_id == user_id,
                )
            )
            .order_by(MeetingSchedule.scheduled_at.asc())
            .all()
        )

    @staticmethod
    def find_by_auction_id(db: Session, auction_id: uuid.UUID) -> list[MeetingSchedule]:
        return (
            db.query(MeetingSchedule)
            .options(
                joinedload(MeetingSchedule.requester),
                joinedload(MeetingSchedule.lister),
            )
            .filter(MeetingSchedule.auction_id == auction_id)
            .order_by(MeetingSchedule.scheduled_at.asc())
            .all()
        )

    @staticmethod
    def find_by_auction_and_requester(
        db: Session,
        auction_id: uuid.UUID,
        requester_id: uuid.UUID,
    ) -> list[MeetingSchedule]:
        return (
            db.query(MeetingSchedule)
            .options(
                joinedload(MeetingSchedule.requester),
                joinedload(MeetingSchedule.lister),
            )
            .filter(
                MeetingSchedule.auction_id == auction_id,
                MeetingSchedule.requester_id == requester_id,
            )
            .order_by(MeetingSchedule.scheduled_at.asc())
            .all()
        )

    @staticmethod
    def find_all_admin(db: Session) -> list[MeetingSchedule]:
        return (
            db.query(MeetingSchedule)
            .options(
                joinedload(MeetingSchedule.auction),
                joinedload(MeetingSchedule.requester),
                joinedload(MeetingSchedule.lister),
            )
            .order_by(MeetingSchedule.scheduled_at.desc())
            .all()
        )

    @staticmethod
    def lister_confirmed_overlap(
        db: Session,
        lister_id: uuid.UUID,
        start: datetime,
        end: datetime,
        *,
        exclude_meeting_id: uuid.UUID | None = None,
    ) -> list[MeetingSchedule]:
        rows = (
            db.query(MeetingSchedule)
            .filter(
                MeetingSchedule.lister_id == lister_id,
                MeetingSchedule.status == "CONFIRMED",
            )
            .all()
        )
        return [
            m
            for m in rows
            if (not exclude_meeting_id or m.id != exclude_meeting_id)
            and _overlaps(start, end, m)
        ]

    @staticmethod
    def requester_confirmed_overlap(
        db: Session,
        requester_id: uuid.UUID,
        start: datetime,
        end: datetime,
        *,
        exclude_meeting_id: uuid.UUID | None = None,
    ) -> list[MeetingSchedule]:
        rows = (
            db.query(MeetingSchedule)
            .filter(
                MeetingSchedule.requester_id == requester_id,
                MeetingSchedule.status == "CONFIRMED",
            )
            .all()
        )
        return [
            m
            for m in rows
            if (not exclude_meeting_id or m.id != exclude_meeting_id)
            and _overlaps(start, end, m)
        ]
