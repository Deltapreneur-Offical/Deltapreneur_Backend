"""Deltapreneur onboarding routes.

Public:
- POST /api/v1/deltapreneur-onboarding/eligibility   (auth) declare revenue, branch flow
- GET  /api/v1/deltapreneur-onboarding/invitation/validate  (public) landing-page check
- POST /api/v1/deltapreneur-onboarding/applications  (public) apply-to-become form

Admin:
- GET   /api/v1/admin/deltapreneur-applications
- POST  /api/v1/admin/deltapreneur-applications/{id}/approve
- POST  /api/v1/admin/deltapreneur-applications/{id}/reject
- POST  /api/v1/admin/deltapreneur-applications/{id}/invitation
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.entity.user.app_user import AppUser
from app.model.common.api_response import ApiResponse
from app.service.deltapreneur.deltapreneur_onboarding_service import (
    DeltapreneurOnboardingService,
)

router = APIRouter(tags=["Deltapreneur Onboarding"])
admin_router = APIRouter(
    prefix="/api/v1/admin/deltapreneur-applications",
    tags=["AdminDeltapreneur"],
)


class ApplicationCreateRequest(BaseModel):
    """Apply-form payload.

    Accepts BOTH camelCase (frontend) and snake_case via aliases; with
    populate_by_name=True either key style validates, and model_dump(by_alias=True)
    hands the service camelCase (which it also normalizes).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    full_name: str = Field(..., min_length=1, max_length=255, alias="fullName")
    email: EmailStr
    company_name: str | None = Field(default=None, max_length=255, alias="companyName")
    annual_revenue_inr: float = Field(..., ge=0, alias="annualRevenueInr")
    linked_in_url: str | None = Field(default=None, max_length=1000, alias="linkedInUrl")
    website_url: str | None = Field(default=None, max_length=1000, alias="websiteUrl")
    about: str | None = Field(default=None)
    motivation: str | None = Field(default=None)


class ReviewActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None)


class RevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discardActiveLink: bool = Field(default=True)
    reason: str | None = Field(default=None)


@router.post("/api/v1/deltapreneur-onboarding/eligibility", response_model=ApiResponse)
def declare_revenue(
    body: dict,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    """Record self-declared annual revenue and branch the onboarding flow."""
    revenue = body.get("declaredRevenueInr") or body.get("declared_revenue_inr")
    result = DeltapreneurOnboardingService.set_declared_revenue(
        db=db,
        user=current_user,
        declared_revenue_inr=float(revenue),
    )
    return ApiResponse(success=True, message="Revenue recorded", data=result)


@router.get("/api/v1/deltapreneur-onboarding/invitation/validate", response_model=ApiResponse)
def validate_invitation(
    token: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    """Landing-page validation for a secret invitation link (non-sensitive)."""
    data = DeltapreneurOnboardingService.invitation_public_payload(db=db, token=token)
    return ApiResponse(success=True, message="Invitation is valid", data=data)


@router.post("/api/v1/deltapreneur-onboarding/applications", response_model=ApiResponse)
def submit_application(
    request: ApplicationCreateRequest,
    db: Session = Depends(get_db),
):
    """Public Apply-to-Become-Deltapreneur submission (no login, no tracking page)."""
    result = DeltapreneurOnboardingService.submit_application(
        db=db,
        payload=request.model_dump(by_alias=True),
    )
    return ApiResponse(success=True, message=result["message"], data=result)


@admin_router.get("")
def admin_list_applications(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN"])),
):
    return DeltapreneurOnboardingService.list_applications_admin(
        db=db,
        current_user=current_user,
        status_filter=status,
    )


@admin_router.post("/{application_id}/approve")
def admin_approve_application(
    application_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN"])),
):
    return DeltapreneurOnboardingService.review_application(
        db=db,
        current_user=current_user,
        application_id=application_id,
        action="APPROVE",
    )


@admin_router.post("/{application_id}/reject")
def admin_reject_application(
    application_id: str,
    body: ReviewActionRequest | None = None,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN"])),
):
    return DeltapreneurOnboardingService.review_application(
        db=db,
        current_user=current_user,
        application_id=application_id,
        action="REJECT",
        rejection_reason=(body.reason if body else None),
    )


@admin_router.post("/{application_id}/revoke")
def admin_revoke_application(
    application_id: str,
    body: RevokeRequest | None = None,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN"])),
):
    """Undo an approval/onboarding — application returns to Pending Review."""
    return DeltapreneurOnboardingService.revoke_application(
        db=db,
        current_user=current_user,
        application_id=application_id,
        discard_active_link=(body.discardActiveLink if body else True),
        reason=(body.reason if body else None),
    )


@admin_router.post("/{application_id}/reopen")
def admin_reopen_application(
    application_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN"])),
):
    """Move a rejected application back to Pending Review for re-review."""
    return DeltapreneurOnboardingService.reopen_application(
        db=db,
        current_user=current_user,
        application_id=application_id,
    )


@admin_router.post("/{application_id}/invitation")
def admin_generate_invitation(
    application_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_role(["ADMIN"])),
):
    return DeltapreneurOnboardingService.generate_invitation(
        db=db,
        current_user=current_user,
        application_id=application_id,
    )
