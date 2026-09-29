"""Deltapreneur onboarding gate: revenue eligibility, applications, secret invitations.

Enforces (server-side) that a NEW creator profile can only be created by a user who is either:

A. Self-declared eligible  — annual revenue >= Rs 40,00,000 (trusted, no proof), or
B. Invited                 — holder of a valid, unused, unexpired secret invitation
                             issued for an APPROVED application.

Grandfathering: users who already have a (non-deleted) community profile are
always eligible — existing Deltapreneurs are unaffected by this gate.

This module is fully independent of Virtual Assistants: no VA entities,
services, routes, statuses, or helpers are imported or reused.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.entity.community.community import Community
from app.entity.deltapreneur.application import DeltapreneurApplication
from app.entity.deltapreneur.invitation import DeltapreneurInvitation
from app.entity.deltapreneur.onboarding_state import DeltapreneurOnboardingState
from app.entity.user.app_user import AppUser
from app.core.config import settings

logger = logging.getLogger(__name__)

# Rs 40 lakh and above qualifies for direct onboarding (exactly 40,00,000 included).
REVENUE_THRESHOLD_INR = 4_000_000

INVITATION_VALIDITY_DAYS = 7

APPLICATION_STATUSES = (
    "PENDING_REVIEW",
    "APPROVED",
    "REJECTED",
    "ONBOARDED",
)

# An UNUSED invitation may only be consumed while its parent application is in
# one of these states. Revocation (back to PENDING_REVIEW) or rejection
# therefore disables an already-sent link immediately, even if its 7-day
# window has not elapsed. (A USED link is already spent and can never be
# reused, and re-approving a revoked application revives a kept link.)
INVITE_USABLE_APPLICATION_STATUSES = ("APPROVED",)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class DeltapreneurOnboardingService:
    # ------------------------------------------------------------------
    # Eligibility gate
    # ------------------------------------------------------------------

    @staticmethod
    def _has_existing_community_profile(db: Session, user_id: uuid.UUID) -> bool:
        community = (
            db.query(Community)
            .filter(
                Community.app_user_id == user_id,
                Community.is_deleted.is_(False),
            )
            .first()
        )
        return community is not None

    @staticmethod
    def is_user_eligible(db: Session, user: AppUser) -> bool:
        """Eligible = grandfathered existing profile OR stored onboarding state."""
        if DeltapreneurOnboardingService._has_existing_community_profile(db, user.id):
            return True
        state = (
            db.query(DeltapreneurOnboardingState)
            .filter(DeltapreneurOnboardingState.app_user_id == user.id)
            .first()
        )
        return state is not None

    @staticmethod
    def ensure_onboarding_eligibility(db: Session, user: AppUser) -> None:
        """Raise 403 unless the user may start the creator LinkedIn onboarding."""
        if DeltapreneurOnboardingService.is_user_eligible(db, user):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Deltapreneur onboarding requires either an annual business revenue "
                "of Rs 40 lakh or above, or an approved invitation."
            ),
        )

    @staticmethod
    def set_declared_revenue(
        db: Session,
        user: AppUser,
        declared_revenue_inr: float,
    ) -> dict[str, Any]:
        """Record self-declared revenue. >= threshold -> eligible; below -> apply route."""
        revenue = _as_float(declared_revenue_inr)
        if revenue is None or revenue < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Enter a valid annual business revenue.",
            )

        if DeltapreneurOnboardingService._has_existing_community_profile(db, user.id):
            # Grandfathered users never need a revenue record.
            return {"eligible": True, "channel": "EXISTING_PROFILE", "thresholdInr": REVENUE_THRESHOLD_INR}

        eligible = revenue >= REVENUE_THRESHOLD_INR
        if not eligible:
            return {
                "eligible": False,
                "nextStep": "APPLY",
                "applyUrl": "/deltapreneurs/apply",
                "thresholdInr": REVENUE_THRESHOLD_INR,
            }

        state = (
            db.query(DeltapreneurOnboardingState)
            .filter(DeltapreneurOnboardingState.app_user_id == user.id)
            .first()
        )
        if state is None:
            state = DeltapreneurOnboardingState(app_user_id=user.id)
        state.declared_revenue_inr = revenue
        state.channel = "SELF_DECLARED"
        db.add(state)
        db.commit()

        return {"eligible": True, "channel": "SELF_DECLARED", "thresholdInr": REVENUE_THRESHOLD_INR}

    # ------------------------------------------------------------------
    # Invitations — validation / consumption (public side)
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_application_allows_invite_use(
        application: DeltapreneurApplication | None,
    ) -> None:
        """An unused invitation is only usable while its application is APPROVED.

        Revocation (back to PENDING_REVIEW), rejection and already-completed
        onboarding all disable the link immediately — even if its 7-day window
        has not elapsed. Fails closed when the application row is missing.
        """
        if application is None or application.status not in INVITE_USABLE_APPLICATION_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=(
                    "This invitation link is no longer valid. "
                    "Please contact the Deltapreneur team."
                ),
            )

    @staticmethod
    def validate_invitation_token(db: Session, token: str) -> DeltapreneurInvitation:
        """Return the invitation row iff token exists, is unused and unexpired.

        Strict application-status gate: the link also stops working the moment
        its parent application is revoked (back to PENDING_REVIEW), rejected,
        or fully onboarded. One-time use and 7-day expiry are unchanged.
        """
        cleaned = (token or "").strip()
        if not cleaned:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation link is invalid.",
            )
        invitation = (
            db.query(DeltapreneurInvitation)
            .filter(DeltapreneurInvitation.token == cleaned)
            .first()
        )
        if invitation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation link is invalid.",
            )
        if invitation.used_at is not None:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="This invitation link has already been used.",
            )
        expires_at = _as_utc(invitation.expires_at)
        if expires_at is None or expires_at <= _utcnow():
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="This invitation link has expired. Please contact the Deltapreneur team.",
            )
        application = (
            db.query(DeltapreneurApplication)
            .filter(DeltapreneurApplication.id == invitation.application_id)
            .first()
        )
        DeltapreneurOnboardingService._assert_application_allows_invite_use(application)
        return invitation

    @staticmethod
    def consume_invitation(
        db: Session,
        token: str,
        user: AppUser,
    ) -> None:
        """Mark the invitation used and record invitation-based eligibility.

        Called from the LinkedIn OAuth callback when the profile is actually
        created through an invitation. One-time use is enforced here.
        """
        invitation = DeltapreneurOnboardingService.validate_invitation_token(db, token)

        # Defense in depth: re-check the application status here (validate does
        # this too) and abort BEFORE any mutation, so a link whose approval was
        # revoked or rejected can never flip the application to ONBOARDED.
        application = (
            db.query(DeltapreneurApplication)
            .filter(DeltapreneurApplication.id == invitation.application_id)
            .first()
        )
        DeltapreneurOnboardingService._assert_application_allows_invite_use(application)

        # Idempotency: already consumed by this same user (OAuth retry) is fine.
        if invitation.used_by_user_id is not None and str(invitation.used_by_user_id) != str(user.id):
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="This invitation link has already been used.",
            )

        now = _utcnow()
        invitation.used_at = now
        invitation.used_by_user_id = user.id
        db.add(invitation)

        state = (
            db.query(DeltapreneurOnboardingState)
            .filter(DeltapreneurOnboardingState.app_user_id == user.id)
            .first()
        )
        if state is None:
            state = DeltapreneurOnboardingState(app_user_id=user.id)
        state.declared_revenue_inr = state.declared_revenue_inr or 0
        state.channel = "INVITATION"
        state.invitation_id = invitation.id
        db.add(state)

        # `application` was fetched and status-checked above.
        if application is not None and application.status != "ONBOARDED":
            application.status = "ONBOARDED"
            application.onboarded_at = now
            db.add(application)

        db.commit()

    @staticmethod
    def invitation_public_payload(db: Session, token: str) -> dict[str, Any]:
        """Non-sensitive info for the invite landing page."""
        invitation = DeltapreneurOnboardingService.validate_invitation_token(db, token)
        application = (
            db.query(DeltapreneurApplication)
            .filter(DeltapreneurApplication.id == invitation.application_id)
            .first()
        )
        return {
            "valid": True,
            "applicantName": application.full_name if application else None,
            "companyName": application.company_name if application else None,
            "expiresAt": _as_utc(invitation.expires_at).isoformat(),
        }

    # ------------------------------------------------------------------
    # Applications (public submission — anonymous, no login required)
    # ------------------------------------------------------------------

    @staticmethod
    def submit_application(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
        full_name = str(payload.get("fullName") or payload.get("full_name") or "").strip()
        email = str(payload.get("email") or "").strip().lower()
        revenue = _as_float(
            payload.get("annualRevenueInr")
            if payload.get("annualRevenueInr") is not None
            else payload.get("annual_revenue_inr")
        )

        if not full_name:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Full name is required.")
        if not email or "@" not in email:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A valid email address is required.")
        if revenue is None or revenue < 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A valid annual revenue is required.")

        application = DeltapreneurApplication(
            full_name=full_name,
            email=email,
            company_name=(str(payload.get("companyName") or payload.get("company_name") or "").strip() or None),
            annual_revenue_inr=revenue,
            linked_in_url=(str(payload.get("linkedInUrl") or payload.get("linked_in_url") or "").strip() or None),
            website_url=(str(payload.get("websiteUrl") or payload.get("website_url") or "").strip() or None),
            about=(str(payload.get("about") or "").strip() or None),
            motivation=(str(payload.get("motivation") or "").strip() or None),
            status="PENDING_REVIEW",
        )
        db.add(application)
        db.commit()
        db.refresh(application)

        logger.info("Deltapreneur application submitted id=%s email=%s", application.id, email)
        return {
            "success": True,
            "message": (
                "Your application has been submitted successfully. Our team will review it "
                "and contact you through the email address provided."
            ),
        }

    # ------------------------------------------------------------------
    # Admin — applications + invitations
    # ------------------------------------------------------------------

    @staticmethod
    def _require_admin(current_user: AppUser) -> None:
        role = (getattr(current_user, "role", "") or "").upper()
        if role != "ADMIN":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")

    @staticmethod
    def _invitation_status(invitation: DeltapreneurInvitation | None) -> str | None:
        if invitation is None:
            return None
        if invitation.used_at is not None:
            return "INVITATION_USED"
        expires_at = _as_utc(invitation.expires_at)
        if expires_at is not None and expires_at <= _utcnow():
            return "INVITATION_EXPIRED"
        return "INVITATION_ACTIVE"

    @staticmethod
    def _serialize_application(
        db: Session,
        application: DeltapreneurApplication,
    ) -> dict[str, Any]:
        invitation = (
            db.query(DeltapreneurInvitation)
            .filter(
                DeltapreneurInvitation.application_id == application.id,
                DeltapreneurInvitation.used_at.is_(None),
            )
            .order_by(DeltapreneurInvitation.created_at.desc())
            .first()
        )
        latest_any = invitation or (
            db.query(DeltapreneurInvitation)
            .filter(DeltapreneurInvitation.application_id == application.id)
            .order_by(DeltapreneurInvitation.created_at.desc())
            .first()
        )

        combined = application.status
        invitation_status = DeltapreneurOnboardingService._invitation_status(latest_any)
        if application.status == "APPROVED":
            combined = invitation_status or "APPROVED"

        # The secret link is only hand-out-able while the application is
        # APPROVED — mirrors the strict consume gate. A link kept across a
        # revoke stays in the audit trail (invitation.status may still read
        # INVITATION_ACTIVE) but is NOT exposed for copying/emailing until the
        # application is re-approved, after which the same link works again.
        active_link_url = None
        if (
            latest_any is not None
            and invitation_status == "INVITATION_ACTIVE"
            and application.status == "APPROVED"
        ):
            active_link_url = DeltapreneurOnboardingService.build_invitation_url(latest_any.token)

        return {
            "id": str(application.id),
            "fullName": application.full_name,
            "email": application.email,
            "companyName": application.company_name,
            "annualRevenueInr": float(application.annual_revenue_inr or 0),
            "linkedInUrl": application.linked_in_url,
            "websiteUrl": application.website_url,
            "about": application.about,
            "motivation": application.motivation,
            "status": application.status,
            "displayStatus": combined,
            "applicationDate": application.created_at.isoformat() if application.created_at else None,
            "reviewedAt": application.reviewed_at.isoformat() if application.reviewed_at else None,
            "rejectionReason": application.rejection_reason,
            "onboardedAt": application.onboarded_at.isoformat() if application.onboarded_at else None,
            "invitation": (
                {
                    "status": invitation_status,
                    "expiresAt": _as_utc(latest_any.expires_at).isoformat() if latest_any else None,
                    "usedAt": _as_utc(latest_any.used_at).isoformat() if latest_any and latest_any.used_at else None,
                    "linkUrl": active_link_url,
                }
                if latest_any is not None
                else None
            ),
        }

    @staticmethod
    def build_invitation_url(token: str) -> str:
        base = (settings.FRONTEND_BASE_URL or "").rstrip("/")
        return f"{base}/creator/invite/{token}"

    @staticmethod
    def list_applications_admin(
        db: Session,
        current_user: AppUser,
        status_filter: str | None = None,
    ) -> dict[str, Any]:
        DeltapreneurOnboardingService._require_admin(current_user)
        query = db.query(DeltapreneurApplication).order_by(
            DeltapreneurApplication.created_at.desc()
        )
        if status_filter:
            query = query.filter(DeltapreneurApplication.status == status_filter.upper())
        rows = query.all()
        data = [DeltapreneurOnboardingService._serialize_application(db, r) for r in rows]
        return {"success": True, "count": len(data), "data": data, "items": data}

    @staticmethod
    def _get_application(db: Session, application_id: str) -> DeltapreneurApplication:
        try:
            app_uuid = uuid.UUID(str(application_id))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.") from None
        application = (
            db.query(DeltapreneurApplication)
            .filter(DeltapreneurApplication.id == app_uuid)
            .first()
        )
        if application is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
        return application

    @staticmethod
    def review_application(
        db: Session,
        current_user: AppUser,
        application_id: str,
        action: str,
        rejection_reason: str | None = None,
    ) -> dict[str, Any]:
        """Approve or reject a pending application. No automatic approval exists."""
        DeltapreneurOnboardingService._require_admin(current_user)
        application = DeltapreneurOnboardingService._get_application(db, application_id)

        if application.status not in ("PENDING_REVIEW", "REJECTED"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Application is already {application.status}.",
            )

        action_clean = (action or "").strip().upper()
        now = _utcnow()

        if action_clean == "APPROVE":
            application.status = "APPROVED"
            application.rejection_reason = None
        elif action_clean == "REJECT":
            application.status = "REJECTED"
            application.rejection_reason = (rejection_reason or "").strip() or None
            # A rejection invalidates any unused invitations for this application.
            for inv in (
                db.query(DeltapreneurInvitation)
                .filter(
                    DeltapreneurInvitation.application_id == application.id,
                    DeltapreneurInvitation.used_at.is_(None),
                )
                .all()
            ):
                inv.expires_at = now
                db.add(inv)
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Action must be APPROVE or REJECT.",
            )

        application.reviewed_at = now
        application.reviewed_by_id = current_user.id
        db.add(application)
        db.commit()

        return DeltapreneurOnboardingService._serialize_application(db, application)

    @staticmethod
    def _expire_unused_invitations(db: Session, application_id: uuid.UUID) -> int:
        """Expire every unused invitation of an application (rejection-style)."""
        now = _utcnow()
        unused = (
            db.query(DeltapreneurInvitation)
            .filter(
                DeltapreneurInvitation.application_id == application_id,
                DeltapreneurInvitation.used_at.is_(None),
            )
            .all()
        )
        for inv in unused:
            inv.expires_at = now
            db.add(inv)
        return len(unused)

    @staticmethod
    def revoke_application(
        db: Session,
        current_user: AppUser,
        application_id: str,
        discard_active_link: bool = True,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Undo an approval/onboarding: application returns to PENDING_REVIEW.

        Robust reversal with an audit trail (no rows are hard-deleted):
        - APPROVED: back to PENDING_REVIEW.  Active unused links are either
          discarded (default — the emailed link stops working immediately) or
          kept as an unexpired row.  NOTE: even a kept link can no longer be
          consumed while the application is PENDING_REVIEW (strict status gate
          in validate_invitation_token); re-approving the application revives it.
        - ONBOARDED (link already used): full revoke — the invitation-based
          onboarding state is removed so the revenue gate re-engages, the
          application returns to PENDING_REVIEW, and the used-link row is kept
          for audit.  The applicant's community profile is NOT deleted.
        """
        DeltapreneurOnboardingService._require_admin(current_user)
        application = DeltapreneurOnboardingService._get_application(db, application_id)

        if application.status not in ("APPROVED", "ONBOARDED"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Only approved or onboarded applications can be revoked. "
                    f"This application is {application.status}."
                ),
            )

        now = _utcnow()
        was_onboarded = application.status == "ONBOARDED"

        # 1) Unused invitation links: discard (expire now) or keep active.
        discarded = 0
        if discard_active_link:
            discarded = DeltapreneurOnboardingService._expire_unused_invitations(
                db, application.id
            )

        # 2) Full revoke for onboarded applicants: remove the INVITATION-channel
        #    onboarding state created by consuming THIS application's link.
        eligibility_removed = False
        if was_onboarded:
            invitation_ids = [
                row[0]
                for row in db.query(DeltapreneurInvitation.id)
                .filter(DeltapreneurInvitation.application_id == application.id)
                .all()
            ]
            if invitation_ids:
                state = (
                    db.query(DeltapreneurOnboardingState)
                    .filter(
                        DeltapreneurOnboardingState.invitation_id.in_(invitation_ids),
                        DeltapreneurOnboardingState.app_user_id.isnot(None),
                    )
                    .first()
                )
                if state is not None:
                    db.delete(state)
                    eligibility_removed = True

        # 3) Back to review; audit fields updated, onboarded marker cleared.
        application.status = "PENDING_REVIEW"
        application.onboarded_at = None
        application.reviewed_at = now
        application.reviewed_by_id = current_user.id
        application.rejection_reason = (reason or "").strip() or None
        db.add(application)
        db.commit()

        serialized = DeltapreneurOnboardingService._serialize_application(db, application)
        serialized["revoked"] = {
            "wasOnboarded": was_onboarded,
            "linksDiscarded": discarded,
            "eligibilityRemoved": eligibility_removed,
        }
        return serialized

    @staticmethod
    def reopen_application(
        db: Session,
        current_user: AppUser,
        application_id: str,
    ) -> dict[str, Any]:
        """Move a REJECTED application back to PENDING_REVIEW for re-review."""
        DeltapreneurOnboardingService._require_admin(current_user)
        application = DeltapreneurOnboardingService._get_application(db, application_id)

        if application.status != "REJECTED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Only rejected applications can be moved back to review. "
                    f"This application is {application.status}."
                ),
            )

        now = _utcnow()
        application.status = "PENDING_REVIEW"
        application.rejection_reason = None
        application.reviewed_at = now
        application.reviewed_by_id = current_user.id
        db.add(application)
        db.commit()

        return DeltapreneurOnboardingService._serialize_application(db, application)

    @staticmethod
    def generate_invitation(
        db: Session,
        current_user: AppUser,
        application_id: str,
    ) -> dict[str, Any]:
        """Generate (or regenerate) a one-time 7-day invitation link.

        Rules enforced server-side:
        - only APPROVED applications (not REJECTED / ONBOARDED) may get links
        - an ACTIVE unused link blocks regeneration until it expires
        - a USED link can never be regenerated
        """
        DeltapreneurOnboardingService._require_admin(current_user)
        application = DeltapreneurOnboardingService._get_application(db, application_id)

        if application.status == "ONBOARDED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Applicant is already onboarded. No invitation can be generated.",
            )
        if application.status == "PENDING_REVIEW":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Approve the application before generating an invitation.",
            )
        if application.status == "REJECTED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Rejected applications cannot receive invitations.",
            )

        active = (
            db.query(DeltapreneurInvitation)
            .filter(
                DeltapreneurInvitation.application_id == application.id,
                DeltapreneurInvitation.used_at.is_(None),
            )
            .order_by(DeltapreneurInvitation.created_at.desc())
            .first()
        )
        if active is not None:
            active_status = DeltapreneurOnboardingService._invitation_status(active)
            if active_status == "INVITATION_ACTIVE":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "An active invitation already exists. It must expire or be used "
                        "before a new link can be generated."
                    ),
                )
            # Expired unused invitation -> allowed to regenerate (old one stays expired).

        now = _utcnow()
        invitation = DeltapreneurInvitation(
            application_id=application.id,
            token=secrets.token_urlsafe(48)[:128],
            expires_at=now + timedelta(days=INVITATION_VALIDITY_DAYS),
            created_by_admin_id=current_user.id,
        )
        db.add(invitation)
        db.commit()
        db.refresh(invitation)

        return {
            "success": True,
            "invitation": {
                "status": "INVITATION_ACTIVE",
                "expiresAt": invitation.expires_at.isoformat(),
                "linkUrl": DeltapreneurOnboardingService.build_invitation_url(invitation.token),
            },
        }
