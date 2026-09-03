import logging
import mimetypes
from datetime import datetime, timezone

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.entity.virtual_assistant.application_role_entity import ApplicationRole
from app.service.virtual_assistant.reference_number_service import allocate_application_numbers
from app.entity.virtual_assistant.virtual_assistant_entity import (
    VirtualAssistantApplication,
)
from app.integrations.s3.supabase_storage import key_from_storage_url
from app.integrations.s3.upload_service import generate_file_url
from app.service.auth.mail_service import MailService
from app.service.virtual_assistant.va_media import (
    upload_va_profile_photo_to_s3,
    validate_linkedin_profile_url,
    validate_resume_link,
)
from app.utils.run_async import run_async_from_sync
from app.utils.virtual_assistant_roles import normalize_va_role_name
from app.entity.virtual_assistant.workspace_entity import VANotification

logger = logging.getLogger(__name__)


def _integrity_error_message(exc: IntegrityError) -> str:
    orig = str(getattr(exc, "orig", exc)).strip()
    lowered = orig.lower()
    if "phone_number" in lowered and "not-null" in lowered:
        return "Phone number is required."
    if "reference_number" in lowered or "application_number" in lowered:
        return "Unable to allocate a unique application reference. Please try again."
    if orig:
        return orig
    return "Unable to save application. Please check your details and try again."


def _is_reference_collision(exc: IntegrityError) -> bool:
    orig = str(getattr(exc, "orig", exc)).lower()
    if "uq_virtual_assistant_applications_email" in orig:
        return False
    if "email" in orig and "unique" in orig and "virtual_assistant_applications" in orig:
        return False
    return (
        "reference_number" in orig
        or "application_number" in orig
        or "duplicate key" in orig
        or "unique constraint" in orig
    )


PROFILE_PHOTO_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
PROFILE_PHOTO_ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}


def _validate_profile_photo(file: UploadFile) -> None:
    filename = (file.filename or "").lower()
    extension = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
    content_type = (file.content_type or "").lower()
    guessed, _ = mimetypes.guess_type(filename)
    allowed = (
        extension in PROFILE_PHOTO_ALLOWED_EXTENSIONS
        or content_type in PROFILE_PHOTO_ALLOWED_MIME_TYPES
        or (guessed and guessed in PROFILE_PHOTO_ALLOWED_MIME_TYPES)
    )
    if not allowed:
        raise HTTPException(
            status_code=400,
            detail="Unsupported profile photo type. Allowed formats: JPG, PNG, WEBP.",
        )
    if file.size and file.size > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="Profile photo must be under 5MB.",
        )


