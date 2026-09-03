import logging

from app.model.feedback.feedback_request import FeedbackRequest
from app.service.auth.mail_service import MailService

logger = logging.getLogger(__name__)


class FeedbackService:
    @staticmethod
    async def send_feedback_email(body: FeedbackRequest) -> None:
        logger.info("Feedback received subject=%s email=%s", body.subject, body.email)
        await MailService.send_feedback_email(
            from_email=body.email,
            subject=body.subject,
            feedback_type=body.feedback_type,
            page_url=body.page_url,
            message_text=body.message,
        )
