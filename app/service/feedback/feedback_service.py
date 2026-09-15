import logging

from app.core.config import settings
from app.core.exceptions import AppException
from app.model.feedback.feedback_request import FeedbackRequest
from app.service.auth.mail_service import MailService

logger = logging.getLogger(__name__)

# Feedback has no database table to fall back on, so a failed send means the
# message is lost. Say so instead of reporting success.
_UNDELIVERABLE_MESSAGE = (
    "We could not deliver your feedback right now. Please try again shortly."
)


class FeedbackService:

    @staticmethod
    async def send_feedback_email(body: FeedbackRequest) -> None:
        """Send feedback mail, raising AppException(503) on failure.

        Kept for callers that want the send result inline. The HTTP endpoint
        uses deliver_feedback_email in a background task instead.
        """
        logger.info("Feedback received subject=%s email=%s", body.subject, body.email)

        if not settings.mail_configured():
            logger.error(
                "mail.skip feedback — mail not configured (MAIL_SERVER=%r); feedback dropped",
                settings.MAIL_SERVER,
            )
            raise AppException(_UNDELIVERABLE_MESSAGE, status_code=503)

        try:
            await MailService.send_feedback_email(
                from_email=body.email,
                subject=body.subject,
                feedback_type=body.feedback_type,
                page_url=body.page_url,
                message_text=body.message,
            )
        except Exception as exc:
            # Never surface SMTP hosts or credentials hints to the browser.
            logger.exception("mail.fail feedback delivery failed: %s", exc)
            raise AppException(_UNDELIVERABLE_MESSAGE, status_code=503) from exc

    @staticmethod
    async def deliver_feedback_email(body: FeedbackRequest) -> None:
        """Background-task variant: attempt delivery, never raise.

        Runs after the HTTP response is sent, so a slow or blocked SMTP server
        does not make the visitor wait. Failures are logged as mail.fail for
        operators; the endpoint has already acknowledged receipt.
        """
        try:
            await FeedbackService.send_feedback_email(body)
        except Exception as exc:  # includes AppException from send_feedback_email
            logger.error("mail.fail feedback background delivery failed: %s", exc)
