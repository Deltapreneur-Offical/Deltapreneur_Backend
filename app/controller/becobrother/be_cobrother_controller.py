# app/controller/becobrother/be_cobrother_controller.py

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.bot_protection import enforce_bot_protection
from app.core.database import get_db
from app.core.rate_limiter import limiter
from app.model.becobrother.be_cobrother import BeCoBrother
from app.service.becobrother.be_cobrother_service import BeCoBrotherService

router = APIRouter(prefix="/api/v1/becobrother", tags=["BeCoBrother"])


@router.post("", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
async def joining_request(
    request: Request,
    body: BeCoBrother,
    db: Session = Depends(get_db),
):
    await enforce_bot_protection(
        request,
        turnstile_token=body.turnstile_token,
        honeypot=body.website,
    )
    if not body.fullName or not body.fullName.strip():
        raise HTTPException(status_code=400, detail="Full name is required")
    if not body.email or not body.email.strip():
        raise HTTPException(status_code=400, detail="Email is required")

    await BeCoBrotherService.joining_request(db, body)
    return {"status": "success", "message": "Application submitted successfully"}
