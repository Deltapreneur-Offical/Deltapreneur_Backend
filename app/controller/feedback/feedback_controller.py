# app/controller/feedback/feedback_controller.py

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.bot_protection import enforce_bot_protection
from app.core.database import get_db
from app.core.rate_limiter import limiter
from app.model.feedback.feedback_request import FeedbackRequest
from app.service.feedback.feedback_service import FeedbackService

router = APIRouter(prefix="/api/v1/feedback", tags=["Feedback"])


@router.post("", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def submit_feedback(
    request: Request,
    body: FeedbackRequest,
    db: Session = Depends(get_db),
):
    await enforce_bot_protection(
        request,
        turnstile_token=body.turnstile_token,
        honeypot=body.website,
    )
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="Feedback message is required")

    await FeedbackService.send_feedback_email(body)
    return {"status": "success", "message": "Feedback sent successfully"}
