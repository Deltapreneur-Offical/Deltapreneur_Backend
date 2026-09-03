from datetime import date, datetime, timezone
import logging
import uuid
from sqlalchemy import and_, exists, func, or_
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import Session

from fastapi import HTTPException
from fastapi import status

logger = logging.getLogger(__name__)

from app.entity.user.app_user import AppUser
from app.entity.virtual_assistant.virtual_assistant_entity import VirtualAssistantApplication
from app.entity.virtual_assistant.application_role_entity import ApplicationRole
from app.entity.virtual_assistant.workspace_entity import VAAssignment
from app.entity.virtual_assistant.workspace_entity import VANotification
from app.repository.admin_audit_log_repository import AdminAuditLogRepository
from app.service.virtual_assistant.reference_number_service import (
    allocate_application_numbers,
    application_number_fields,
)
from app.service.virtual_assistant.va_media import (
    resolve_va_profile_photo_url,
    resolve_va_storage_media_url,
    upload_va_profile_photo_to_s3,
    validate_linkedin_profile_url,
    validate_resume_link,
)
from app.service.virtual_assistant.virtual_assistant_service import (
    _validate_profile_photo,
)
from app.utils.virtual_assistant_roles import normalize_va_role_name


class VirtualAssistantAdminService:
    @staticmethod
    def _create_va_notification(
        db: Session,
        application_id,
        notification_type: str,
        message: str | None = None,
        title: str | None = None,
        target_url: str | None = None,
        related_assignment_id=None,
    ) -> None:
        try:
            if isinstance(application_id, str):
                application_id = uuid.UUID(application_id)

            app_row = (
                db.query(VirtualAssistantApplication)
                .filter(VirtualAssistantApplication.id == application_id)
                .first()
            )
            if not app_row:
                logger.warning("_create_va_notification: Application %s not found", application_id)
                return

            va_id = app_row.user_id
            if not va_id and app_row.email:
                user = db.query(AppUser).filter(AppUser.email == app_row.email.strip().lower()).first()
                if user:
                    va_id = user.id
                    app_row.user_id = user.id
                    db.flush()

            if not va_id:
                logger.warning("_create_va_notification: No user_id associated with application %s", application_id)
                return

            if isinstance(va_id, str):
                va_id = uuid.UUID(va_id)

            final_title = title.strip() if title else None
            final_message = message.strip() if message else None

            if not final_title and final_message:
                final_title = final_message
                final_message = None
            elif final_title and final_message:
                norm_t = final_title.rstrip(".").lower()
                norm_m = final_message.rstrip(".").lower()
                if norm_t == norm_m:
                    final_message = None

            if not final_title:
                final_title = notification_type.replace("_", " ").title()

            db.add(
                VANotification(
                    va_id=va_id,
                    related_application_id=application_id,
                    notification_type=notification_type,
                    title=final_title,
                    message=final_message,
                    target_url=target_url,
                    related_assignment_id=related_assignment_id,
                )
            )
            db.commit()
        except Exception as exc:
            logger.exception("Failed to create VA notification for application_id %s: %s", application_id, exc)
            db.rollback()


    @staticmethod
    def list_applications(
        db: Session,
        search: str | None,
        status_filter: str | None,
        role_filter: str | None,
        date_from: date | None,
        date_to: date | None,
        page: int,
        page_size: int,
        publish_status: str | None = None,
    ) -> dict:
        query = db.query(VirtualAssistantApplication).filter(
            VirtualAssistantApplication.is_deleted.is_(False)
        )

        if search:
            pattern = f"%{search.lower()}%"
            search_filters = [
                func.lower(VirtualAssistantApplication.full_name).like(pattern),
                func.lower(VirtualAssistantApplication.email).like(pattern),
                func.lower(VirtualAssistantApplication.phone_number).like(pattern),
                func.lower(VirtualAssistantApplication.reference_number).like(pattern),
            ]
            if search.strip().isdigit():
                search_filters.append(VirtualAssistantApplication.application_number == int(search.strip()))
            query = query.filter(or_(*search_filters))

        if status_filter:
            # The Applications module filters by the overall lifecycle status.
            # "under_review" is tracked on the legacy string `status` column;
            # the remaining values map to the `overall_status` enum.
            if status_filter == "under_review":
                query = query.filter(VirtualAssistantApplication.status == "reviewing")
            elif status_filter in {"pending", "partially_approved", "approved", "rejected"}:
                query = query.filter(VirtualAssistantApplication.overall_status == status_filter)

        if role_filter:
            query = query.filter(
                VirtualAssistantApplication.roles.ilike(f"%{role_filter}%")
            )

        if publish_status in {"draft", "published", "unpublished"}:
            query = query.filter(VirtualAssistantApplication.publish_status == publish_status)

        if date_from:
            query = query.filter(
                func.date(VirtualAssistantApplication.created_at) >= date_from
            )

        if date_to:
            query = query.filter(
                func.date(VirtualAssistantApplication.created_at) <= date_to
            )

        total = query.count()
        offset = (page - 1) * page_size
        rows = (
            query.order_by(VirtualAssistantApplication.created_at.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )

        return {
            "items": [VirtualAssistantAdminService._serialize(r) for r in rows],
            "total": total,
            "page": page,
            "pageSize": page_size,
            "totalPages": (total + page_size - 1) // page_size if total > 0 else 0,
        }

    @staticmethod
    def get_application(db: Session, application_id) -> dict | None:
        row = db.query(VirtualAssistantApplication).filter(
            VirtualAssistantApplication.id == application_id
        ).first()
        if not row or row.is_deleted:
            return None
        VirtualAssistantAdminService._ensure_roles(db, row)
        return VirtualAssistantAdminService._serialize_detail(db, row)

    @staticmethod
    def list_application_roles(db: Session, application_id) -> list[dict]:
        from app.entity.user.app_user import AppUser

        row = db.query(VirtualAssistantApplication).filter(
            VirtualAssistantApplication.id == application_id
        ).first()
        if not row or row.is_deleted:
            return []
        VirtualAssistantAdminService._ensure_roles(db, row)
        roles = (
            db.query(ApplicationRole)
            .filter(ApplicationRole.application_id == application_id)
            .order_by(ApplicationRole.role_name)
            .all()
        )
        reviewer_ids = [r.reviewed_by_id for r in roles if r.reviewed_by_id]
        reviewer_map = {}
        if reviewer_ids:
            import uuid as _uuid

            parsed_ids = []
            for rid in reviewer_ids:
                try:
                    parsed_ids.append(_uuid.UUID(rid))
                except (ValueError, AttributeError, TypeError):
                    continue
            if parsed_ids:
                reviewers = (
                    db.query(AppUser)
                    .filter(AppUser.id.in_(parsed_ids))
                    .all()
                )
                for u in reviewers:
                    name = " ".join(filter(None, [u.firstname, u.lastname])).strip() or u.email
                    reviewer_map[str(u.id)] = name
        return [
            {
                "id": str(r.id),
                "roleName": r.role_name,
                "status": r.status,
                "reviewedAt": r.reviewed_at.isoformat() if r.reviewed_at else None,
                "reviewedBy": reviewer_map.get(r.reviewed_by_id) if r.reviewed_by_id else None,
                "rejectionNote": r.rejection_note,
            }
            for r in roles
        ]

    @staticmethod
    def count_by_status(db: Session) -> dict:
        """Return per-tab counts used by the Applications list page."""
        base = db.query(VirtualAssistantApplication).filter(
            VirtualAssistantApplication.is_deleted.is_(False)
        )
        total = base.count()
        under_review = base.filter(
            VirtualAssistantApplication.status == "reviewing"
        ).count()
        counts = {s: 0 for s in ("pending", "under_review", "partially_approved", "approved", "rejected")}
        counts["under_review"] = under_review
        for status in ("pending", "partially_approved", "approved", "rejected"):
            counts[status] = base.filter(
                VirtualAssistantApplication.overall_status == status
            ).count()
        counts["all"] = total
        return counts

    @staticmethod
    def _ensure_roles(db: Session, row: VirtualAssistantApplication) -> None:
        """Backfill per-role rows from the legacy ``roles`` CSV string.

        Older submissions stored selected roles only as a comma-separated
        string. The detail/role-review UI relies on individual ``ApplicationRole``
        rows, so seed them lazily the first time they are requested.
        """
        existing = (
            db.query(ApplicationRole)
            .filter(ApplicationRole.application_id == row.id)
            .count()
        )
        if existing > 0 or not row.roles:
            return
        names = [r.strip() for r in row.roles.split(",") if r.strip()]
        if not names:
            return
        for name in names:
            db.add(ApplicationRole(application_id=row.id, role_name=name, status="pending"))
        db.commit()

    @staticmethod
    def update_status(db: Session, application_id, new_status: str) -> dict | None:
        row = db.query(VirtualAssistantApplication).filter(
            VirtualAssistantApplication.id == application_id
        ).first()
        if not row or row.is_deleted:
            return None
        if new_status == "partially_approved":
            # overall_status is derived from role approvals; refresh and return.
            VirtualAssistantAdminService._recompute_overall_status(db, application_id)
            VirtualAssistantAdminService._recompute_workspace_lock(db, application_id)
            db.commit()
            db.refresh(row)
            return VirtualAssistantAdminService._serialize_detail(db, row)
        if new_status not in {"pending", "reviewing", "accepted", "rejected"}:
            return None
        row.status = new_status
        if new_status in {"accepted", "rejected"}:
            row.reviewed_at = datetime.now(timezone.utc)
        VirtualAssistantAdminService._recompute_overall_status(db, application_id)
        VirtualAssistantAdminService._recompute_workspace_lock(db, application_id)
        db.commit()
        db.refresh(row)
        return VirtualAssistantAdminService._serialize_detail(db, row)

    @staticmethod
    def update_role_status(
        db: Session,
        application_id,
        role_id,
        new_status: str,
        rejection_note: str | None = None,
        reviewer_id: str | None = None,
        reviewer_name: str | None = None,
    ) -> dict | None:
        role = (
            db.query(ApplicationRole)
            .filter(
                and_(
                    ApplicationRole.id == role_id,
                    ApplicationRole.application_id == application_id,
                )
            )
            .first()
        )
        if not role:
            return None
        role.status = new_status
        role.rejection_note = rejection_note if new_status == "rejected" else (rejection_note or role.rejection_note)
        if new_status in {"approved", "rejected"}:
            role.reviewed_at = datetime.now(timezone.utc)
            role.reviewed_by_id = reviewer_id
        db.commit()
        db.refresh(role)
        app_row = db.query(VirtualAssistantApplication).filter(
            VirtualAssistantApplication.id == application_id
        ).first()
        if not app_row or app_row.is_deleted:
            return VirtualAssistantAdminService._serialize_role(role)
        was_locked = bool(app_row.workspace_locked)
        VirtualAssistantAdminService._recompute_overall_status(db, application_id)
        VirtualAssistantAdminService._recompute_workspace_lock(db, application_id)
        db.commit()
        db.refresh(app_row)
        if new_status == "approved":
            VirtualAssistantAdminService._create_va_notification(
                db, application_id, "role_approval",
                f"Your role '{role.role_name}' has been approved.",
            )
        elif new_status == "rejected":
            VirtualAssistantAdminService._create_va_notification(
                db, application_id, "role_rejected",
                f"Your role '{role.role_name}' has been rejected.",
            )
        if was_locked and not app_row.workspace_locked:
            VirtualAssistantAdminService._create_va_notification(
                db, application_id, "workspace_unlocked",
                "Your Virtual Assistant Workspace has been unlocked.",
            )
        return VirtualAssistantAdminService._serialize_role(role)

    @staticmethod
    def notify_role_decisions(
        db: Session,
        application_id,
        updated_roles: list[dict],
        reviewer_name: str | None = None,
    ) -> None:
        """Send a single combined email to the applicant summarising role decisions.

        Detects whether the Virtual Assistant Workspace was unlocked (i.e. at least
        one role is now approved for the first time) so the email can mention it.
        """
        row = db.query(VirtualAssistantApplication).filter(
            VirtualAssistantApplication.id == application_id
        ).first()
        if not row or not row.email:
            return

        roles = (
            db.query(ApplicationRole)
            .filter(ApplicationRole.application_id == application_id)
            .order_by(ApplicationRole.role_name)
            .all()
        )
        has_approved = any(r.status == "approved" for r in roles)
        workspace_unlocked = has_approved

        try:
            from app.service.auth.mail_service import MailService

            coro = MailService.send_virtual_assistant_role_decision_email(
                to_email=row.email,
                full_name=row.full_name,
                reference_number=row.reference_number,
                roles=[
                    {
                        "roleName": r.role_name,
                        "status": r.status,
                        "rejectionNote": r.rejection_note,
                    }
                    for r in roles
                ],
                overall_status=row.overall_status,
                reviewer_name=reviewer_name,
                workspace_unlocked=workspace_unlocked,
            )
            VirtualAssistantAdminService._run_async(coro)
        except Exception:  # pragma: no cover - email failures must not break review
            import logging

            logging.getLogger(__name__).exception(
                "virtual_assistant.role_decision.email.failed id=%s", application_id
            )

    @staticmethod
    def _run_async(coro):
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return asyncio.run(coro)

    @staticmethod
    def _recompute_overall_status(db: Session, application_id) -> None:
        row = db.query(VirtualAssistantApplication).filter(
            VirtualAssistantApplication.id == application_id
        ).first()
        if not row:
            return
        roles = (
            db.query(ApplicationRole)
            .filter(ApplicationRole.application_id == application_id)
            .all()
        )
        if not roles:
            row.overall_status = "pending"
            return
        statuses = {r.status for r in roles}
        if statuses == {"approved"}:
            row.overall_status = "approved"
        elif statuses == {"rejected"}:
            row.overall_status = "rejected"
        elif "approved" in statuses and "rejected" not in statuses:
            row.overall_status = "partially_approved"
        elif "rejected" in statuses and "approved" not in statuses:
            row.overall_status = "rejected"
        elif "approved" in statuses and "rejected" in statuses:
            # At least one approved while others are rejected/pending → partial.
            row.overall_status = "partially_approved"
        else:
            row.overall_status = "pending"
        VirtualAssistantAdminService._recompute_workspace_lock(db, application_id)

    @staticmethod
    def _recompute_workspace_lock(db: Session, application_id) -> None:
        row = db.query(VirtualAssistantApplication).filter(
            VirtualAssistantApplication.id == application_id
        ).first()
        if not row:
            return
        roles = (
            db.query(ApplicationRole)
            .filter(ApplicationRole.application_id == application_id)
            .all()
        )
        has_approved = any(r.status == "approved" for r in roles)
        row.workspace_locked = not has_approved

    @staticmethod
    def _serialize(row: VirtualAssistantApplication) -> dict:
        def _clean_url(url):
            if not url or not isinstance(url, str):
                return None
            lower = url.lower()
            if any(p in lower for p in ["example.com", "storage.example.com", "placeholder", "test.com", "dummy"]):
                return None
            return url

        payload = {
            "id": str(row.id),
            "userId": row.user_id,
            "referenceNumber": row.reference_number,
            "fullName": row.full_name,
            "email": row.email,
            "phoneNumber": row.phone_number,
            "location": row.location,
            "profilePhotoUrl": resolve_va_profile_photo_url(
                row.profile_photo_url, row.profile_photo_key
            ),
            "isAdult": row.consent_adult,
            "bio": row.short_bio,
            "roles": row.roles,
            "skills": row.skills,
            "yearsExperience": row.years_experience,
            "languagesKnown": row.languages_known,
            "linkedinUrl": _clean_url(row.linkedin_url),
            "portfolioUrl": _clean_url(row.portfolio_url),
            "resumeUrl": (
                _clean_url(row.resume_url)
                if (row.resume_url and not row.resume_key)
                else (
                    resolve_va_storage_media_url(row.resume_url, row.resume_key)
                    or _clean_url(row.resume_url)
                )
            ),
            "availability": row.availability,
            "hoursPerWeek": row.hours_per_week,
            "expectedCompensation": row.expected_compensation,
            "publicMonthlyPriceInr": row.public_monthly_price_inr,
            "pricingCurrency": row.pricing_currency,
            "maxClientCapacity": row.max_client_capacity,
            "pricingUpdatedById": row.pricing_updated_by_id,
            "pricingUpdatedAt": row.pricing_updated_at.isoformat() if row.pricing_updated_at else None,
            "publishStatus": row.publish_status,
            "publishedAt": row.published_at.isoformat() if row.published_at else None,
            "publishedById": row.published_by_id,
            "publishedByName": row.published_by_name,
            "consentAccurate": row.consent_accurate,
            "consentTerms": row.consent_terms,
            "consentAdult": row.consent_adult,
            "status": row.status,
            "overallStatus": row.overall_status,
            "workspaceLocked": row.workspace_locked,
            "adminNotes": row.admin_notes,
            "createdAt": row.created_at.isoformat() if row.created_at else None,
            "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
            "featured": bool(getattr(row, "featured", False)),
        }
        payload.update(application_number_fields(row))
        return payload

    @staticmethod
    def _active_approved_role_exists():
        """SQL exists() clause: application has at least one approved, active role."""
        return exists().where(
            and_(
                ApplicationRole.application_id == VirtualAssistantApplication.id,
                ApplicationRole.status == "approved",
                ApplicationRole.is_active.is_(True),
            )
        )

    @staticmethod
    def apply_public_marketplace_filters(query):
        """Restrict to publicly listable VA profiles per architecture rules."""
        return (
            query.filter(VirtualAssistantApplication.is_deleted.is_(False))
            .filter(VirtualAssistantApplication.publish_status == "published")
            .filter(VirtualAssistantApplication.overall_status == "approved")
            .filter(VirtualAssistantApplication.public_monthly_price_inr.isnot(None))
            .filter(VirtualAssistantApplication.public_monthly_price_inr >= 0)
            .filter(VirtualAssistantAdminService._active_approved_role_exists())
        )

    @staticmethod
    def is_publicly_listable(db: Session, row: VirtualAssistantApplication) -> bool:
        if not row or row.is_deleted:
            return False
        if row.publish_status != "published" or row.overall_status != "approved":
            return False
        if row.public_monthly_price_inr is None or row.public_monthly_price_inr < 0:
            return False
        active_approved = (
            db.query(ApplicationRole.id)
            .filter(
                ApplicationRole.application_id == row.id,
                ApplicationRole.status == "approved",
                ApplicationRole.is_active.is_(True),
            )
            .first()
        )
        return active_approved is not None

    @staticmethod
    def _public_application_roles(db: Session, application_id) -> list[dict]:
        roles = (
            db.query(ApplicationRole)
            .filter(
                ApplicationRole.application_id == application_id,
                ApplicationRole.status == "approved",
                ApplicationRole.is_active.is_(True),
            )
            .order_by(ApplicationRole.role_name)
            .all()
        )
        return [
            {
                "id": str(role.id),
                "roleName": role.role_name,
                "status": role.status,
                "maxClients": role.max_clients,
                "currentClients": role.current_clients,
                "isActive": role.is_active,
                "availabilityStatus": VirtualAssistantAdminService._role_availability_status(role),
            }
            for role in roles
        ]

    @staticmethod
    def _public_view_count(db: Session, application_id) -> int:
        try:
            import uuid
            from app.repository.virtual_assistant_view_repository import VirtualAssistantViewRepository

            return VirtualAssistantViewRepository.count_by_application_id(
                db,
                uuid.UUID(str(application_id)),
            )
        except Exception:
            return 0

    @staticmethod
    def _serialize_public(db: Session, row: VirtualAssistantApplication) -> dict:
        public_roles = VirtualAssistantAdminService._public_application_roles(db, row.id)
        approved_role_names = [role["roleName"] for role in public_roles]

        def _clean_url(url):
            if not url or not isinstance(url, str):
                return None
            lower = url.lower()
            if any(p in lower for p in ["example.com", "storage.example.com", "placeholder", "test.com", "dummy"]):
                return None
            return url

        payload = {
            "id": str(row.id),
            "referenceNumber": row.reference_number,
            "fullName": row.full_name,
            "location": row.location,
            "profilePhotoUrl": resolve_va_profile_photo_url(
                row.profile_photo_url, row.profile_photo_key
            ),
            "bio": row.short_bio,
            "roles": ", ".join(approved_role_names) if approved_role_names else (row.roles or ""),
            "skills": row.skills,
            "yearsExperience": row.years_experience,
            "languagesKnown": row.languages_known,
            "linkedinUrl": _clean_url(row.linkedin_url),
            "portfolioUrl": _clean_url(row.portfolio_url),
            "availability": row.availability,
            "hoursPerWeek": row.hours_per_week,
            "publicMonthlyPriceInr": row.public_monthly_price_inr,
            "pricingCurrency": row.pricing_currency or "INR",
            "maxClientCapacity": row.max_client_capacity,
            "publishedAt": row.published_at.isoformat() if row.published_at else None,
            "publishStatus": row.publish_status,
            "overallStatus": row.overall_status,
            "featured": bool(getattr(row, "featured", False)),
            "views": VirtualAssistantAdminService._public_view_count(db, row.id),
            "applicationRoles": public_roles,
        }
        payload.update(application_number_fields(row))
        return payload

    @staticmethod
    def list_public_profiles(
        db: Session,
        *,
        search: str | None = None,
        role: str | None = None,
        skills: str | None = None,
        languages: str | None = None,
        availability: str | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        experience: str | None = None,
        sort_by: str | None = "recently_published",
        featured_only: bool = False,
        page: int = 1,
        page_size: int = 12,
    ) -> dict:
        query = VirtualAssistantAdminService.apply_public_marketplace_filters(
            db.query(VirtualAssistantApplication)
        )

        if featured_only:
            query = query.filter(VirtualAssistantApplication.featured.is_(True))

        if search:
            like = f"%{search.lower()}%"
            search_filters = [
                VirtualAssistantApplication.full_name.ilike(like),
                VirtualAssistantApplication.roles.ilike(like),
                VirtualAssistantApplication.skills.ilike(like),
                VirtualAssistantApplication.languages_known.ilike(like),
                VirtualAssistantApplication.reference_number.ilike(like),
            ]
            if search.strip().isdigit():
                search_filters.append(VirtualAssistantApplication.application_number == int(search.strip()))
            query = query.filter(or_(*search_filters))
        if role:
            query = query.filter(VirtualAssistantApplication.roles.ilike(f"%{role}%"))
        if skills:
            for skill in [s.strip() for s in skills.split(",") if s.strip()]:
                query = query.filter(VirtualAssistantApplication.skills.ilike(f"%{skill}%"))
        if languages:
            for lang in [l.strip() for l in languages.split(",") if l.strip()]:
                query = query.filter(VirtualAssistantApplication.languages_known.ilike(f"%{lang}%"))
        if availability:
            query = query.filter(VirtualAssistantApplication.availability == availability)
        if min_price is not None:
            query = query.filter(VirtualAssistantApplication.public_monthly_price_inr >= min_price)
        if max_price is not None:
            query = query.filter(VirtualAssistantApplication.public_monthly_price_inr <= max_price)
        if experience:
            query = query.filter(VirtualAssistantApplication.years_experience == experience)

        sort_column = VirtualAssistantApplication.published_at
        if sort_by == "price_asc":
            sort_column = VirtualAssistantApplication.public_monthly_price_inr
        elif sort_by == "price_desc":
            sort_column = VirtualAssistantApplication.public_monthly_price_inr.desc()
        elif sort_by == "experience":
            sort_column = VirtualAssistantApplication.years_experience

        if featured_only:
            query = query.order_by(
                VirtualAssistantApplication.featured.desc(),
                VirtualAssistantApplication.published_at.desc(),
            )
        else:
            query = query.order_by(sort_column.desc() if sort_by in {"recently_published"} else sort_column)

        total = query.count()
        rows = query.offset((page - 1) * page_size).limit(page_size).all()
        for row in rows:
            VirtualAssistantAdminService._ensure_roles(db, row)

        return {
            "items": [VirtualAssistantAdminService._serialize_public(db, row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size else 1,
        }

    @staticmethod
    def _owner_user_uuid(row: VirtualAssistantApplication):
        if not row.user_id:
            return None
        try:
            return uuid.UUID(str(row.user_id))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def get_public_profile_and_record_view(
        db: Session,
        application_id,
        *,
        viewer=None,
        client_ip: str | None = None,
        viewer_industry: str | None = None,
        viewer_role: str | None = None,
    ) -> dict | None:
        from app.service.marketplace.listing_view_counter import record_virtual_assistant_view

        row = (
            db.query(VirtualAssistantApplication)
            .filter(VirtualAssistantApplication.id == application_id)
            .first()
        )
        if not row or not VirtualAssistantAdminService.is_publicly_listable(db, row):
            return None
        VirtualAssistantAdminService._ensure_roles(db, row)

        try:
            app_uuid = uuid.UUID(str(application_id))
            record_virtual_assistant_view(
                db,
                application_id=app_uuid,
                owner_user_id=VirtualAssistantAdminService._owner_user_uuid(row),
                viewer=viewer,
                client_ip=client_ip,
                viewer_industry=viewer_industry,
                viewer_role=viewer_role,
                increment_views=lambda: None,
            )
            db.refresh(row)
        except Exception:
            logger.exception(
                "Virtual Assistant view tracking failed application_id=%s",
                application_id,
            )

        return VirtualAssistantAdminService._serialize_public(db, row)

    @staticmethod
    def _serialize_detail(db: Session, row: VirtualAssistantApplication) -> dict:
        data = VirtualAssistantAdminService._serialize(row)
        data["profilePhotoKey"] = row.profile_photo_key
        data["profilePhotoFilename"] = row.profile_photo_filename
        data["profilePhotoMimeType"] = row.profile_photo_mime_type
        data["profilePhotoSize"] = row.profile_photo_size
        data["resumeKey"] = row.resume_key
        data["resumeFilename"] = row.resume_filename
        data["resumeMimeType"] = row.resume_mime_type
        data["resumeSize"] = row.resume_size
        data["reviewedAt"] = row.reviewed_at.isoformat() if row.reviewed_at else None
        data["applicationRoles"] = VirtualAssistantAdminService.list_application_roles(
            db, row.id
        )
        data["publishStatus"] = row.publish_status
        data["publishedAt"] = row.published_at.isoformat() if row.published_at else None
        data["publishedById"] = row.published_by_id
        data["publishedByName"] = row.published_by_name
        return data

    @staticmethod
    def update_pricing(
        db: Session,
        application_id,
        public_monthly_price_inr: int | None,
        pricing_currency: str | None,
        updated_by_user_id: str | None,
        updated_by_user_name: str | None,
        max_client_capacity: int | None = None,
    ) -> dict | None:
        row = db.query(VirtualAssistantApplication).filter(
            VirtualAssistantApplication.id == application_id
        ).first()
        if not row or row.is_deleted:
            return None
        row.public_monthly_price_inr = public_monthly_price_inr
        row.pricing_currency = (pricing_currency or "INR").upper()[:3]
        if max_client_capacity is not None:
            row.max_client_capacity = max_client_capacity
        row.pricing_updated_by_id = updated_by_user_id
        row.pricing_updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
        VirtualAssistantAdminService._log_pricing_audit(
            db, updated_by_user_id, updated_by_user_name, row
        )
        try:
            VirtualAssistantAdminService._create_va_notification(
                db, application_id, "pricing_updated",
                f"Your customer monthly price has been updated to {row.pricing_currency or 'INR'} {row.public_monthly_price_inr or 0}.",
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "virtual_assistant.pricing.notification.failed id=%s", application_id
            )
        return VirtualAssistantAdminService._serialize_detail(db, row)

    @staticmethod
    def _log_pricing_audit(db, admin_id, admin_name, row):
        try:
            from app.entity.platform.admin_audit_log import AdminAuditLog
            from app.repository.admin_audit_log_repository import AdminAuditLogRepository
            repo = AdminAuditLogRepository(db)
            try:
                admin_uuid = uuid.UUID(admin_id) if isinstance(admin_id, str) else admin_id
            except Exception:
                admin_uuid = None
            log = AdminAuditLog(
                admin_id=admin_uuid,
                action="UPDATE_VA_PRICING",
                entity_id=str(row.id),
                entity_type="VIRTUAL_ASSISTANT",
                reason=f"public_monthly_price_inr={row.public_monthly_price_inr} currency={row.pricing_currency[:3] if row.pricing_currency else ''}",
                details=f"Updated pricing for VA {row.full_name} ({row.email})",
            )
            db.add(log)
            db.commit()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("va.pricing.audit.failed")

    @staticmethod
    def create_application(
        db: Session,
        full_name: str,
        email: str,
        phone_number: str | None,
        location: str,
        profile_photo,
        bio: str,
        roles: list[str],
        skills: str,
        years_experience: str,
        languages: str,
        linkedin_url: str | None,
        portfolio_url: str | None,
        resume_url: str | None,
        availability: str | None,
        hours_per_week: str | None,
        expected_compensation: str | None,
        max_client_capacity: int | None,
        current_assigned_clients: int | None = 0,
        publish_immediately: bool = False,
        public_monthly_price_inr: int | None = None,
        pricing_currency: str | None = "INR",
        admin_user_id: str | None = None,
        admin_user_name: str | None = None,
    ) -> dict:
        logger.info("virtual_assistant.admin.create.start email=%s roles=%s", email.strip().lower(), roles)
        email_normalized = (email or "").strip().lower()
        if not (full_name or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Full name is required.")
        if not email_normalized:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is required.")
        if not (location or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Location is required.")
        if not (bio or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Short bio is required.")
        if len(roles) != 1 or not (roles[0] or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Exactly one Virtual Assistant role is required per application.",
            )
        role_name = normalize_va_role_name(roles[0])
        if not (skills or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Skills are required.")
        if not (years_experience or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Years of experience is required.")
        if not (languages or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Languages known is required.")
        if not (availability or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Availability must be selected.")
        if max_client_capacity is None or int(max_client_capacity) < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum Client Capacity must be configured.",
            )
        if public_monthly_price_inr is None or int(public_monthly_price_inr) < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Customer Monthly Price must be set.",
            )
        if not (expected_compensation or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Expected compensation is required.")

        assigned_clients = max(0, int(current_assigned_clients or 0))
        if assigned_clients > int(max_client_capacity):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current assigned clients cannot exceed maximum client capacity.",
            )

        resume_url = validate_resume_link(resume_url)
        linkedin_url = validate_linkedin_profile_url(linkedin_url)

        if not profile_photo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Profile photo is required.",
            )
        _validate_profile_photo(profile_photo)

        existing_application = (
            db.query(VirtualAssistantApplication)
            .filter(VirtualAssistantApplication.email == email_normalized)
            .filter(VirtualAssistantApplication.roles == role_name)
            .filter(VirtualAssistantApplication.is_deleted.is_(False))
            .filter(VirtualAssistantApplication.overall_status.in_(("pending", "approved")))
            .first()
        )
        if existing_application:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A {existing_application.overall_status} application already exists for {role_name}.",
            )

        profile_photo_url = None
        profile_photo_key = None
        profile_photo_filename = None
        profile_photo_mime_type = None
        profile_photo_size = None

        profile_photo_key = upload_va_profile_photo_to_s3(profile_photo)
        profile_photo_filename = profile_photo.filename
        profile_photo_mime_type = profile_photo.content_type
        profile_photo_size = profile_photo.size

        if not profile_photo_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Profile photo is required and could not be stored.",
            )

        publish_now = bool(publish_immediately)
        overall_status = "approved" if publish_now else "pending"
        role_status = "approved" if publish_now else "pending"
        now = datetime.now(timezone.utc)
        currency = (pricing_currency or "INR").upper()[:3]
        portfolio = (portfolio_url or "").strip() or None

        created_rows: list = []
        try:
            for role_name in roles:
                application_number, reference_number = allocate_application_numbers(db)
                row = VirtualAssistantApplication(
                    application_number=application_number,
                    full_name=full_name.strip(),
                    email=email_normalized,
                    phone_number=(phone_number or "").strip(),
                    location=(location or "").strip() or None,
                    profile_photo_url=profile_photo_url,
                    profile_photo_key=profile_photo_key,
                    profile_photo_filename=profile_photo_filename,
                    profile_photo_mime_type=profile_photo_mime_type,
                    profile_photo_size=profile_photo_size,
                    short_bio=(bio or "").strip() or None,
                    roles=role_name,
                    skills=(skills or "").strip() or None,
                    years_experience=(years_experience or "").strip() or None,
                    languages_known=(languages or "").strip() or None,
                    linkedin_url=linkedin_url,
                    portfolio_url=portfolio,
                    resume_url=resume_url,
                    resume_key=None,
                    resume_filename=None,
                    resume_mime_type=None,
                    resume_size=None,
                    availability=(availability or "").strip() or None,
                    hours_per_week=(hours_per_week or "").strip() or None,
                    expected_compensation=(expected_compensation or "").strip() or None,
                    max_client_capacity=int(max_client_capacity),
                    public_monthly_price_inr=int(public_monthly_price_inr),
                    pricing_currency=currency,
                    consent_accurate=True,
                    consent_terms=True,
                    consent_adult=True,
                    status="approved" if publish_now else "pending",
                    overall_status=overall_status,
                    reference_number=reference_number,
                    publish_status="published" if publish_now else "draft",
                    published_at=now if publish_now else None,
                    published_by_id=admin_user_id if publish_now else None,
                    published_by_name=admin_user_name if publish_now else None,
                )
                db.add(row)
                db.flush()
                db.add(
                    ApplicationRole(
                        application_id=row.id,
                        role_name=role_name,
                        status=role_status,
                        max_clients=int(max_client_capacity),
                        current_clients=assigned_clients,
                    )
                )
                db.flush()

                if publish_now:
                    publish_errors = VirtualAssistantAdminService._validate_publish_requirements(db, row)
                    if publish_errors:
                        db.rollback()
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="; ".join(publish_errors),
                        )

                created_rows.append(row)

            db.commit()
        except HTTPException:
            db.rollback()
            raise
        except IntegrityError as exc:
            db.rollback()
            logger.exception(
                "virtual_assistant.admin.create.integrity_error email=%s",
                email_normalized,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Unable to save Virtual Assistant profile. Please verify the details and try again.",
            ) from exc

        primary_row = created_rows[0]
        for row in created_rows:
            db.refresh(row)
            VirtualAssistantAdminService._recompute_overall_status(db, row.id)
            was_locked = row.workspace_locked
            VirtualAssistantAdminService._recompute_workspace_lock(db, row.id)
            db.commit()
            db.refresh(row)

            try:
                VirtualAssistantAdminService._create_va_notification(
                    db, row.id, "application_submitted",
                    message=f"Your application ({row.reference_number}) for {row.roles} has been submitted successfully.",
                    title="Application Submitted",
                )
                if was_locked and not row.workspace_locked:
                    VirtualAssistantAdminService._create_va_notification(
                        db, row.id, "workspace_unlocked",
                        "Your Virtual Assistant Workspace has been unlocked.",
                    )
                if publish_now:
                    VirtualAssistantAdminService._create_va_notification(
                        db, row.id, "profile_published",
                        "Your Virtual Assistant profile has been published.",
                    )
            except Exception:
                logger.exception("virtual_assistant.admin.create.notification.failed id=%s", row.id)

        logger.info(
            "virtual_assistant.admin.create.success email=%s application_id=%s roles=%s publish=%s",
            email_normalized,
            primary_row.id,
            roles,
            publish_now,
        )
        return VirtualAssistantAdminService._serialize_detail(db, primary_row)

    @staticmethod
    def publish_application(
        db: Session,
        application_id,
        admin_user_id: str | None,
        admin_user_name: str | None,
    ) -> dict | None:
        row = db.query(VirtualAssistantApplication).filter(
            VirtualAssistantApplication.id == application_id
        ).first()
        if not row or row.is_deleted:
            return None
        errors = VirtualAssistantAdminService._validate_publish_requirements(db, row)
        if errors:
            raise ValueError("; ".join(errors))
        row.publish_status = "published"
        row.published_at = datetime.now(timezone.utc)
        row.published_by_id = admin_user_id
        row.published_by_name = admin_user_name
        db.commit()
        db.refresh(row)
        try:
            VirtualAssistantAdminService._create_va_notification(
                db, application_id, "profile_published",
                "Your Virtual Assistant profile has been published.",
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "virtual_assistant.publish.notification.failed id=%s", application_id
            )
        return VirtualAssistantAdminService._serialize_detail(db, row)

    @staticmethod
    def unpublish_application(
        db: Session,
        application_id,
        admin_user_id: str | None,
        admin_user_name: str | None,
    ) -> dict | None:
        row = db.query(VirtualAssistantApplication).filter(
            VirtualAssistantApplication.id == application_id
        ).first()
        if not row or row.is_deleted:
            return None
        row.publish_status = "unpublished"
        row.published_at = None
        row.published_by_id = None
        row.published_by_name = None
        db.commit()
        db.refresh(row)
        try:
            VirtualAssistantAdminService._create_va_notification(
                db, application_id, "profile_unpublished",
                "Your Virtual Assistant profile has been unpublished.",
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "virtual_assistant.unpublish.notification.failed id=%s", application_id
            )
        return VirtualAssistantAdminService._serialize_detail(db, row)

    @staticmethod
    def _validate_publish_requirements(db: Session, row: VirtualAssistantApplication) -> list[str]:
        errors = []
        roles = VirtualAssistantAdminService.list_application_roles(db, row.id)
        has_approved_role = any(r["status"] == "approved" for r in roles)
        if not has_approved_role:
            errors.append("At least one Virtual Assistant role must be approved.")
        if not row.full_name or not row.email:
            errors.append("Personal information is incomplete.")
        if not row.short_bio:
            errors.append("Short bio is required.")
        if not row.skills:
            errors.append("Skills are required.")
        if not row.years_experience:
            errors.append("Years of experience is required.")
        if not row.languages_known:
            errors.append("Languages known is required.")
        if not row.availability:
            errors.append("Availability must be selected.")
        if not resolve_va_profile_photo_url(row.profile_photo_url, row.profile_photo_key):
            errors.append("A stored profile photo is required before publishing.")
        if row.public_monthly_price_inr is None or row.public_monthly_price_inr < 0:
            errors.append("Customer Monthly Price must be set.")
        if row.max_client_capacity is None or row.max_client_capacity < 1:
            errors.append("Maximum Client Capacity must be configured.")
        return errors

    @staticmethod
    def update_role_capacity(
        db: Session,
        role_id,
        max_clients: int | None,
        current_clients: int | None = None,
        is_active: bool | None = None,
        updated_by_user_id: str | None = None,
        updated_by_user_name: str | None = None,
    ) -> dict | None:
        role = db.query(ApplicationRole).filter(ApplicationRole.id == role_id).first()
        if not role:
            return None
        if max_clients is not None:
            if max_clients < 0:
                raise ValueError("max_clients must be non-negative")
            role.max_clients = max_clients
        if current_clients is not None:
            if current_clients < 0:
                raise ValueError("current_clients must be non-negative")
            if role.max_clients is not None and current_clients > role.max_clients:
                raise ValueError("current_clients cannot exceed max_clients")
            role.current_clients = current_clients
        if is_active is not None:
            role.is_active = is_active
        db.commit()
        db.refresh(role)
        VirtualAssistantAdminService._log_capacity_audit(
            db, updated_by_user_id, updated_by_user_name, role
        )
        return VirtualAssistantAdminService._serialize_role(role)

    @staticmethod
    def _log_capacity_audit(db, admin_id, admin_name, role):
        try:
            from app.entity.platform.admin_audit_log import AdminAuditLog
            repo = AdminAuditLogRepository(db)
            admin_uuid = uuid.UUID(admin_id) if isinstance(admin_id, str) else admin_id
            log = AdminAuditLog(
                admin_id=admin_uuid,
                action="UPDATE_VA_ROLE_CAPACITY",
                entity_id=str(role.id),
                entity_type="VA_APPLICATION_ROLE",
                reason=f"max_clients={role.max_clients} current_clients={role.current_clients} is_active={role.is_active}",
                details=f"Updated capacity for role {role.role_name} on application {role.application_id}",
            )
            db.add(log)
            db.commit()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("va.capacity.audit.failed")

    @staticmethod
    def _serialize_role(role: ApplicationRole) -> dict:
        return {
            "id": str(role.id),
            "applicationId": str(role.application_id),
            "roleName": role.role_name,
            "status": role.status,
            "reviewedAt": role.reviewed_at.isoformat() if role.reviewed_at else None,
            "reviewedBy": role.reviewed_by_id,
            "rejectionNote": role.rejection_note,
            "maxClients": role.max_clients,
            "currentClients": role.current_clients,
            "isActive": role.is_active,
            "availabilityStatus": VirtualAssistantAdminService._role_availability_status(role),
        }

    @staticmethod
    def _role_availability_status(role: ApplicationRole) -> str:
        if not role.is_active:
            return "temporarily_unavailable"
        if role.max_clients is None or role.current_clients is None:
            return "available"
        if role.current_clients >= role.max_clients:
            return "not_available"
        if role.current_clients > 0:
            return "limited"
        return "available"

    @staticmethod
    def list_application_roles(db: Session, application_id) -> list[dict]:
        roles = (
            db.query(ApplicationRole)
            .filter(ApplicationRole.application_id == application_id)
            .order_by(ApplicationRole.role_name)
            .all()
        )
        return [VirtualAssistantAdminService._serialize_role(r) for r in roles]

    @staticmethod
    def get_applicant_applications(db: Session, email: str) -> list[VirtualAssistantApplication]:
        """All non-deleted VA applications for an applicant email (newest first)."""
        email_normalized = (email or "").strip().lower()
        if not email_normalized:
            return []
        return (
            db.query(VirtualAssistantApplication)
            .filter(
                VirtualAssistantApplication.email == email_normalized,
                VirtualAssistantApplication.is_deleted.is_(False),
            )
            .order_by(VirtualAssistantApplication.created_at.desc())
            .all()
        )

    @staticmethod
    def applicant_workspace_unlocked(db: Session, email: str) -> bool:
        summaries = VirtualAssistantAdminService.list_applicant_role_summaries(db, email)
        return any(s.get("status") == "approved" for s in summaries)

    @staticmethod
    def get_primary_workspace_application(
        db: Session, email: str
    ) -> VirtualAssistantApplication | None:
        apps = VirtualAssistantAdminService.get_applicant_applications(db, email)
        if not apps:
            return None
        for app in apps:
            VirtualAssistantAdminService._ensure_roles(db, app)
            roles = (
                db.query(ApplicationRole)
                .filter(ApplicationRole.application_id == app.id)
                .all()
            )
            if any(r.status == "approved" for r in roles):
                return app
        return apps[0]

    @staticmethod
    def list_applicant_role_summaries(db: Session, email: str) -> list[dict]:
        """Read-only rows for the applicant journey: one entry per role application."""
        email_normalized = (email or "").strip().lower()
        if not email_normalized:
            return []

        apps = (
            db.query(VirtualAssistantApplication)
            .filter(
                VirtualAssistantApplication.email == email_normalized,
                VirtualAssistantApplication.is_deleted.is_(False),
            )
            .order_by(
                VirtualAssistantApplication.application_number.asc(),
                VirtualAssistantApplication.created_at.asc(),
            )
            .all()
        )

        summaries: list[dict] = []
        for app in apps:
            VirtualAssistantAdminService._ensure_roles(db, app)
            app_roles = VirtualAssistantAdminService.list_application_roles(db, app.id)
            pricing_currency = app.pricing_currency or "INR"
            if not app_roles:
                summaries.append(
                    {
                        "id": str(app.id),
                        "referenceNumber": app.reference_number,
                        "roleName": app.roles or "—",
                        "status": "pending",
                        "expectedCompensation": app.expected_compensation,
                        "publicMonthlyPriceInr": app.public_monthly_price_inr,
                        "pricingCurrency": pricing_currency,
                    }
                )
                continue

            for role in app_roles:
                summaries.append(
                    {
                        "id": role["id"],
                        "referenceNumber": app.reference_number,
                        "roleName": role["roleName"],
                        "status": role["status"],
                        "expectedCompensation": app.expected_compensation,
                        "publicMonthlyPriceInr": app.public_monthly_price_inr,
                        "pricingCurrency": pricing_currency,
                    }
                )
        return summaries

    @staticmethod
    def create_assignment(
        db: Session,
        application_id,
        assigned_company: str | None,
        assigned_role: str | None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        notes: str | None = None,
        created_by_user_id: str | None = None,
        created_by_user_name: str | None = None,
    ) -> dict | None:
        company = (assigned_company or "").strip()
        role = (assigned_role or "").strip()
        if not company:
            raise ValueError("assignedCompany is required")
        if not role:
            raise ValueError("assignedRole is required")

        row = db.query(VirtualAssistantApplication).filter(
            VirtualAssistantApplication.id == application_id,
            VirtualAssistantApplication.is_deleted.is_(False),
        ).first()
        if not row:
            return None

        assignment = VAAssignment(
            application_id=row.id,
            assigned_company=company,
            assigned_role=role,
            status="active",
            start_date=start_date,
            end_date=end_date,
            notes=(notes or None),
            is_active=True,
            is_deleted=False,
        )
        try:
            db.add(assignment)
            db.commit()
            db.refresh(assignment)
        except SQLAlchemyError:
            db.rollback()
            logger.exception("va.assignment.create.db_failed application_id=%s", application_id)
            raise

        VirtualAssistantAdminService._log_assignment_audit(
            db, created_by_user_id, created_by_user_name, assignment, "ASSIGNMENT_CREATED"
        )
        VirtualAssistantAdminService._send_assignment_emails(db, assignment, "created")
        VirtualAssistantAdminService._create_va_notification(
            db,
            application_id,
            "new_assignment",
            f"New assignment: {assignment.assigned_company or 'A client'} / {assignment.assigned_role or 'Role'}.",
            related_assignment_id=assignment.id,
        )
        return VirtualAssistantAdminService._serialize_assignment(assignment)

    @staticmethod
    def update_assignment(
        db: Session,
        assignment_id,
        assigned_company: str | None = None,
        assigned_role: str | None = None,
        status: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        notes: str | None = None,
        updated_by_user_id: str | None = None,
        updated_by_user_name: str | None = None,
    ) -> dict | None:
        assignment = db.query(VAAssignment).filter(VAAssignment.id == assignment_id).first()
        if not assignment:
            return None
        old_status = assignment.status
        if assigned_company is not None:
            assignment.assigned_company = assigned_company
        if assigned_role is not None:
            assignment.assigned_role = assigned_role
        if status is not None:
            assignment.status = status
        if start_date is not None:
            assignment.start_date = start_date
        if end_date is not None:
            assignment.end_date = end_date
        if notes is not None:
            assignment.notes = notes
        db.commit()
        db.refresh(assignment)
        action = "ASSIGNMENT_UPDATED"
        if status and status == "cancelled" and old_status != "cancelled":
            action = "ASSIGNMENT_CANCELLED"
        VirtualAssistantAdminService._log_assignment_audit(db, updated_by_user_id, updated_by_user_name, assignment, action)
        if action == "ASSIGNMENT_CANCELLED":
            VirtualAssistantAdminService._send_assignment_emails(db, assignment, "cancelled")
        notif_type = "assignment_updated"
        if status == "completed" and old_status != "completed":
            notif_type = "assignment_completed"
        VirtualAssistantAdminService._create_va_notification(
            db, str(assignment.application_id), notif_type,
            f"Assignment updated: {assignment.assigned_company or 'A client'} / {assignment.assigned_role or 'Role'} — {status or assignment.status}.",
            related_assignment_id=str(assignment.id),
        )
        return VirtualAssistantAdminService._serialize_assignment(assignment)

    @staticmethod
    def delete_application(
        db: Session,
        application_id,
        deleted_by_user_id: str | None = None,
        deleted_by_user_name: str | None = None,
    ) -> bool:
        app = db.query(VirtualAssistantApplication).filter(
            VirtualAssistantApplication.id == application_id,
            VirtualAssistantApplication.is_deleted.is_(False),
        ).first()
        if not app:
            return False

        db.query(VANotification).filter(
            VANotification.related_application_id == application_id,
        ).delete(synchronize_session=False)

        db.delete(app)
        db.commit()
        return True

    @staticmethod
    def delete_assignment(
        db: Session,
        assignment_id,
        deleted_by_user_id: str | None = None,
        deleted_by_user_name: str | None = None,
    ) -> bool:
        assignment = db.query(VAAssignment).filter(VAAssignment.id == assignment_id).first()
        if not assignment:
            return False
        VirtualAssistantAdminService._log_assignment_audit(db, deleted_by_user_id, deleted_by_user_name, assignment, "ASSIGNMENT_DELETED")
        db.delete(assignment)
        db.commit()
        return True

    @staticmethod
    def list_assignments(db: Session, application_id) -> list[dict]:
        items = (
            db.query(VAAssignment)
            .filter(
                VAAssignment.application_id == application_id,
                VAAssignment.is_deleted.is_(False),
            )
            .order_by(VAAssignment.created_at.desc())
            .all()
        )
        return [VirtualAssistantAdminService._serialize_assignment(a) for a in items]

    @staticmethod
    def _serialize_assignment(assignment: VAAssignment) -> dict:
        return {
            "id": str(assignment.id),
            "applicationId": str(assignment.application_id),
            "assignedCompany": assignment.assigned_company,
            "assignedRole": assignment.assigned_role,
            "status": assignment.status,
            "startDate": assignment.start_date.isoformat() if assignment.start_date else None,
            "endDate": assignment.end_date.isoformat() if assignment.end_date else None,
            "notes": assignment.notes,
            "createdAt": assignment.created_at.isoformat() if assignment.created_at else None,
            "updatedAt": assignment.updated_at.isoformat() if assignment.updated_at else None,
        }

    @staticmethod
    def _log_assignment_audit(db, admin_id, admin_name, assignment, action):
        if not admin_id:
            return
        try:
            from app.entity.platform.admin_audit_log import AdminAuditLog
            repo = AdminAuditLogRepository(db)
            admin_uuid = uuid.UUID(admin_id) if isinstance(admin_id, str) else admin_id
            log = AdminAuditLog(
                admin_id=admin_uuid,
                action=action,
                entity_id=str(assignment.id),
                entity_type="VA_ASSIGNMENT",
                reason=f"application_id={assignment.application_id} status={assignment.status}",
                details=f"Assignment {assignment.assigned_company} / {assignment.assigned_role}",
            )
            db.add(log)
            db.commit()
        except Exception:
            logger.exception("va.assignment.audit.failed")

    @staticmethod
    def _send_assignment_emails(db, assignment: VAAssignment, event: str) -> None:
        try:
            from app.entity.virtual_assistant.virtual_assistant_entity import VirtualAssistantApplication
            row = db.query(VirtualAssistantApplication).filter(VirtualAssistantApplication.id == assignment.application_id).first()
            if not row or not row.email:
                return
            from app.service.auth.mail_service import MailService
            if event == "created":
                coro = MailService.send_virtual_assistant_new_assignment_email(
                    to_email=row.email,
                    full_name=row.full_name,
                    reference_number=row.reference_number,
                    assigned_company=assignment.assigned_company,
                    assigned_role=assignment.assigned_role,
                    start_date=assignment.start_date.isoformat() if assignment.start_date else None,
                    end_date=assignment.end_date.isoformat() if assignment.end_date else None,
                    notes=assignment.notes,
                )
            elif event == "cancelled":
                coro = MailService.send_virtual_assistant_assignment_cancelled_email(
                    to_email=row.email,
                    full_name=row.full_name,
                    reference_number=row.reference_number,
                    assigned_company=assignment.assigned_company,
                    assigned_role=assignment.assigned_role,
                    reason=assignment.notes,
                )
            else:
                return
            VirtualAssistantAdminService._run_async(coro)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("va.assignment.email.failed")