class VirtualAssistantService:
    @staticmethod
    def submit_application(
        db: Session,
        full_name: str,
        email: str,
        phone_number: str,
        location: str,
        profile_photo: UploadFile | None,
        resume_url: str | None,
        bio: str,
        roles: list[str],
        skills: str,
        years_of_experience: str,
        languages: str,
        linkedin_url: str,
        portfolio_url: str,
        availability: str,
        hours_per_week: str,
        expected_compensation: str,
        info_accurate: bool,
        agree_terms: bool,
        is_adult: bool,
        user_id: str | None = None,
    ) -> dict:
        email_normalized = email.strip().lower()
        logger.info("virtual_assistant.application.submit.start email=%s roles=%s", email_normalized, roles)

        if len(roles) != 1 or not roles[0].strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Exactly one Virtual Assistant role is required per application.",
            )

        role_name = normalize_va_role_name(roles[0])
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
                detail=f"You already have a {existing_application.overall_status} application for {role_name}.",
            )

        profile_photo_url = None
        profile_photo_key = None
        profile_photo_filename = None
        profile_photo_mime_type = None
        profile_photo_size = None

        if profile_photo:
            logger.info(
                "virtual_assistant.application.upload.start type=profile_photo filename=%s email=%s",
                profile_photo.filename,
                email_normalized,
            )
            _validate_profile_photo(profile_photo)
            profile_photo_key = upload_va_profile_photo_to_s3(profile_photo)
            logger.info(
                "virtual_assistant.application.upload.success type=profile_photo key=%s email=%s",
                profile_photo_key,
                email_normalized,
            )
            profile_photo_filename = profile_photo.filename
            profile_photo_mime_type = profile_photo.content_type
            profile_photo_size = profile_photo.size

        if not profile_photo_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Profile photo is required and could not be stored.",
            )

        resume_url = validate_resume_link(resume_url)
        linkedin_url = validate_linkedin_profile_url(linkedin_url)

        logger.info(
            "virtual_assistant.application.create_start email=%s roles=%s",
            email_normalized,
            roles,
        )

        # Deduplicate roles within this submission only — same applicant may already
        # have prior applications for any of these roles; each submission still creates
        # independent application records.
        unique_roles: list[str] = []
        seen_in_batch: set[str] = set()
        for role_name in roles:
            if role_name and role_name not in seen_in_batch:
                unique_roles.append(role_name)
                seen_in_batch.add(role_name)

        if not unique_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one Virtual Assistant role is required.",
            )

        # One brand-new application record per selected role. Never merge onto an existing app.
        created_rows: list[VirtualAssistantApplication] = []
        skipped_roles: list[str] = []

        def _build_application(role_name: str, role_reference: str, role_application_number: int) -> VirtualAssistantApplication:
            return VirtualAssistantApplication(
                application_number=role_application_number,
                user_id=user_id,
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
                years_experience=(years_of_experience or "").strip() or None,
                languages_known=(languages or "").strip() or None,
                linkedin_url=linkedin_url,
                portfolio_url=(portfolio_url or "").strip() or None,
                resume_url=resume_url,
                resume_key=None,
                resume_filename=None,
                resume_mime_type=None,
                resume_size=None,
                availability=(availability or "").strip() or None,
                hours_per_week=(hours_per_week or "").strip() or None,
                expected_compensation=(expected_compensation or "").strip() or None,
                consent_accurate=bool(info_accurate),
                consent_terms=bool(agree_terms),
                consent_adult=bool(is_adult),
                status="pending",
                reference_number=role_reference,
            )

        for role_name in unique_roles:
            inserted = False
            last_integrity_error: IntegrityError | None = None

            for insert_attempt in range(5):
                application_number, role_reference = allocate_application_numbers(db)
                row = _build_application(role_name, role_reference, application_number)
                try:
                    db.add(row)
                    db.flush()
                    db.add(ApplicationRole(application_id=row.id, role_name=role_name, status="pending"))
                    db.commit()
                    db.refresh(row)
                    created_rows.append(row)
                    inserted = True
                    logger.info(
                        "virtual_assistant.application.db_insert.committed ref=%s id=%s role=%s attempt=%s",
                        role_reference,
                        row.id,
                        role_name,
                        insert_attempt + 1,
                    )
                    break
                except IntegrityError as exc:
                    last_integrity_error = exc
                    db.rollback()
                    if not _is_reference_collision(exc):
                        logger.exception(
                            "virtual_assistant.application.db_insert.failed ref=%s role=%s",
                            role_reference,
                            role_name,
                        )
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=_integrity_error_message(exc),
                        ) from exc
                    logger.warning(
                        "virtual_assistant.application.db_insert.conflict ref=%s role=%s attempt=%s error=%s",
                        role_reference,
                        role_name,
                        insert_attempt + 1,
                        exc,
                    )
                    continue

            if not inserted:
                logger.error(
                    "virtual_assistant.application.db_insert.exhausted_retries role=%s last_error=%s",
                    role_name,
                    last_integrity_error,
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=_integrity_error_message(last_integrity_error),
                ) from last_integrity_error

        if not created_rows:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create Virtual Assistant application. Please try again.",
            )

        primary_row = created_rows[0]
        created_roles = [r.roles for r in created_rows]
        logger.info(
            "virtual_assistant.application.submitted ids=%s email=%s refs=%s new_roles=%s",
            [r.id for r in created_rows],
            primary_row.email,
            [r.reference_number for r in created_rows],
            created_roles,
        )

        if primary_row.user_id:
            try:
                for created in created_rows:
                    db.add(
                        VANotification(
                            va_id=created.user_id,
                            related_application_id=created.id,
                            notification_type="application_submitted",
                            title="Application Submitted",
                            message=f"Your application ({created.reference_number}) for {created.roles} has been submitted successfully.",
                        )
                    )
                db.commit()
            except Exception:
                logger.exception(
                    "virtual_assistant.application.notification.commit_failed ref=%s",
                    primary_row.reference_number,
                )
                db.rollback()
        else:
            logger.info(
                "virtual_assistant.application.notification.skipped ref=%s no user_id",
                primary_row.reference_number,
            )

        if not settings.mail_configured():
            logger.warning("mail.skip virtual_assistant id=%s mail not configured", primary_row.id)
            return {
                "reference_number": primary_row.reference_number,
                "email": primary_row.email,
                "new_roles": created_roles,
                "skipped_roles": skipped_roles,
                "reference_numbers": [r.reference_number for r in created_rows],
            }

        submitted_at = (
            primary_row.created_at.astimezone(timezone.utc).strftime("%d %b %Y, %I:%M %p")
            if primary_row.created_at
            else datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p")
        )

        # One confirmation email for the batch (primary reference).
        try:
            logger.info(
                "virtual_assistant.application.confirmation_email.start id=%s ref=%s",
                primary_row.id,
                primary_row.reference_number,
            )
            VirtualAssistantService._run_async(
                MailService.send_virtual_assistant_application_confirmation_email(
                    to_email=primary_row.email,
                    full_name=primary_row.full_name,
                    reference_number=primary_row.reference_number,
                    submitted_at=submitted_at,
                )
            )
            logger.info(
                "virtual_assistant.application.confirmation_email.sent id=%s ref=%s",
                primary_row.id,
                primary_row.reference_number,
            )
        except Exception:
            logger.exception(
                "virtual_assistant.application.confirmation_email.failed id=%s ref=%s",
                primary_row.id,
                primary_row.reference_number,
            )

        recipient = settings.resolved_mail_support_inbox()
        if not recipient:
            logger.warning("mail.skip virtual_assistant id=%s no recipient", primary_row.id)
            return {
                "reference_number": primary_row.reference_number,
                "email": primary_row.email,
                "new_roles": created_roles,
                "skipped_roles": skipped_roles,
                "reference_numbers": [r.reference_number for r in created_rows],
            }

        # Notify admin once per created application so each role is visible independently.
        for created in created_rows:
            try:
                logger.info(
                    "virtual_assistant.application.admin_email.start id=%s ref=%s",
                    created.id,
                    created.reference_number,
                )
                VirtualAssistantService._run_async(
                    MailService.send_virtual_assistant_application_email(
                        to_email=recipient,
                        full_name=created.full_name,
                        email=created.email,
                        phone_number=created.phone_number,
                        location=created.location,
                        profile_photo_url=created.profile_photo_url,
                        is_adult=created.consent_adult,
                        bio=created.short_bio,
                        roles=created.roles,
                        skills=created.skills,
                        years_experience=created.years_experience,
                        languages=created.languages_known,
                        linkedin_url=created.linkedin_url,
                        portfolio_url=created.portfolio_url,
                        resume_url=created.resume_url,
                        availability=created.availability,
                        hours_per_week=created.hours_per_week,
                        expected_compensation=created.expected_compensation,
                        info_accurate=created.consent_accurate,
                        agree_terms=created.consent_terms,
                        reference_number=created.reference_number,
                        submitted_at=submitted_at,
                    )
                )
                logger.info(
                    "virtual_assistant.application.admin_email.sent id=%s ref=%s",
                    created.id,
                    created.reference_number,
                )
            except Exception:
                logger.exception(
                    "virtual_assistant.application.admin_email.failed id=%s ref=%s",
                    created.id,
                    created.reference_number,
                )

        logger.info(
            "virtual_assistant.application.submit.complete ref=%s email=%s ids=%s",
            primary_row.reference_number,
            primary_row.email,
            [r.id for r in created_rows],
        )
        return {
            "reference_number": primary_row.reference_number,
            "email": primary_row.email,
            "new_roles": created_roles,
            "skipped_roles": skipped_roles,
            "reference_numbers": [r.reference_number for r in created_rows],
        }

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
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return asyncio.run(coro)
