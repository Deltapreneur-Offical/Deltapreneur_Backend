import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.entity.becobrother.be_cobrother_entity import BeCoBrotherApplication
from app.model.becobrother.be_cobrother import BeCoBrother
from app.service.auth.mail_service import MailService

logger = logging.getLogger(__name__)


class BeCoBrotherService:
    @staticmethod
    async def joining_request(db: Session, body: BeCoBrother) -> None:
        row = BeCoBrotherApplication(
            full_name=body.fullName.strip(),
            email=str(body.email).strip().lower(),
            phone_number=(body.phoneNumber or "").strip() or None,
            pin_code=(body.pinCode or "").strip() or None,
            skill=(body.skill or "").strip() or None,
            equipment=bool(body.equipment),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        logger.info(
            "BeCoBrother application saved id=%s email=%s",
            row.id,
            row.email,
        )

        if not settings.mail_configured():
            logger.warning("mail.skip becobrother_application id=%s mail not configured", row.id)
            return

        submitted_at = (
            row.created_at.astimezone(timezone.utc).strftime("%d %b %Y, %I:%M %p")
            if row.created_at
            else datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p")
        )
        recipient = settings.resolved_becobrother_application_recipient()
        if not recipient:
            logger.warning("mail.skip becobrother_application id=%s no recipient", row.id)
            return

        try:
            await MailService.send_becobrother_application_email(
                to_email=recipient,
                full_name=row.full_name,
                email=row.email,
                phone_number=row.phone_number,
                pin_code=row.pin_code,
                skill=row.skill,
                equipment=row.equipment,
                submitted_at=submitted_at,
            )
        except Exception:  # noqa: BLE001
            logger.exception("becobrother.application.email.failed id=%s", row.id)
