"""Share-link API.

- ``POST /api/v1/shares``        (authenticated) create a share for a domain-search
                                 or AI-brand result; referrer = current user.
- ``GET  /api/v1/shares/{token}`` (public) sanitized preview with a LIVE registrar
                                 check; issues the signed anonymous visitor cookie.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_optional_current_user
from app.core.exceptions import AppException
from app.entity.share.share_link import ShareType
from app.entity.user.app_user import AppUser
from app.service.share.share_service import ShareService
from app.service.share.visitor_cookie import read_visitor_key, set_visitor_cookie

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/shares", tags=["Shares"])


class ShareCreateRequest(BaseModel):
    share_type: ShareType
    domain: Optional[str] = None
    original_query: Optional[str] = None
    listing_id: Optional[uuid.UUID] = None


@router.post("")
async def create_share(
    body: ShareCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: Optional[AppUser] = Depends(get_optional_current_user),
):
    """Create a shareable link — works for logged-in AND logged-out senders.

    The referrer is always the authenticated user; a logged-out sender creates
    an anonymous share (``referrer_id = NULL``) that can never earn Edge Points.
    """
    service = ShareService(db)
    referrer_visitor_key = read_visitor_key(request)
    share = await service.create_share(
        share_type=body.share_type,
        domain=body.domain,
        original_query=body.original_query,
        listing_id=body.listing_id,
        referrer=current_user,
        referrer_visitor_key=referrer_visitor_key,
    )
    return {
        "success": True,
        "data": {
            "token": share.token,
            "share_url": service.share_url(share, request),
            "share_type": share.share_type.value,
            "domain": share.domain,
            "created_at": share.created_at.isoformat() if share.created_at else None,
        },
    }


@router.get("/{token}")
async def get_share_preview(
    token: str,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
):
    """Public preview: resolve the share, run a LIVE registrar check, sanitize."""
    service = ShareService(db)
    share = await service.resolve_share(token)
    if share is None:
        raise AppException("Share not found.", status_code=404)

    # Issue/refresh the signed anonymous visitor cookie (identity for dedupe).
    if not read_visitor_key(request):
        set_visitor_cookie(response)

    payload = await service.build_preview_payload(share)
    return {"success": True, "data": payload}
