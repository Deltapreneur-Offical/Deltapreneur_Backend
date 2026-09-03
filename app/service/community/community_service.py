import logging
import re
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.entity.community.community import Community
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.model.community.community_create_request import CommunityCreateRequest
from app.model.community.community_update_request import CommunityUpdateRequest
from app.repository.community_repository import CommunityRepository
from app.repository.profile_view_repository import ProfileViewRepository
from app.service.marketplace.listing_view_counter import record_community_profile_view
from app.repository.community_auction_repository import CommunityAuctionRepository
from app.entity.community.community_auction import CommunityAuction
from app.service.notification.notification_service import NotificationService
from app.integrations.s3.supabase_storage import resolve_media_url
from app.integrations import local_storage
from urllib.parse import unquote
import httpx
from app.service.community import linkedin_oauth
from app.repository.user_repository import UserRepository
from app.core.config import settings
from app.utils.community_profile_completion import (
    evaluate_profile_completion,
    is_profile_complete,
)


class CommunityService:
    @staticmethod
    def _clear_profile_details(community: Community) -> None:
        """Remove creator-facing fields (used on delete / fresh LinkedIn reconnect)."""
        community.role = None
        community.skills = None
        community.industry = None
        community.location = None
        community.why_im_here = None
        community.about = None
        community.linked_in_profile_url = None
        community.cover_image_url = None
        community.expected_rate = None
        community.introduction_video_link = None
        community.resume_drive_link = None
        community.portfolio_website_link = None
        community.preferred_work_type = None
        community.industry_expertise = None
        community.languages_known = None
        community.pitch_deck_link = None
        community.youtube_video_link = None
        community.headline = None
        community.education = None
        community.graduation_year = None
        community.experience = None
        community.github_profile = None
        community.social_media_profile = None
        community.current_company = None
        community.designation = None
        community.role_description = None
        community.company_name = None
        community.company_website = None
        community.availability = None
        community.hiring_for = None
        community.mentorship_topics = None
        community.investment_focus = None
        community.investment_stage = None
        community.ticket_size = None
        community.startup_stage = None
        community.co_founder_needs = None
        community.incubation_programs = None
        community.support_offered = None

    @staticmethod
    def _attach_profile_completion(payload: dict, community: Community) -> dict:
        completion = evaluate_profile_completion(community)
        payload.update(
            {
                "profile_complete": completion["is_complete"],
                "profileComplete": completion["is_complete"],
                "profile_completion_percent": completion["percent"],
                "profileCompletionPercent": completion["percent"],
                "profile_status": completion["status"],
                "profileStatus": completion["status"],
                "profile_missing_fields": completion["missing_fields"],
                "profileMissingFields": completion["missing_fields"],
            }
        )
        return payload

    @staticmethod
    def _is_ephemeral_linkedin_cdn_url(url: str | None) -> bool:
        """LinkedIn CDN / DMS URLs expire and block hotlinking in browsers."""
        if not url:
            return False
        lower = url.lower()
        return "licdn.com" in lower or "media.linkedin.com" in lower

    @staticmethod
    def _is_loopback_url(url: str | None) -> bool:
        if not url:
            return False
        lower = url.lower()
        return "127.0.0.1" in lower or "localhost" in lower

    @staticmethod
    def _persisted_linkedin_upload_url(linkedin_id: str | None) -> str | None:
        """
        Prefer a durable ``/uploads/community-images/linkedin_<id>.*`` photo.

        Checks local disk first, then known non-loopback upload bases (e.g. prod),
        without writing the database.
        """
        if not linkedin_id or not str(linkedin_id).strip():
            return None
        safe = re.sub(r"[^A-Za-z0-9_\-]", "_", str(linkedin_id).strip())
        for ext in ("jpg", "jpeg", "png", "webp"):
            rel = f"community-images/linkedin_{safe}.{ext}"
            if (local_storage.UPLOADS_ROOT / rel).is_file():
                return local_storage.build_local_image_url(rel)

        bases: list[str] = []
        for candidate in (
            (settings.BACKEND_BASE_URL or "").strip().rstrip("/"),
            "https://backend.cobrother.com",
        ):
            if candidate and candidate not in bases and not CommunityService._is_loopback_url(candidate):
                bases.append(candidate)
        if not bases:
            return None
        # Saved LinkedIn downloads use .jpg by convention.
        return f"{bases[0]}/uploads/community-images/linkedin_{safe}.jpg"

    @staticmethod
    def _usable_creator_media_url(
        url: str | None,
        *,
        linkedin_id: str | None = None,
    ) -> str | None:
        """
        Return a browser-loadable URL when possible.

        Read-only for the database. Does not rewrite working production
        ``/uploads/`` URLs onto a local host that is missing the file.
        """
        original = (url or "").strip() or None

        # If we still have a LinkedIn CDN link, prefer any durable upload copy.
        if CommunityService._is_ephemeral_linkedin_cdn_url(original):
            persisted = CommunityService._persisted_linkedin_upload_url(linkedin_id)
            if persisted:
                return persisted
            return None

        if not original:
            return CommunityService._persisted_linkedin_upload_url(linkedin_id)

        resolved = resolve_media_url(original)
        if not resolved:
            return CommunityService._persisted_linkedin_upload_url(linkedin_id)

        if "/uploads/" in resolved:
            if local_storage.local_upload_file_exists(resolved):
                return resolved
            # Local DEV often rewrites prod upload URLs to 127.0.0.1 — keep the
            # original host when it is not loopback so the image still loads.
            if "/uploads/" in original and not CommunityService._is_loopback_url(original):
                return original
            persisted = CommunityService._persisted_linkedin_upload_url(linkedin_id)
            if persisted:
                return persisted
            return None

        return resolved

    @staticmethod
    def _to_response(community: Community) -> dict:
        linkedin_id = getattr(community, "linked_in_id", None)
        resolved_image = CommunityService._usable_creator_media_url(
            community.image_url,
            linkedin_id=linkedin_id,
        )
        resolved_cover = CommunityService._usable_creator_media_url(
            getattr(community, "cover_image_url", None),
            linkedin_id=linkedin_id,
        )
        app_user_id = (
            str(community.app_user_id) if community.app_user_id else None
        )
        payload = {
            "id": str(community.id),
            "linked_in_id": community.linked_in_id,
            "name": community.name,
            "image_url": resolved_image,
            "cover_image_url": resolved_cover,
            "linked_in_profile_url": community.linked_in_profile_url,
            "role": community.role,
            "views": community.views,
            "skills": community.skills,
            "industry": community.industry,
            "location": community.location,
            "why_im_here": community.why_im_here,
            "about": getattr(community, "about", None),
            "expected_rate": getattr(community, "expected_rate", None),
            "introduction_video_link": getattr(community, "introduction_video_link", None),
            "resume_drive_link": getattr(community, "resume_drive_link", None),
            "portfolio_website_link": getattr(community, "portfolio_website_link", None),
            "preferred_work_type": getattr(community, "preferred_work_type", None),
            "industry_expertise": getattr(community, "industry_expertise", None),
            "languages_known": getattr(community, "languages_known", None),
            "pitch_deck_link": getattr(community, "pitch_deck_link", None),
            "youtube_video_link": getattr(community, "youtube_video_link", None),
            "headline": getattr(community, "headline", None),
            "education": getattr(community, "education", None),
            "graduation_year": getattr(community, "graduation_year", None),
            "experience": getattr(community, "experience", None),
            "github_profile": getattr(community, "github_profile", None),
            "social_media_profile": getattr(community, "social_media_profile", None),
            "current_company": getattr(community, "current_company", None),
            "designation": getattr(community, "designation", None),
            "role_description": getattr(community, "role_description", None),
            "company_name": getattr(community, "company_name", None),
            "company_website": getattr(community, "company_website", None),
            "availability": getattr(community, "availability", None),
            "hiring_for": getattr(community, "hiring_for", None),
            "mentorship_topics": getattr(community, "mentorship_topics", None),
            "investment_focus": getattr(community, "investment_focus", None),
            "investment_stage": getattr(community, "investment_stage", None),
            "ticket_size": getattr(community, "ticket_size", None),
            "startup_stage": getattr(community, "startup_stage", None),
            "co_founder_needs": getattr(community, "co_founder_needs", None),
            "incubation_programs": getattr(community, "incubation_programs", None),
            "support_offered": getattr(community, "support_offered", None),
            "is_approved": community.is_approved,
            "featured": bool(getattr(community, "featured", False)),
            "app_user_id": app_user_id,
            "created_at": community.created_at,
            "updated_at": community.updated_at,
        }
        # Frontend compatibility: React components expect camelCase keys and an
        # appUser object for ownership checks.
        payload.update(
            {
                "linkedInId": payload["linked_in_id"],
                "imageUrl": payload["image_url"],
                "coverImageUrl": payload["cover_image_url"],
                "linkedInProfileUrl": payload["linked_in_profile_url"],
                "whyImHere": payload["why_im_here"],
                "about": payload["about"],
                "expectedRate": payload["expected_rate"],
                "introductionVideoLink": payload["introduction_video_link"],
                "resumeDriveLink": payload["resume_drive_link"],
                "portfolioWebsiteLink": payload["portfolio_website_link"],
                "preferredWorkType": payload["preferred_work_type"],
                "industryExpertise": payload["industry_expertise"],
                "languagesKnown": payload["languages_known"],
                "pitchDeckLink": payload["pitch_deck_link"],
                "youtubeVideoLink": payload["youtube_video_link"],
                "headline": payload["headline"],
                "education": payload["education"],
                "graduationYear": payload["graduation_year"],
                "experience": payload["experience"],
                "githubProfile": payload["github_profile"],
                "socialMediaProfile": payload["social_media_profile"],
                "currentCompany": payload["current_company"],
                "designation": payload["designation"],
                "roleDescription": payload["role_description"],
                "companyName": payload["company_name"],
                "companyWebsite": payload["company_website"],
                "availability": payload["availability"],
                "hiringFor": payload["hiring_for"],
                "mentorshipTopics": payload["mentorship_topics"],
                "investmentFocus": payload["investment_focus"],
                "investmentStage": payload["investment_stage"],
                "ticketSize": payload["ticket_size"],
                "startupStage": payload["startup_stage"],
                "coFounderNeeds": payload["co_founder_needs"],
                "incubationPrograms": payload["incubation_programs"],
                "supportOffered": payload["support_offered"],
                "isApproved": payload["is_approved"],
                "featured": bool(getattr(community, "featured", False)),
                "appUserId": app_user_id,
                "createdAt": payload["created_at"],
                "updatedAt": payload["updated_at"],
                "appUser": {"id": app_user_id} if app_user_id else None,
                # Legacy alias used in some React checks.
                "user": {"id": app_user_id} if app_user_id else None,
            }
        )
        return CommunityService._attach_profile_completion(payload, community)

    @staticmethod
    def _apply_field_updates(
        community: Community,
        update_data: dict,
    ) -> None:
        for field, value in update_data.items():
            if value is None:
                setattr(community, field, None)
                continue

            if field in {"role", "industry"}:
                setattr(community, field, value.value)
            else:
                setattr(community, field, value)

    @staticmethod
    def _sync_listable_approval(community: Community) -> None:
        """Mark profiles listable only when all mandatory creator fields are complete."""
        community.is_approved = is_profile_complete(community)


    @staticmethod
    def _notify_user(
        db: Session,
        current_user: AppUser,
        notification_type: NotificationType,
        title: str,
        message: str,
        target_url: str = "/community",
    ) -> None:
        try:
            NotificationService.notify(
                db=db,
                user=current_user,
                notification_type=notification_type,
                title=title,
                message=message,
                target_url=target_url,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Community action completed but notification creation failed"
            )


    @staticmethod
    def create_my_profile(
        db: Session,
        request: CommunityCreateRequest,
        current_user: AppUser,
    ) -> dict:
        existing = CommunityRepository.find_any_by_app_user_id(
            db=db,
            app_user_id=current_user.id,
        )

        if existing and not existing.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Creator profile already exists",
            )

        payload = request.model_dump(exclude_unset=True)

        if payload.get("linked_in_id"):
            other = CommunityRepository.find_by_linked_in_id(
                db=db,
                linked_in_id=payload["linked_in_id"],
            )

            if other is not None and (
                existing is None or other.id != existing.id
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This LinkedIn profile is already linked to another account",
                )

        if existing and existing.is_deleted:
            existing.is_deleted = False
            existing.deleted_at = None
            existing.deleted_by = None

            CommunityService._apply_field_updates(
                community=existing,
                update_data=payload,
            )
            CommunityService._sync_listable_approval(existing)

            try:
                saved = CommunityRepository.save(db, existing)
            except IntegrityError:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Unable to restore profile due to a data conflict",
                ) from None

            CommunityService._notify_user(
                db=db,
                current_user=current_user,
                notification_type=NotificationType.COMMUNITY_PROFILE_CREATED,
                title="Creator profile created",
                message="Your community profile has been restored successfully.",
            )

            return CommunityService._to_response(saved)

        community = Community(
            app_user_id=current_user.id,
        )

        CommunityService._apply_field_updates(
            community=community,
            update_data=payload,
        )
        CommunityService._sync_listable_approval(community)

        try:
            saved = CommunityRepository.save(db, community)
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Unable to create profile due to a data conflict",
            ) from None

        CommunityService._notify_user(
            db=db,
            current_user=current_user,
            notification_type=NotificationType.COMMUNITY_PROFILE_CREATED,
            title="Creator profile created",
            message="Your community profile has been created successfully.",
        )

        return CommunityService._to_response(saved)


    @staticmethod
    def get_all_profiles(
        db: Session,
        *,
        featured_only: bool = False,
        page_size: int | None = None,
    ) -> list[dict]:
        from app.service.community.community_auction_service import (
            CommunityAuctionService,
        )

        if featured_only:
            communities = CommunityRepository.find_for_listing(
                db,
                featured_only=True,
                limit=None,
            )
            complete = list(communities)
        else:
            if page_size is not None:
                communities = CommunityRepository.find_for_listing(
                    db,
                    featured_only=False,
                    limit=page_size,
                )
            else:
                communities = CommunityRepository.find_all(db)

            complete = [community for community in communities if is_profile_complete(community)]
            if page_size is not None:
                complete = complete[:page_size]

        profile_ids = [community.id for community in complete]
        view_counts = ProfileViewRepository.bulk_unique_viewer_counts(db, profile_ids)
        auctions = CommunityAuctionRepository.find_by_community_ids(db, profile_ids)
        auction_by_community = CommunityAuctionService.build_profile_summaries_by_community(
            auctions,
        )

        rows: list[dict] = []
        for community in complete:
            payload = CommunityService._to_response(community)
            payload["views"] = view_counts.get(str(community.id), 0)
            summary = auction_by_community.get(str(community.id))
            if summary:
                payload["auctionSummary"] = summary
            rows.append(payload)
        rows.sort(
            key=lambda row: str(row.get("createdAt") or row.get("created_at") or ""),
            reverse=True,
        )
        rows.sort(key=lambda row: not bool(row.get("featured")))
        return rows

    @staticmethod
    def get_profile_by_id(
        db: Session,
        community_id: uuid.UUID,
        current_user: AppUser | None,
    ) -> dict:
        community = CommunityRepository.find_by_id(
            db=db,
            community_id=community_id,
        )

        is_owner = False
        if community is None and current_user is not None:
            any_community = CommunityRepository.find_by_id_any(
                db=db,
                community_id=community_id,
            )
            if (
                any_community is not None
                and any_community.is_deleted
                and any_community.app_user_id == current_user.id
            ):
                community = any_community
                is_owner = True

        if not community:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Creator profile not found",
            )

        is_owner = is_owner or (
            current_user is not None
            and community.app_user_id == current_user.id
        )
        if not is_profile_complete(community) and not is_owner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Creator profile not found",
            )

        if current_user is not None:
            def _increment_views() -> None:
                community.views = ProfileViewRepository.count_unique_viewers(
                    db,
                    community_id,
                )
                CommunityRepository.save(db, community)

            try:
                record_community_profile_view(
                    db,
                    community_id=community_id,
                    owner_user_id=community.app_user_id,
                    viewer=current_user,
                    increment_views=_increment_views,
                )
            except Exception:
                logging.getLogger(__name__).exception(
                    "Creator profile view tracking failed community_id=%s viewer_id=%s",
                    community_id,
                    current_user.id,
                )
        saved_community = CommunityRepository.find_by_id(db=db, community_id=community_id)
        if saved_community is None and is_owner:
            saved_community = CommunityRepository.find_by_id_any(
                db=db,
                community_id=community_id,
            )
        if saved_community is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Creator profile not found",
            )

        payload = CommunityService._to_response(saved_community)
        payload["views"] = ProfileViewRepository.count_unique_viewers(
            db,
            community_id,
        )
        return payload

    @staticmethod
    def get_my_profile(
        db: Session,
        current_user: AppUser,
    ) -> dict | None:
        rows = CommunityRepository.find_all_by_app_user_id(
            db=db,
            app_user_id=current_user.id,
        )
        active_rows = [row for row in rows if not row.is_deleted]
        if active_rows:
            return CommunityService._to_response(active_rows[0])

        if rows and all(row.is_deleted for row in rows):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Creator profile was removed. Connect with LinkedIn to set it up again.",
            )

        # No profile yet — return null (200) so clients can show "create profile"
        # without treating a missing profile as a hard API failure / console 404.
        return None

    @staticmethod
    def update_profile(
        db: Session,
        community_id: uuid.UUID,
        request: CommunityUpdateRequest,
        current_user: AppUser,
    ) -> dict:
        community = CommunityRepository.find_by_id(
            db=db,
            community_id=community_id,
        )

        if not community:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Creator profile not found",
            )

        if community.app_user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only update your own community profile",
            )

        update_data = request.model_dump(exclude_unset=True)

        CommunityService._apply_field_updates(
            community=community,
            update_data=update_data,
        )

        CommunityService._sync_listable_approval(community)
        saved_community = CommunityRepository.save(db, community)

        CommunityService._notify_user(
            db=db,
            current_user=current_user,
            notification_type=NotificationType.COMMUNITY_PROFILE_UPDATED,
            title="Creator profile updated",
            message="Your community profile has been updated successfully.",
        )

        return CommunityService._to_response(saved_community)

    @staticmethod
    def delete_profile(
        db: Session,
        community_id: uuid.UUID,
        current_user: AppUser,
    ) -> None:
        community = CommunityRepository.find_by_id(
            db=db,
            community_id=community_id,
        )

        if not community:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Creator profile not found",
            )

        if community.app_user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own community profile",
            )

        auctions = (
            db.query(CommunityAuction)
            .filter(
                CommunityAuction.community_id == community_id,
                CommunityAuction.is_deleted.is_(False),
            )
            .all()
        )
        for auction in auctions:
            CommunityAuctionRepository.soft_delete(
                db=db,
                auction=auction,
                deleted_by=current_user.id,
            )

        community.linked_in_id = None
        community.name = None
        community.image_url = None
        CommunityService._clear_profile_details(community)

        CommunityRepository.soft_delete(
            db=db,
            community=community,
            deleted_by=current_user.id,
        )

    @staticmethod
    def _linkedin_config_ready() -> bool:
        return bool(
            settings.LINKEDIN_CLIENT_ID
            and settings.LINKEDIN_CLIENT_SECRET
        )

    @staticmethod
    def _normalize_linkedin_oauth_state(state: str) -> str:
        """LinkedIn may return state once or twice URL-encoded depending on redirect chain."""
        raw = (state or "").strip()
        for _ in range(3):
            decoded = unquote(raw)
            if decoded == raw:
                break
            raw = decoded
        return raw

    @staticmethod
    def _decode_linkedin_oauth_state(state: str) -> str:
        email, _, _ = CommunityService._parse_linkedin_oauth_state_payload(state)
        return email

    @staticmethod
    def _parse_linkedin_oauth_state(state: str) -> tuple[str, str | None]:
        email, return_origin, _redirect_uri = CommunityService._parse_linkedin_oauth_state_payload(
            state
        )
        return email, return_origin

    @staticmethod
    def _parse_linkedin_oauth_state_payload(
        state: str,
    ) -> tuple[str, str | None, str | None]:
        """Return (email, return_origin, redirect_uri) from a signed LinkedIn OAuth state token.

        This is the canonical state-parsing method.  Its return signature must
        remain a 3-tuple to preserve backward compatibility with existing callers
        and tests.  Any additional state fields should be read via dedicated
        helpers such as ``_parse_linkedin_oauth_state_action``.
        """
        from app.core.oauth_state import parse_oauth_state

        raw = CommunityService._normalize_linkedin_oauth_state(state)
        payload = parse_oauth_state(raw, provider="linkedin_community")
        if not payload:
            return "", None, None

        email = str(payload.get("email") or "").strip()
        redirect_uri = payload.get("redirect_uri")
        if redirect_uri is not None:
            redirect_uri = str(redirect_uri).strip() or None
        return_origin = CommunityService._allowed_linkedin_return_origin(
            payload.get("return_origin"),
        )
        return email, return_origin, redirect_uri

    @staticmethod
    def _parse_linkedin_oauth_state_action(state: str) -> str | None:
        """Extract the optional ``action`` field from a signed LinkedIn OAuth state token.

        This is a dedicated helper for the new sync-photo flow.  It intentionally
        does NOT change the signature of ``_parse_linkedin_oauth_state_payload``
        so that existing callers and tests are unaffected.
        """
        from app.core.oauth_state import parse_oauth_state

        raw = CommunityService._normalize_linkedin_oauth_state(state)
        payload = parse_oauth_state(raw, provider="linkedin_community")
        if not isinstance(payload, dict):
            return None
        return str(payload.get("action") or "").strip() or None

    @staticmethod
    def _encode_linkedin_oauth_state(
        *,
        email: str,
        redirect_uri: str,
        return_origin: str | None = None,
    ) -> str:
        from app.core.oauth_state import create_oauth_state

        safe_origin = CommunityService._allowed_linkedin_return_origin(return_origin)
        return create_oauth_state(
            "linkedin_community",
            email=email,
            redirect_uri=redirect_uri,
            return_origin=safe_origin,
        )

    @staticmethod
    def _allowed_linkedin_return_origin(return_origin: str | None) -> str | None:
        from app.core.frontend_origins import allowed_frontend_return_origin

        return allowed_frontend_return_origin(return_origin)

    @staticmethod
    def get_linkedin_authorization_url(
        current_user: AppUser,
        *,
        redirect_uri: str,
        return_origin: str | None = None,
    ) -> str:
        if not CommunityService._linkedin_config_ready():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="LinkedIn OAuth is not configured",
            )

        state = CommunityService._encode_linkedin_oauth_state(
            email=current_user.email,
            redirect_uri=redirect_uri,
            return_origin=return_origin,
        )

        return linkedin_oauth.build_authorization_url(
            client_id=settings.LINKEDIN_CLIENT_ID,
            redirect_uri=redirect_uri,
            state=state,
        )

    @staticmethod
    def get_sync_photo_authorization_url(
        current_user: AppUser,
        *,
        redirect_uri: str,
        return_origin: str | None = None,
    ) -> str:
        """Generate a LinkedIn OAuth URL whose callback will only update image_url."""
        if not CommunityService._linkedin_config_ready():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="LinkedIn OAuth is not configured",
            )

        from app.core.oauth_state import create_oauth_state

        safe_origin = CommunityService._allowed_linkedin_return_origin(return_origin)
        state = create_oauth_state(
            "linkedin_community",
            email=current_user.email,
            redirect_uri=redirect_uri,
            return_origin=safe_origin,
            action="sync_photo",
        )

        return linkedin_oauth.build_authorization_url(
            client_id=settings.LINKEDIN_CLIENT_ID,
            redirect_uri=redirect_uri,
            state=state,
        )

    @staticmethod
    def _upload_linkedin_picture(picture_url: str, linkedin_id: str) -> str | None:
        """
        Download a LinkedIn CDN profile picture and save it to local storage.

        LinkedIn CDN URLs expire and often 403 in the browser. Persist the image
        under ``uploads/community-images/`` and return that permanent URL.

        Returns None when download/save fails — callers must keep any previous
        good ``image_url`` instead of storing the raw LinkedIn CDN link.
        """
        _log = logging.getLogger(__name__)
        if not picture_url or not str(picture_url).strip():
            return None
        try:
            stem = f"linkedin_{linkedin_id}"
            permanent_url = local_storage.download_and_save(
                picture_url,
                folder="community-images",
                stem=stem,
            )
            _log.info(
                "Saved LinkedIn profile picture locally for linkedin_id=%s → %s",
                linkedin_id,
                permanent_url,
            )
            return permanent_url
        except Exception:
            _log.warning(
                "Failed to save LinkedIn picture locally for linkedin_id=%s; "
                "leaving existing image_url unchanged (not storing CDN URL).",
                linkedin_id,
                exc_info=True,
            )
            return None

    @staticmethod
    def sync_profile_photo_from_linkedin(
        db: Session,
        code: str,
        state: str,
    ) -> uuid.UUID:
        """
        Exchange the LinkedIn auth code and update **only** image_url on the
        community profile.  No other field (name, headline, bio, skills, etc.)
        is ever modified by this method.
        """
        if not CommunityService._linkedin_config_ready():
            raise ValueError("LinkedIn OAuth is not configured")

        email, _return_origin, redirect_uri_from_state = (
            CommunityService._parse_linkedin_oauth_state_payload(state)
        )
        redirect_uri = redirect_uri_from_state or linkedin_oauth.resolve_linkedin_redirect_uri()

        user = UserRepository.find_by_email_insensitive(db=db, email=email)
        if not user or user.is_deleted:
            raise ValueError("User not found")

        try:
            token_body = linkedin_oauth.exchange_authorization_code_response(
                client_id=settings.LINKEDIN_CLIENT_ID,
                client_secret=settings.LINKEDIN_CLIENT_SECRET,
                redirect_uri=redirect_uri,
                code=code,
            )
            access_token = str(token_body.get("access_token") or "")
            if not access_token:
                raise ValueError("LinkedIn token exchange failed: no access_token")

            member = linkedin_oauth.fetch_linkedin_member_profile(
                access_token,
                id_token=str(token_body.get("id_token") or "") or None,
            )
        except httpx.HTTPError as exc:
            raise ValueError("LinkedIn token or profile request failed") from exc

        linked_in_id = str(member.get("linked_in_id") or "").strip()
        picture = member.get("picture")

        if not linked_in_id:
            raise ValueError("LinkedIn userinfo missing subject")

        if not picture:
            raise ValueError(
                "Unable to fetch the latest LinkedIn profile photo. "
                "Please reconnect your LinkedIn account and try again."
            )

        # Look up the community profile for this user.
        community = CommunityRepository.find_any_by_app_user_id(
            db=db, app_user_id=user.id
        )
        if community is None or community.is_deleted:
            raise ValueError("Creator profile not found — please create your profile first.")

        # Download and persist the picture; only update image_url if successful.
        permanent_picture = CommunityService._upload_linkedin_picture(picture, linked_in_id)
        if permanent_picture:
            community.image_url = permanent_picture
        else:
            raise ValueError(
                "Unable to fetch the latest LinkedIn profile photo. "
                "Please reconnect your LinkedIn account and try again."
            )

        saved = CommunityRepository.save(db, community)
        logging.getLogger(__name__).info(
            "Sync profile photo succeeded for user=%s community_id=%s",
            user.email,
            saved.id,
        )
        return saved.id

    @staticmethod
    def handle_linkedin_oauth_callback(
        db: Session,
        code: str,
        state: str,
    ) -> tuple[uuid.UUID, bool]:
        if not CommunityService._linkedin_config_ready():
            raise ValueError("LinkedIn OAuth is not configured")

        email, _return_origin, redirect_uri_from_state = (
            CommunityService._parse_linkedin_oauth_state_payload(state)
        )
        redirect_uri = redirect_uri_from_state or linkedin_oauth.resolve_linkedin_redirect_uri()

        user = UserRepository.find_by_email_insensitive(
            db=db,
            email=email,
        )

        if not user or user.is_deleted:
            raise ValueError("User not found")

        try:
            token_body = linkedin_oauth.exchange_authorization_code_response(
                client_id=settings.LINKEDIN_CLIENT_ID,
                client_secret=settings.LINKEDIN_CLIENT_SECRET,
                redirect_uri=redirect_uri,
                code=code,
            )
            access_token = str(token_body.get("access_token") or "")
            if not access_token:
                raise ValueError("LinkedIn token exchange failed: no access_token")

            granted_scopes = str(token_body.get("scope") or "").strip()
            if granted_scopes and "r_profile_basicinfo" not in granted_scopes:
                logging.getLogger(__name__).warning(
                    "LinkedIn token missing r_profile_basicinfo in scope response; granted=%s",
                    granted_scopes,
                )

            member = linkedin_oauth.fetch_linkedin_member_profile(
                access_token,
                id_token=str(token_body.get("id_token") or "") or None,
            )

        except httpx.HTTPError as exc:
            raise ValueError("LinkedIn token or profile request failed") from exc

        linked_in_id = str(member.get("linked_in_id") or "").strip()
        if not linked_in_id:
            raise ValueError("LinkedIn userinfo missing subject")

        name = member.get("name")
        picture = member.get("picture")
        profile_url = member.get("profile_url")

        # Clear duplicate linked_in_id from any other community profile (including soft-deleted ones)
        CommunityRepository.clear_linked_in_id_from_other_users(
            db=db,
            linked_in_id=linked_in_id,
            exclude_app_user_id=user.id,
        )

        existing_linked_in_profile = CommunityRepository.find_by_linked_in_id(
            db=db,
            linked_in_id=linked_in_id,
        )

        if existing_linked_in_profile is not None:
            community = existing_linked_in_profile
        else:
            community = CommunityRepository.find_any_by_app_user_id(
                db=db,
                app_user_id=user.id,
            )

            if community is None:
                community = Community(
                    app_user_id=user.id,
                    views=0,
                    is_approved=False,
                )

            elif community.is_deleted:
                community.is_deleted = False
                community.deleted_at = None
                community.deleted_by = None
                CommunityService._clear_profile_details(community)

        assets = {
            "picture": picture,
            "background_picture": member.get("background_picture"),
        }

        community.linked_in_id = linked_in_id
        community.name = name or community.name
        raw_picture = assets.get("picture")
        if raw_picture:
            # LinkedIn CDN URLs expire / 403 in browsers. Only replace image_url
            # when we successfully persist a local copy (leave DB unchanged otherwise).
            permanent_picture = CommunityService._upload_linkedin_picture(
                raw_picture, linked_in_id
            )
            if permanent_picture:
                community.image_url = permanent_picture
        background = assets.get("background_picture")
        if background:
            permanent_cover = CommunityService._upload_linkedin_picture(
                background, f"{linked_in_id}_cover"
            )
            if permanent_cover:
                community.cover_image_url = permanent_cover
            # Do not store raw LinkedIn CDN covers — response layer hides them.
        if profile_url:
            community.linked_in_profile_url = profile_url

        CommunityService._sync_listable_approval(community)

        try:
            saved = CommunityRepository.save(db, community)
        except IntegrityError:
            db.rollback()
            raise ValueError(
                "Unable to save community profile. Possible LinkedIn conflict."
            ) from None

        try:
            NotificationService.notify(
                db=db,
                user=user,
                notification_type=NotificationType.COMMUNITY_LINKEDIN_LINKED,
                title="LinkedIn connected",
                message="Your community profile was updated from LinkedIn.",
                target_url="/community",
            )

        except Exception:
            logging.getLogger(__name__).exception(
                "LinkedIn profile saved but notification failed"
            )

        return saved.id, bool(profile_url)
