"""Sequential VA application and reference number allocation."""

from __future__ import annotations

import logging

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from fastapi import HTTPException, status

from app.entity.virtual_assistant.virtual_assistant_entity import VirtualAssistantApplication

logger = logging.getLogger(__name__)

VA_REFERENCE_PREFIX = "CB-VA-"
VA_SEQUENCE_NAME = "va_application_number_seq"
VA_ALLOCATION_LOCK_KEY = 824_001


def format_reference_number(application_number: int) -> str:
    return f"{VA_REFERENCE_PREFIX}{application_number:06d}"


def format_application_number_display(application_number: int | None) -> str | None:
    if application_number is None:
        return None
    return str(application_number).zfill(2)


def parse_application_number_from_reference(reference_number: str | None) -> int | None:
    if not reference_number:
        return None
    normalized = reference_number.strip().upper()
    if normalized.startswith(VA_REFERENCE_PREFIX):
        suffix = normalized[len(VA_REFERENCE_PREFIX) :]
        if suffix.isdigit():
            return int(suffix)
    return None


def resolve_application_number(row: VirtualAssistantApplication) -> int | None:
    number = getattr(row, "application_number", None)
    if number is not None:
        return int(number)
    return parse_application_number_from_reference(row.reference_number)


def _sync_sequence(db: Session) -> None:
    db.execute(
        text(
            f"""
            SELECT setval(
                '{VA_SEQUENCE_NAME}',
                GREATEST(
                    COALESCE((SELECT MAX(application_number) FROM virtual_assistant_applications), 0),
                    COALESCE((SELECT last_value FROM {VA_SEQUENCE_NAME}), 0)
                ),
                true
            )
            """
        )
    )


def allocate_application_numbers(db: Session) -> tuple[int, str]:
    """Reserve the next sequential application number and formatted reference."""
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": VA_ALLOCATION_LOCK_KEY})
    _sync_sequence(db)

    for attempt in range(20):
        application_number = int(
            db.execute(text(f"SELECT nextval('{VA_SEQUENCE_NAME}')")).scalar_one()
        )
        reference_number = format_reference_number(application_number)
        existing = (
            db.query(VirtualAssistantApplication.id)
            .filter(
                or_(
                    VirtualAssistantApplication.reference_number == reference_number,
                    VirtualAssistantApplication.application_number == application_number,
                )
            )
            .first()
        )
        if not existing:
            return application_number, reference_number
        logger.warning(
            "va.reference.collision application_number=%s reference=%s attempt=%s",
            application_number,
            reference_number,
            attempt + 1,
        )

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Unable to generate a unique reference number. Please try again.",
    )


def application_number_fields(row: VirtualAssistantApplication) -> dict[str, int | str | None]:
    number = resolve_application_number(row)
    return {
        "applicationNumber": number,
        "applicationNumberDisplay": format_application_number_display(number),
    }
