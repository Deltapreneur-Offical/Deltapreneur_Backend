"""Public webhooks for Razorpay and OpenProvider."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_async_db
from app.service.domain.domain_registration_ops_service import DomainRegistrationOpsService

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhooks"])


async def get_ops_service(
    db: AsyncSession = Depends(get_async_db),
) -> DomainRegistrationOpsService:
    return DomainRegistrationOpsService(db)


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None, alias="X-Razorpay-Signature"),
    service: DomainRegistrationOpsService = Depends(get_ops_service),
) -> dict:
    body = await request.body()
    sig = x_razorpay_signature or ""
    return await service.handle_razorpay_webhook(body, sig)


@router.post("/openprovider/domain-status")
async def openprovider_callback(
    body: dict,
    x_openprovider_webhook_secret: str | None = Header(
        None,
        alias="X-OpenProvider-Webhook-Secret",
    ),
    service: DomainRegistrationOpsService = Depends(get_ops_service),
) -> dict:
    expected = settings.OPENPROVIDER_WEBHOOK_SECRET.strip()
    if expected:
        if not x_openprovider_webhook_secret or x_openprovider_webhook_secret != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook credentials.",
            )
    elif settings.ENVIRONMENT == "production":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenProvider webhook secret is not configured.",
        )
    return await service.handle_openprovider_callback(body)
