import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppException
from app.core.security import (
    create_access_token,
    generate_password_reset_token,
    generate_refresh_token,
    hash_otp_code,
    hash_password,
    hash_refresh_token,
    hash_reset_token,
    verify_password,
)

from app.entity.user.app_user import AppUser
from app.entity.user.auth_provider import AuthProvider
from app.entity.user.user_role import UserRole
from app.entity.user.password_reset_token import PasswordResetToken
from app.entity.user.refresh_token import RefreshToken, RevocationReason

from app.model.auth.complete_profile_request import CompleteProfileRequest
from app.model.auth.jwt_response import JwtResponse

from app.repository.password_reset_token_repository import (
    PasswordResetTokenRepository,
)
from app.repository.user_repository import UserRepository
from app.repository.refresh_token_repository import RefreshTokenRepository

from app.service.auth.auth_exceptions import (
    AccountInactiveException,
    EmailAlreadyExistsException,
    EmailNotVerifiedException,
    InvalidCredentialsException,
    InvalidPasswordResetTokenException,
    InvalidVerificationTokenException,
)
from app.service.auth.mail_service import MailService
from app.service.auth.signup_otp_cache import signup_otp_cache
from app.utils.user_identity import resolved_username

logger = logging.getLogger(__name__)

PASSWORD_RESET_EXPIRY_MINUTES = 30
# Overlapping /auth/refresh calls present the same parent after it was rotated.
# Treat that as an in-flight duplicate for this window — do not kill the session.
REFRESH_REUSE_GRACE = timedelta(seconds=30)
OTP_EXPIRY_MINUTES = 10
OTP_GENERIC_MESSAGE = (
    "If an account exists for this email, a one-time code has been sent."
)

REGISTER_OTP_SENT_MESSAGE = (
    "Verification code sent. Please check your email."
)

REGISTER_OTP_RESENT_MESSAGE = (
    "If a registration is in progress for this email, "
    "a new verification code has been sent."
)

FORGOT_PASSWORD_GENERIC_MESSAGE = (
    "If an account exists for this email, "
    "a password reset link has been sent."
)

INVALID_RESET_LINK_MESSAGE = "Invalid or expired reset link."

RESEND_VERIFICATION_GENERIC_MESSAGE = (
    "If this email is registered and pending verification, "
    "you will receive a message shortly."
)


