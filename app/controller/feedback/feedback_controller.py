# app/controller/feedback/feedback_controller.py

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status

from app.core.bot_protection import enforce_bot_protection
from app.core.config import settings
from app.core.rate_limiter import limiter
from app.model.feedback.feedback_request import FeedbackRequest
from app.service.feedback.feedback_service import FeedbackService

router = APIRouter(prefix="/api/v1/feedback", tags=["Feedback"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
async def submit_feedback(
    request: Request,
    body: FeedbackRequest,
    background_tasks: BackgroundTasks,
):
    await enforce_bot_protection(
        request,
        turnstile_token=body.turnstile_token,
        honeypot=body.website,
    )
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="Feedback message is required")

    # Fail fast and clearly when the server has no working mail configuration,
    # so the user is not told "received" when there is no path to deliver it.
    if not settings.mail_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "We could not deliver your feedback right now. Please try again shortly."
            ),
        )

    # Delivery runs after the response is sent, so a slow or blocked SMTP server
    # never makes the visitor wait. FeedbackService logs mail.fail on failure.
    background_tasks.add_task(FeedbackService.deliver_feedback_email, body)
    return {"status": "success", "message": "Feedback received. Thank you!"}
