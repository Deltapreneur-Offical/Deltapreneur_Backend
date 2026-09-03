import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from jose import JWTError, jwt

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.core.config import settings
from app.core.security import ACCESS_TOKEN_TYPE
from app.core.auth_cookies import get_access_token
from app.entity.user.app_user import AppUser
from app.service.user.edge_points_service import EdgePointsService
from app.service.share.share_service import ShareService
from app.service.share.visitor_cookie import read_visitor_key
from app.services.referral_rate_limiter import referral_rate_limiter
from app.core.client_ip import get_client_ip

router = APIRouter(prefix="/api/v1", tags=["Edge Points"])


class ReferralTrackRequest(BaseModel):
    """New preferred contract: ``share_token`` only — the server resolves the
    referrer and item from the share record. Legacy marketplace links still
    send ``referrer_id`` / ``listing_id`` / ``listing_type``."""
    share_token: Optional[str] = None
    referrer_id: Optional[uuid.UUID] = None
    listing_id: Optional[uuid.UUID] = None
    listing_type: Optional[str] = None


async def _resolve_optional_visitor(request: Request, db: AsyncSession) -> Optional[AppUser]:
    """Resolve the current user from the JWT without raising — returns None for anonymous requests."""
    try:
        from fastapi.security import HTTPBearer
        bearer_scheme = HTTPBearer(auto_error=False)
        credentials = await bearer_scheme(request)
        bearer = credentials.credentials if credentials else None
        token = get_access_token(request, bearer_token=bearer)
        if not token:
            return None
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        # Access JWTs use claim "token_type" (see create_access_token), not "type".
        if payload.get("token_type") != ACCESS_TOKEN_TYPE:
            return None
        email = payload.get("sub")
        if not email:
            return None
        result = await db.execute(
            select(AppUser).filter(
                AppUser.email == email,
                AppUser.is_deleted.is_(False),
                AppUser.active.is_(True),
            )
        )
        return result.scalars().first()
    except (JWTError, Exception):
        return None


@router.get("/edge-points/summary")
async def get_wallet_summary(
    current_user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    summary = await EdgePointsService.get_wallet_summary(db, current_user)
    return {
        "success": True,
        "data": summary
    }

@router.get("/edge-points/history")
async def get_wallet_history(
    current_user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    history = await EdgePointsService.get_wallet_history(db, current_user)
    return {
        "success": True,
        "data": history
    }

@router.get("/edge-points/referral-history")
async def get_referral_history(
    current_user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    referrals = await EdgePointsService.get_referral_history(db, current_user)
    return {
        "success": True,
        "data": referrals
    }

@router.post("/referrals/track")
async def track_referral_link(
    body: ReferralTrackRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    client_ip = get_client_ip(request)
    visitor = await _resolve_optional_visitor(request, db)
    visitor_key = read_visitor_key(request)
    identity = str(visitor.id) if visitor else (visitor_key or client_ip)

    # Preferred: tokenized share link. Referrer + item are resolved server-side.
    if body.share_token:
        share = await ShareService(db).resolve_share(body.share_token)
        if share is None:
            return {"success": False, "message": "Share not found"}
        if not await referral_rate_limiter.check_track(identity=identity, token=body.share_token):
            return {"success": False, "message": "Too many requests. Please try again later."}
        return await EdgePointsService.track_share_referral(
            session=db,
            share=share,
            visitor_ip=client_ip,
            visitor_user=visitor,
            visitor_key_from_cookie=visitor_key,
        )

    # Legacy marketplace `?ref=` links (kept for backward compatibility).
    if body.referrer_id and body.listing_id and body.listing_type:
        if not await referral_rate_limiter.check_track(identity=identity, token=None):
            return {"success": False, "message": "Too many requests. Please try again later."}
        return await EdgePointsService.track_referral(
            session=db,
            referrer_id=body.referrer_id,
            listing_id=body.listing_id,
            listing_type=body.listing_type,
            visitor_ip=client_ip,
            visitor_user=visitor,
        )

    return {
        "success": False,
        "message": "Either share_token or referrer_id/listing_id/listing_type is required.",
    }