class AuthService:

    @staticmethod
    def _assert_user_may_authenticate(user: AppUser) -> None:
        if user.is_deleted:
            raise InvalidCredentialsException("Account no longer exists")
        if not user.active:
            raise AccountInactiveException("Account is deactivated")

    @staticmethod
    def _is_eligible_for_password_reset(user: AppUser) -> bool:
        if not user.active or user.is_deleted:
            return False
        if not user.email_verified:
            return False
        return True

    @staticmethod
    async def register(
        db: Session,
        email: str,
        password: str,
    ):
        normalized_email = email.lower().strip()

        generic_success = {
            "success": True,
            "message": (
                "Registration successful. "
                "Please check your email to verify your account."
            ),
        }

        existing_user = UserRepository.find_by_email(
            db,
            normalized_email,
            include_deleted=True,
        )
        if existing_user:
            if existing_user.is_deleted:
                verification_token = str(uuid.uuid4())
                verification_expiry = datetime.now(UTC) + timedelta(
                    hours=24,
                )
                RefreshTokenRepository.revoke_all_user_tokens(
                    db,
                    existing_user,
                    RevocationReason.LOGOUT,
                )
                existing_user.is_deleted = False
                existing_user.deleted_at = None
                existing_user.deleted_by = None
                existing_user.password = hash_password(password)
                existing_user.role = UserRole.USER
                existing_user.auth_provider = AuthProvider.EMAIL
                existing_user.oauth_provider = None
                existing_user.oauth_provider_id = None
                existing_user.otp = None
                existing_user.otp_expiry = None
                existing_user.active = True
                existing_user.email_verified = False
                existing_user.verification_token = verification_token
                existing_user.verification_token_expiry = (
                    verification_expiry
                )
                existing_user.profile_complete = False
                db.commit()
                await MailService.send_verification_email(
                    existing_user.email,
                    verification_token,
                )
                return generic_success

            if existing_user.email_verified:
                raise EmailAlreadyExistsException(
                    "This email is already registered. Sign in or use Forgot Password."
                )

            if not existing_user.email_verified:
                verification_token = str(uuid.uuid4())
                verification_expiry = datetime.now(UTC) + timedelta(
                    hours=24,
                )
                existing_user.password = hash_password(password)
                existing_user.auth_provider = AuthProvider.EMAIL
                existing_user.verification_token = verification_token
                existing_user.verification_token_expiry = (
                    verification_expiry
                )
                db.commit()
                try:
                    await MailService.send_verification_email(
                        existing_user.email,
                        verification_token,
                    )
                except Exception:
                    logger.exception(
                        "Resend verification on duplicate register failed",
                    )
            return generic_success

        verification_token = str(uuid.uuid4())
        verification_expiry = datetime.now(UTC) + timedelta(hours=24)

        user = AppUser(
            email=normalized_email,
            password=hash_password(password),
            role=UserRole.USER,
            auth_provider=AuthProvider.EMAIL,
            active=True,
            email_verified=False,
            verification_token=verification_token,
            verification_token_expiry=verification_expiry,
            profile_complete=False,
        )

        saved_user = UserRepository.save(db, user)

        try:
            await MailService.send_verification_email(
                saved_user.email,
                verification_token,
            )
        except Exception:
            logger.exception(
                "Verification email failed for %s — account created; use resend or OTP login",
                saved_user.email,
            )

        return generic_success

    @staticmethod
    async def verify_email(
        db: Session,
        token: str,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
    ):
        user = UserRepository.find_by_verification_token(db, token)

        if not user:
            raise InvalidVerificationTokenException(
                "Invalid verification token."
            )

        if (
            user.verification_token_expiry
            and user.verification_token_expiry < datetime.now(UTC)
        ):
            raise InvalidVerificationTokenException(
                "Verification token has expired."
            )

        user.email_verified = True
        user.verification_token = None
        user.verification_token_expiry = None
        db.commit()
        db.refresh(user)

        AuthService._assert_user_may_authenticate(user)

        return AuthService._create_authenticated_session(
            db,
            user,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name,
            new_user=False,
        )

    @staticmethod
    def _names_allow_profile_complete(firstname: str | None, lastname: str | None) -> bool:
        return bool((firstname or "").strip() and (lastname or "").strip())

    @staticmethod
    def user_profile_payload(user: AppUser) -> dict:
        return {
            "id": str(user.id),
            "email": user.email,
            "role": user.role.value,
            "emailVerified": user.email_verified,
            "profileComplete": user.profile_complete,
            "firstname": user.firstname,
            "lastname": user.lastname,
            "username": resolved_username(user),
            "phoneNumber": user.phone_number,
            "phoneVerified": user.phone_verified,
            "address": user.address,
            "active": user.active,
        }

    @staticmethod
    def _create_authenticated_session(
        db: Session,
        user: AppUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
        new_user: bool = False,
    ):

        # Intentional single-session-on-login: a new login revokes other devices/tabs.
        RefreshTokenRepository.revoke_all_user_tokens(
            db,
            user,
            RevocationReason.LOGOUT,
        )

        # Generate new session
        session_public_id = uuid.uuid4()

        raw_token = generate_refresh_token()

        token_hash = hash_refresh_token(raw_token)

        refresh_expiry = datetime.now(UTC) + timedelta(
            milliseconds=settings.JWT_REFRESH_TOKEN_EXPIRE_MS
        )

        refresh_token = RefreshToken(
            token_hash=token_hash,
            user_id=user.id,
            session_public_id=session_public_id,
            expires_at=refresh_expiry,
            revoked=False,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name,
            pepper_kid=settings.JWT_REFRESH_TOKEN_PEPPER_KID,
        )

        RefreshTokenRepository.save(
            db,
            refresh_token,
        )

        access_token = create_access_token(
            subject=user.email,
            role=f"ROLE_{user.role.value}",
            session_public_id=str(session_public_id),
        )

        jwt_response = JwtResponse(
            accessToken=access_token,
            refreshToken=raw_token,
            userId=str(user.id),
            email=user.email,
            role=user.role.value,
            expiresIn=settings.JWT_ACCESS_TOKEN_EXPIRE_MS,
            newUser=new_user,
            emailVerified=user.email_verified,
            profileComplete=bool(user.profile_complete),
        )

        return {
            "success": True,
            "message": "Login successful",
            "data": jwt_response.model_dump(),
        }
    


    @staticmethod
    async def login(
        db: Session,
        email: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
    ):
        normalized_email = email.lower().strip()

        user = UserRepository.find_by_email(db, normalized_email)

        if not user:
            raise InvalidCredentialsException("Invalid email or password")

        if not user.password:
            if user.oauth_provider or user.auth_provider == AuthProvider.OAUTH:
                raise InvalidCredentialsException(
                    "This account uses Google sign-in. Use Continue with Google, "
                    "or choose Forgot Password to set an email password."
                )
            raise InvalidCredentialsException("Invalid email or password")

        if not verify_password(password, user.password):
            raise InvalidCredentialsException("Invalid email or password")

        if not user.email_verified:
            raise EmailNotVerifiedException(
                "Please verify your email before signing in."
            )

        AuthService._assert_user_may_authenticate(user)

        return AuthService._create_authenticated_session(
            db=db,
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name,
            new_user=False,
        )

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _latest_active_descendant(
        db: Session,
        token_id: uuid.UUID | None,
    ) -> RefreshToken | None:
        """Follow replaced_by links to the current unrevoked, unexpired token."""
        seen: set[uuid.UUID] = set()
        current_id = token_id
        while current_id is not None and current_id not in seen:
            seen.add(current_id)
            current = RefreshTokenRepository.find_by_id(db, current_id)
            if current is None:
                return None
            if not current.revoked:
                expires_at = AuthService._as_utc(current.expires_at)
                if expires_at is None or expires_at <= datetime.now(UTC):
                    return None
                return current
            current_id = current.replaced_by_token_id
        return None

    @staticmethod
    def _access_payload_for_session(user: AppUser, session_public_id) -> dict:
        access_token = create_access_token(
            subject=user.email,
            role=f"ROLE_{user.role.value}",
            session_public_id=str(session_public_id),
        )
        return {
            "success": True,
            "message": "Token refreshed successfully",
            "data": {
                "accessToken": access_token,
            },
        }

    @staticmethod
    def _inflight_rotated_refresh(
        db: Session,
        stored_token: RefreshToken,
    ) -> dict | None:
        """Return a new access JWT when this is a duplicate of a just-rotated parent.

        Does not return a refresh token, so Set-Cookie cannot overwrite the
        winner's child cookie. Outside the grace window, return None so the
        caller can treat it as reuse/theft.
        """
        if stored_token.replaced_by_token_id is None:
            return None
        reason = stored_token.revocation_reason
        if reason is not None and reason != RevocationReason.ROTATED:
            return None
        revoked_at = AuthService._as_utc(stored_token.revoked_at)
        if revoked_at is None:
            return None
        if datetime.now(UTC) - revoked_at > REFRESH_REUSE_GRACE:
            return None
        child = AuthService._latest_active_descendant(
            db,
            stored_token.replaced_by_token_id,
        )
        if child is None:
            return None
        if child.session_public_id != stored_token.session_public_id:
            return None
        user = stored_token.user or child.user
        if user is None or user.is_deleted or not user.active:
            return None
        return AuthService._access_payload_for_session(
            user,
            stored_token.session_public_id,
        )

    @staticmethod
    async def refresh_access_token(
        db: Session,
        raw_refresh_token: str,
    ):
        token_hash = hash_refresh_token(raw_refresh_token)
        stored_token = RefreshTokenRepository.find_by_token_hash(
            db, token_hash
        )

        if not stored_token:
            raise InvalidCredentialsException("Invalid refresh token")

        # Reuse detection: revoked token that was already rotated.
        # In-flight duplicates of the immediate parent (parallel refresh)
        # must not revoke the live session chain.
        if stored_token.revoked:
            inflight = AuthService._inflight_rotated_refresh(db, stored_token)
            if inflight is not None:
                return inflight
            if stored_token.replaced_by_token_id is not None:
                RefreshTokenRepository.revoke_session_chain(
                    db,
                    stored_token.session_public_id,
                    RevocationReason.REUSE_DETECTED,
                )
            raise InvalidCredentialsException("Refresh token revoked")

        if stored_token.expires_at < datetime.now(UTC):
            raise InvalidCredentialsException("Refresh token expired")

        user = stored_token.user
        if user.is_deleted:
            RefreshTokenRepository.revoke_session_chain(
                db,
                stored_token.session_public_id,
                RevocationReason.LOGOUT,
            )
            raise InvalidCredentialsException("Invalid refresh token")
        if not user.active:
            RefreshTokenRepository.revoke_session_chain(
                db,
                stored_token.session_public_id,
                RevocationReason.LOGOUT,
            )
            raise AccountInactiveException("Account is deactivated")

        # Issue new token in same session chain
        new_raw_token = generate_refresh_token()
        new_token_hash = hash_refresh_token(new_raw_token)
        refresh_expiry = datetime.now(UTC) + timedelta(
            milliseconds=settings.JWT_REFRESH_TOKEN_EXPIRE_MS
        )

        new_refresh_token = RefreshToken(
            token_hash=new_token_hash,
            user_id=user.id,
            session_public_id=stored_token.session_public_id,
            parent_token_id=stored_token.id,
            expires_at=refresh_expiry,
            revoked=False,
            ip_address=stored_token.ip_address,
            user_agent=stored_token.user_agent,
            device_name=stored_token.device_name,
            pepper_kid=settings.JWT_REFRESH_TOKEN_PEPPER_KID,
        )

        db.add(new_refresh_token)

        # Atomically revoke old token and link to new
        stored_token.revoked = True
        stored_token.revoked_at = datetime.now(UTC)
        stored_token.revocation_reason = RevocationReason.ROTATED

        db.commit()
        db.refresh(new_refresh_token)

        # Link old → new after both rows exist
        stored_token.replaced_by_token_id = new_refresh_token.id
        db.commit()

        access_token = create_access_token(
            subject=user.email,
            role=f"ROLE_{user.role.value}",
            session_public_id=str(stored_token.session_public_id),
        )

        return {
            "success": True,
            "message": "Token refreshed successfully",
            "data": {
                "accessToken": access_token,
                "refreshToken": new_raw_token,
            },
        }

    @staticmethod
    async def logout(
        db: Session,
        raw_refresh_token: str | None = None,
    ) -> dict:
        if raw_refresh_token:
            token_hash = hash_refresh_token(raw_refresh_token)
            stored_token = RefreshTokenRepository.find_by_token_hash(
                db, token_hash
            )

            if stored_token and not stored_token.revoked:
                RefreshTokenRepository.revoke_session_chain(
                    db,
                    stored_token.session_public_id,
                    RevocationReason.LOGOUT,
                )

        return {
            "success": True,
            "message": "Logout successful",
        }

    @staticmethod
    async def resend_verification_email(
        db: Session,
        email: str,
    ):
        normalized_email = email.lower().strip()

        user = UserRepository.find_by_email(db, normalized_email)

        if (
            user
            and not user.is_deleted
            and user.active
            and not user.email_verified
        ):
            verification_token = str(uuid.uuid4())
            verification_expiry = datetime.now(UTC) + timedelta(hours=24)
            user.verification_token = verification_token
            user.verification_token_expiry = verification_expiry
            db.commit()
            try:
                await MailService.send_verification_email(
                    user.email,
                    verification_token,
                )
            except Exception:
                logger.exception("Resend verification email failed")

        return {
            "success": True,
            "message": RESEND_VERIFICATION_GENERIC_MESSAGE,
        }

    @staticmethod
    async def login_with_google_profile(
        db: Session,
        google_user: dict,
        google_tokens: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
    ):
        google_tokens = google_tokens or {}
        google_access_token = (google_tokens.get("access_token") or "").strip()
        google_refresh_token = (google_tokens.get("refresh_token") or "").strip()

        email = google_user.get("email")
        email_verified = google_user.get("email_verified", False)
        google_sub = google_user.get("sub")
        firstname = google_user.get("given_name")
        lastname = google_user.get("family_name")

        if not email_verified:
            raise InvalidCredentialsException(
                "Google account email is not verified"
            )
        if not email:
            raise InvalidCredentialsException("Google account email missing")
        if not google_sub or not str(google_sub).strip():
            raise InvalidCredentialsException(
                "Google account identifier missing"
            )

        google_sub = str(google_sub).strip()
        normalized_email = email.lower().strip()

        existing_oauth_user = (
            UserRepository.find_by_oauth_provider_and_provider_id(
                db,
                "google",
                google_sub,
            )
        )
        if existing_oauth_user:
            AuthService._assert_user_may_authenticate(existing_oauth_user)
            if google_access_token:
                existing_oauth_user.google_access_token = google_access_token
            # Google may omit refresh_token on subsequent logins; preserve old one.
            if google_refresh_token:
                existing_oauth_user.google_refresh_token = google_refresh_token
            db.commit()
            return AuthService._create_authenticated_session(
                db=db,
                user=existing_oauth_user,
                ip_address=ip_address,
                user_agent=user_agent,
                device_name=device_name,
                new_user=False,
            )

        existing_email_user = UserRepository.find_by_email(
            db,
            normalized_email,
        )
        if existing_email_user:
            AuthService._assert_user_may_authenticate(existing_email_user)
            if not existing_email_user.email_verified:
                raise InvalidCredentialsException(
                    "Please verify your email before signing in with Google."
                )
            # A verified email proves ownership, so it is safe to attach the
            # Google identity to this existing account instead of creating a
            # duplicate. We only block a genuine conflict where this email is
            # already bound to a *different* Google account (which would mean
            # two distinct Google identities claim the same verified email).
            existing_linked_id = existing_email_user.oauth_provider_id
            if (
                existing_email_user.oauth_provider == "google"
                and existing_linked_id
                and existing_linked_id != google_sub
            ):
                raise InvalidCredentialsException(
                    "This email is linked to a different Google account"
                )
            existing_email_user.oauth_provider = "google"
            existing_email_user.oauth_provider_id = google_sub
            if google_access_token:
                existing_email_user.google_access_token = google_access_token
            if google_refresh_token:
                existing_email_user.google_refresh_token = google_refresh_token
            db.commit()
            db.refresh(existing_email_user)
            return AuthService._create_authenticated_session(
                db=db,
                user=existing_email_user,
                ip_address=ip_address,
                user_agent=user_agent,
                device_name=device_name,
                new_user=False,
            )

        tombstone = UserRepository.find_by_email(
            db,
            normalized_email,
            include_deleted=True,
        )
        if tombstone and tombstone.is_deleted:
            raise InvalidCredentialsException(
                "This email is not available for sign-in"
            )

        user = AppUser(
            email=normalized_email,
            firstname=firstname,
            lastname=lastname,
            password=None,
            role=UserRole.USER,
            auth_provider=AuthProvider.OAUTH,
            oauth_provider="google",
            oauth_provider_id=google_sub,
            google_access_token=google_access_token or None,
            google_refresh_token=google_refresh_token or None,
            active=True,
            email_verified=True,
            profile_complete=False,
        )
        saved_user = UserRepository.save(db, user)
        return AuthService._create_authenticated_session(
            db=db,
            user=saved_user,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name,
            new_user=True,
        )

    @staticmethod
    async def login_with_oauth_profile(
        db: Session,
        provider: str,
        provider_id: str,
        email: str | None,
        firstname: str | None = None,
        lastname: str | None = None,
        picture: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
    ):
        provider_id = str(provider_id).strip() if provider_id else ""
        provider = provider.lower().strip()

        if not provider_id:
            raise InvalidCredentialsException("Invalid OAuth provider id")

        if not email:
            normalized_email = f"{provider}_{provider_id}@{provider}.cobrother.com"
        else:
            normalized_email = email.lower().strip()

        existing_oauth_user = (
            UserRepository.find_by_oauth_provider_and_provider_id(
                db,
                provider,
                provider_id,
            )
        )
        if existing_oauth_user:
            AuthService._assert_user_may_authenticate(existing_oauth_user)
            if provider == "linkedin":
                AuthService._ensure_linkedin_community_profile(
                    db, existing_oauth_user, provider_id, firstname, lastname, picture
                )
            db.commit()
            return AuthService._create_authenticated_session(
                db=db,
                user=existing_oauth_user,
                ip_address=ip_address,
                user_agent=user_agent,
                device_name=device_name,
                new_user=False,
            )

        if provider == "linkedin":
            from app.entity.community.community import Community
            from app.repository.community_repository import CommunityRepository

            existing_linkedin_community = CommunityRepository.find_by_linked_in_id(
                db,
                linked_in_id=provider_id,
            )
            if existing_linkedin_community:
                linkedin_user = UserRepository.find_by_id(
                    db,
                    existing_linkedin_community.app_user_id,
                )
                if linkedin_user:
                    AuthService._assert_user_may_authenticate(linkedin_user)
                    AuthService._ensure_linkedin_community_profile(
                        db,
                        linkedin_user,
                        provider_id,
                        firstname,
                        lastname,
                        picture,
                    )
                    db.commit()
                    return AuthService._create_authenticated_session(
                        db=db,
                        user=linkedin_user,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        device_name=device_name,
                        new_user=False,
                    )

        existing_email_user = UserRepository.find_by_email(
            db,
            normalized_email,
        )
        if existing_email_user:
            AuthService._assert_user_may_authenticate(existing_email_user)
            if not existing_email_user.email_verified:
                raise InvalidCredentialsException(
                    f"Please verify your email before signing in with {provider.capitalize()}."
                )
            # A verified email proves ownership, so it is safe to attach this
            # OAuth identity to the existing account instead of creating a
            # duplicate. Only block a genuine conflict where this email is
            # already bound to a *different* {provider} account.
            existing_linked_id = existing_email_user.oauth_provider_id
            if (
                existing_email_user.oauth_provider == provider
                and existing_linked_id
                and existing_linked_id != provider_id
            ):
                raise InvalidCredentialsException(
                    f"This email is linked to a different {provider.capitalize()} account"
                )
            existing_email_user.oauth_provider = provider
            existing_email_user.oauth_provider_id = provider_id
            if provider == "linkedin":
                AuthService._ensure_linkedin_community_profile(
                    db, existing_email_user, provider_id, firstname, lastname, picture
                )
            db.commit()
            db.refresh(existing_email_user)
            return AuthService._create_authenticated_session(
                db=db,
                user=existing_email_user,
                ip_address=ip_address,
                user_agent=user_agent,
                device_name=device_name,
                new_user=False,
            )

        tombstone = UserRepository.find_by_email(
            db,
            normalized_email,
            include_deleted=True,
        )
        if tombstone and tombstone.is_deleted:
            raise InvalidCredentialsException(
                "This email is not available for sign-in"
            )

        user = AppUser(
            email=normalized_email,
            firstname=firstname,
            lastname=lastname,
            password=None,
            role=UserRole.USER,
            auth_provider=AuthProvider.OAUTH,
            oauth_provider=provider,
            oauth_provider_id=provider_id,
            active=True,
            email_verified=True,
            profile_complete=False,
        )
        saved_user = UserRepository.save(db, user)
        if provider == "linkedin":
            AuthService._ensure_linkedin_community_profile(
                db, saved_user, provider_id, firstname, lastname, picture
            )
        return AuthService._create_authenticated_session(
            db=db,
            user=saved_user,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name,
            new_user=True,
        )

    @staticmethod
    def _ensure_linkedin_community_profile(
        db: Session,
        user: AppUser,
        provider_id: str,
        firstname: str | None,
        lastname: str | None,
        picture: str | None,
    ) -> None:
        from app.entity.community.community import Community
        from app.repository.community_repository import CommunityRepository

        # Clear conflicting linked_in_id from any other community profile (including soft-deleted ones)
        other_communities = db.query(Community).filter(
            Community.linked_in_id == provider_id,
            Community.app_user_id != user.id
        ).all()
        for other in other_communities:
            other.linked_in_id = None
            db.add(other)
        db.flush()

        community = CommunityRepository.find_any_by_app_user_id(db, user.id)
        if not community:
            community = Community(
                app_user_id=user.id,
                views=0,
                is_approved=False,
            )

        community.linked_in_id = provider_id
        name = f"{firstname or ''} {lastname or ''}".strip()
        if name:
            community.name = name
        if picture:
            community.image_url = picture

        if getattr(community, "is_deleted", False):
            community.is_deleted = False
            community.deleted_at = None
            community.deleted_by = None

        CommunityRepository.save(db, community)

    @staticmethod
    async def forgot_password(
        db: Session,
        email: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict:
        normalized_email = email.lower().strip()
        user = UserRepository.find_by_email(db, normalized_email)

        if not user or not AuthService._is_eligible_for_password_reset(user):
            return {
                "success": True,
                "message": FORGOT_PASSWORD_GENERIC_MESSAGE,
            }

        raw_token = generate_password_reset_token()
        token_hash = hash_reset_token(raw_token)
        expires_at = datetime.now(UTC) + timedelta(
            minutes=PASSWORD_RESET_EXPIRY_MINUTES,
        )

        reset_row = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            requested_ip=ip_address,
            user_agent=user_agent,
        )

        try:
            PasswordResetTokenRepository.delete_unused_for_user(
                db,
                user.id,
                commit=False,
            )
            PasswordResetTokenRepository.add(
                db,
                reset_row,
                commit=False,
            )
            await MailService.send_password_reset_email(
                user.email,
                raw_token,
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "Failed to send password reset email for user_id=%s",
                user.id,
            )

        return {
            "success": True,
            "message": FORGOT_PASSWORD_GENERIC_MESSAGE,
        }

    @staticmethod
    async def reset_password(
        db: Session,
        raw_token: str,
        new_password: str,
    ) -> dict:
        token_hash = hash_reset_token(raw_token)
        stored_token = PasswordResetTokenRepository.find_by_token_hash(
            db,
            token_hash,
        )

        if not stored_token:
            raise InvalidPasswordResetTokenException(
                INVALID_RESET_LINK_MESSAGE,
            )

        now = datetime.now(UTC)

        if stored_token.used_at is not None:
            raise InvalidPasswordResetTokenException(
                INVALID_RESET_LINK_MESSAGE,
            )

        if stored_token.expires_at < now:
            raise InvalidPasswordResetTokenException(
                INVALID_RESET_LINK_MESSAGE,
            )

        user = stored_token.user

        if (
            not user
            or user.is_deleted
            or not user.active
            or not AuthService._is_eligible_for_password_reset(user)
        ):
            raise InvalidPasswordResetTokenException(
                INVALID_RESET_LINK_MESSAGE,
            )

        try:
            user.password = hash_password(new_password)
            user.password_changed_at = now
            if user.auth_provider == AuthProvider.OAUTH:
                user.auth_provider = AuthProvider.EMAIL
            PasswordResetTokenRepository.mark_used(
                db,
                stored_token,
                now,
                commit=False,
            )
            PasswordResetTokenRepository.delete_all_except(
                db,
                user.id,
                stored_token.id,
                commit=False,
            )
            RefreshTokenRepository.revoke_all_user_tokens(
                db,
                user,
                RevocationReason.PASSWORD_CHANGED,
                commit=False,
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "Password reset transaction failed for user_id=%s",
                user.id,
            )
            raise InvalidPasswordResetTokenException(
                INVALID_RESET_LINK_MESSAGE,
            ) from None

        return {
            "success": True,
            "message": "Password reset successful",
        }

    @staticmethod
    async def change_password(
        db: Session,
        user: AppUser,
        current_password: str,
        new_password: str,
    ) -> dict:
        if not user.password:
            raise InvalidCredentialsException(
                "Use set-password to create a password for this account",
            )

        if not verify_password(current_password, user.password):
            raise InvalidCredentialsException("Current password is incorrect")

        now = datetime.now(UTC)

        try:
            user.password = hash_password(new_password)
            user.password_changed_at = now
            PasswordResetTokenRepository.delete_all_for_user(
                db,
                user.id,
                commit=False,
            )
            RefreshTokenRepository.revoke_all_user_tokens(
                db,
                user,
                RevocationReason.PASSWORD_CHANGED,
                commit=False,
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "change_password failed for user_id=%s",
                user.id,
            )
            raise InvalidCredentialsException(
                "Unable to change password",
            ) from None

        return {
            "success": True,
            "message": (
                "Password changed successfully. "
                "Please sign in again with your new password."
            ),
        }

    @staticmethod
    async def set_password(
        db: Session,
        user: AppUser,
        new_password: str,
    ) -> dict:
        if user.password is not None:
            raise InvalidCredentialsException(
                "Password already set. Use Change Password instead."
            )

        now = datetime.now(UTC)

        try:
            user.password = hash_password(new_password)
            user.password_changed_at = now
            PasswordResetTokenRepository.delete_all_for_user(
                db,
                user.id,
                commit=False,
            )
            RefreshTokenRepository.revoke_all_user_tokens(
                db,
                user,
                RevocationReason.PASSWORD_CHANGED,
                commit=False,
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "set_password failed for user_id=%s",
                user.id,
            )
            raise InvalidCredentialsException(
                "Unable to set password",
            ) from None

        return {
            "success": True,
            "message": (
                "Password set successfully. "
                "Please sign in again with your new password."
            ),
        }

    @staticmethod
    def _signup_cache_key(email: str) -> str:
        return f"signup_otp:{email.lower().strip()}"

    @staticmethod
    async def _store_and_send_registration_otp(
        email: str,
        password_hash: str,
    ) -> None:
        raw_code = f"{secrets.randbelow(1_000_000):06d}"
        pending = {
            "otp_hash": hash_otp_code(raw_code),
            "password_hash": password_hash,
            "expires_at": (
                datetime.now(UTC) + timedelta(minutes=OTP_EXPIRY_MINUTES)
            ).isoformat(),
        }
        cache_key = AuthService._signup_cache_key(email)
        await signup_otp_cache.set_json(
            cache_key,
            pending,
            OTP_EXPIRY_MINUTES * 60,
        )
        try:
            await MailService.send_registration_otp_email(email, raw_code)
        except Exception:
            await signup_otp_cache.delete(cache_key)
            logger.exception(
                "send_registration_otp email failed for email=%s",
                email,
            )
            raise AppException(
                "Unable to send verification code. Please try again later.",
                status_code=503,
            ) from None

    @staticmethod
    async def send_otp_for_registration(
        db: Session,
        email: str,
        password: str,
    ) -> dict:
        normalized_email = email.lower().strip()
        existing_user = UserRepository.find_by_email(
            db,
            normalized_email,
            include_deleted=True,
        )
        if (
            existing_user
            and not existing_user.is_deleted
            and existing_user.email_verified
        ):
            raise EmailAlreadyExistsException(
                "This email is already registered. Sign in or use Forgot Password."
            )

        await AuthService._store_and_send_registration_otp(
            normalized_email,
            hash_password(password),
        )
        return {
            "success": True,
            "message": REGISTER_OTP_SENT_MESSAGE,
        }

    @staticmethod
    async def resend_otp_for_registration(email: str) -> dict:
        normalized_email = email.lower().strip()
        cache_key = AuthService._signup_cache_key(normalized_email)
        pending = await signup_otp_cache.get_json(cache_key)
        if not pending:
            return {
                "success": True,
                "message": REGISTER_OTP_RESENT_MESSAGE,
            }

        await AuthService._store_and_send_registration_otp(
            normalized_email,
            pending["password_hash"],
        )
        return {
            "success": True,
            "message": REGISTER_OTP_RESENT_MESSAGE,
        }

    @staticmethod
    async def verify_otp_and_register(
        db: Session,
        email: str,
        otp_code: str,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
    ) -> dict:
        normalized_email = email.lower().strip()
        cache_key = AuthService._signup_cache_key(normalized_email)
        pending = await signup_otp_cache.get_json(cache_key)

        if not pending:
            raise InvalidCredentialsException("Invalid email or code")

        expires_at = datetime.fromisoformat(pending["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        if expires_at < datetime.now(UTC):
            await signup_otp_cache.delete(cache_key)
            raise InvalidCredentialsException("Code has expired")

        if pending["otp_hash"] != hash_otp_code(otp_code.strip()):
            raise InvalidCredentialsException("Invalid email or code")

        password_hash = pending["password_hash"]
        await signup_otp_cache.delete(cache_key)

        existing_user = UserRepository.find_by_email(
            db,
            normalized_email,
            include_deleted=True,
        )

        if existing_user:
            if existing_user.is_deleted:
                RefreshTokenRepository.revoke_all_user_tokens(
                    db,
                    existing_user,
                    RevocationReason.LOGOUT,
                )
                existing_user.is_deleted = False
                existing_user.deleted_at = None
                existing_user.deleted_by = None
                existing_user.password = password_hash
                existing_user.role = UserRole.USER
                existing_user.auth_provider = AuthProvider.EMAIL
                existing_user.oauth_provider = None
                existing_user.oauth_provider_id = None
                existing_user.otp = None
                existing_user.otp_expiry = None
                existing_user.active = True
                existing_user.email_verified = True
                existing_user.verification_token = None
                existing_user.verification_token_expiry = None
                existing_user.profile_complete = False
                db.commit()
                db.refresh(existing_user)
                AuthService._assert_user_may_authenticate(existing_user)
                return AuthService._create_authenticated_session(
                    db,
                    existing_user,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    device_name=device_name,
                    new_user=True,
                )

            if existing_user.email_verified:
                raise EmailAlreadyExistsException(
                    "This email is already registered. Sign in or use Forgot Password."
                )

            existing_user.password = password_hash
            existing_user.auth_provider = AuthProvider.EMAIL
            existing_user.email_verified = True
            existing_user.verification_token = None
            existing_user.verification_token_expiry = None
            existing_user.otp = None
            existing_user.otp_expiry = None
            db.commit()
            db.refresh(existing_user)
            AuthService._assert_user_may_authenticate(existing_user)
            return AuthService._create_authenticated_session(
                db,
                existing_user,
                ip_address=ip_address,
                user_agent=user_agent,
                device_name=device_name,
                new_user=not existing_user.profile_complete,
            )

        user = AppUser(
            email=normalized_email,
            password=password_hash,
            role=UserRole.USER,
            auth_provider=AuthProvider.EMAIL,
            active=True,
            email_verified=True,
            verification_token=None,
            verification_token_expiry=None,
            profile_complete=False,
        )
        saved_user = UserRepository.save(db, user)
        return AuthService._create_authenticated_session(
            db,
            saved_user,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name,
            new_user=True,
        )

    @staticmethod
    async def send_otp_for_login(db: Session, email: str) -> dict:
        normalized_email = email.lower().strip()
        user = UserRepository.find_by_email(db, normalized_email)

        if user and user.active and not user.is_deleted:
            raw_code = f"{secrets.randbelow(1_000_000):06d}"
            try:
                await MailService.send_otp_login_email(user.email, raw_code)
            except Exception:
                logger.exception(
                    "send_otp_login email failed for email=%s",
                    normalized_email,
                )
                raise AppException(
                    "Unable to send login code. Please try again later.",
                    status_code=503,
                ) from None

            user.otp = hash_otp_code(raw_code)
            user.otp_expiry = datetime.now(UTC) + timedelta(
                minutes=OTP_EXPIRY_MINUTES
            )
            try:
                db.commit()
            except Exception:
                db.rollback()
                logger.exception(
                    "send_otp_for_login commit failed for email=%s",
                    normalized_email,
                )
                raise AppException(
                    "Unable to send login code. Please try again later.",
                    status_code=503,
                ) from None

        return {
            "success": True,
            "message": OTP_GENERIC_MESSAGE,
        }

    @staticmethod
    async def verify_otp_and_login(
        db: Session,
        email: str,
        otp_code: str,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
    ) -> dict:
        normalized_email = email.lower().strip()
        user = UserRepository.find_by_email(db, normalized_email)

        if not user or not user.otp or not user.otp_expiry:
            raise InvalidCredentialsException("Invalid email or code")

        if user.otp_expiry < datetime.now(UTC):
            raise InvalidCredentialsException("Code has expired")

        if user.otp != hash_otp_code(otp_code.strip()):
            raise InvalidCredentialsException("Invalid email or code")

        AuthService._assert_user_may_authenticate(user)

        if not user.email_verified:
            user.email_verified = True

        user.otp = None
        user.otp_expiry = None
        db.commit()

        return AuthService._create_authenticated_session(
            db,
            user,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name,
            new_user=not user.profile_complete,
        )

    @staticmethod
    async def complete_profile(
        db: Session,
        email: str,
        body: CompleteProfileRequest,
    ) -> dict:
        from app.service.profile.profile_service import ProfileService

        user = UserRepository.find_by_email(db, email.lower().strip())
        if not user:
            raise InvalidCredentialsException("User not found")

        return await ProfileService.complete_profile(db, user, body)
