import logging
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


_BACKEND_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_BACKEND_ENV_FILE), extra="ignore")
    DATABASE_URL: str
    # Used when DATABASE_URL points at a local SSH tunnel that is not running.
    DATABASE_URL_DIRECT: str = ""

    DB_POOL_SIZE: int = 3

    DB_MAX_OVERFLOW: int = 2

    DB_POOL_RECYCLE_SECONDS: int = 300

    # Disable auction timer + domain retry scheduler (saves DB connections in local dev).
    BACKGROUND_JOBS_ENABLED: bool = True

    TEST_DATABASE_URL: str = ""

    JWT_SECRET_KEY: str

    JWT_ALGORITHM: str

    JWT_ACCESS_TOKEN_EXPIRE_MS: int

    JWT_REFRESH_TOKEN_EXPIRE_MS: int

    JWT_REFRESH_TOKEN_PEPPER: str

    JWT_REFRESH_TOKEN_PEPPER_KID: str

    MAIL_USERNAME: str

    MAIL_PASSWORD: str

    MAIL_FROM: str

    MAIL_PORT: int

    MAIL_SERVER: str

    MAIL_STARTTLS: bool

    MAIL_SSL_TLS: bool

    MAIL_VALIDATE_CERTS: bool = True

    MAIL_FROM_NAME: str

    # Display From for transactional mail (e.g. no-reply@hubregistrar.com). Replies go to MAIL_REPLY_TO.
    MAIL_REPLY_TO: str = "support@deltapreneur.com"

    # Optional From for domain registration lifecycle emails (active / DNS / RAA).
    # Empty = use MAIL_FROM. Example: domains@hubregistrar.com (requires SMTP send-as / Workspace).
    MAIL_DOMAINS_FROM: str = ""
    # Optional SMTP login for domain emails. Empty = reuse MAIL_USERNAME / MAIL_PASSWORD.
    MAIL_DOMAINS_USERNAME: str = ""
    MAIL_DOMAINS_PASSWORD: str = ""

    # Join CoBrother form notifications (defaults to MAIL_REPLY_TO)
    BECOBROTHER_APPLICATION_RECIPIENT: str = ""

    BACKEND_BASE_URL: str = ""

    # Storage backend: auto | supabase | aws
    # auto — supabase when SUPABASE_URL is set, else aws when AWS_BUCKET_NAME + keys are set
    STORAGE_BACKEND: str = "auto"

    # Supabase Storage (S3-compatible API — Storage → S3 Connection in dashboard)
    SUPABASE_URL: str = ""
    SUPABASE_STORAGE_BUCKET: str = ""
    SUPABASE_S3_ACCESS_KEY_ID: str = ""
    SUPABASE_S3_SECRET_ACCESS_KEY: str = ""
    SUPABASE_S3_REGION: str = "ap-south-1"
    # Optional override; default derived from SUPABASE_URL
    SUPABASE_S3_ENDPOINT: str = ""

    # Native AWS S3 (EC2 / RDS migration target)
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "ap-south-1"
    AWS_BUCKET_NAME: str = ""
    # Optional CloudFront or custom public base, e.g. https://d123.cloudfront.net
    AWS_S3_PUBLIC_BASE_URL: str = ""
    # Optional — LocalStack/MinIO only; omit for real AWS S3
    AWS_S3_ENDPOINT_URL: str = ""

    FRONTEND_BASE_URL: str = ""

    GOOGLE_CLIENT_ID: str = ""

    LINKEDIN_CLIENT_ID: str | None = None

    LINKEDIN_CLIENT_SECRET: str | None = None

    LINKEDIN_REDIRECT_URI: str | None = None

    # Optional additive HubRegistrar LinkedIn callback. Never replace
    # LINKEDIN_REDIRECT_URI. When unset, Hub API hosts derive
    # https://{host}/api/v1/community/linkedin/callback.
    LINKEDIN_REDIRECT_URI_HUBREGISTRAR: str = ""

    GOOGLE_CLIENT_SECRET: str = ""

    GOOGLE_OAUTH_REDIRECT_URI: str = ""

    GOOGLE_OAUTH_SUCCESS_REDIRECT: str = ""

    # Optional additive HubRegistrar Google callback. Unset until DNS + Console
    # ADD of this URI. Never replace GOOGLE_OAUTH_REDIRECT_URI.
    GOOGLE_OAUTH_REDIRECT_URI_HUBREGISTRAR: str = ""

    FACEBOOK_CLIENT_ID: str = ""
    FACEBOOK_CLIENT_SECRET: str = ""
    FACEBOOK_REDIRECT_URI: str = ""

    INSTAGRAM_CLIENT_ID: str = ""
    INSTAGRAM_CLIENT_SECRET: str = ""
    INSTAGRAM_REDIRECT_URI: str = ""

    TRUST_PROXY_HEADERS: bool = False

    ENVIRONMENT: str = "development"

    CORS_ALLOW_ORIGINS: str = ""
    # Optional: e.g. https://co-brother-frontend(-[a-zA-Z0-9-]+)?\.vercel\.app
    CORS_ALLOW_ORIGIN_REGEX: str = ""

    JSON_LOGGING: bool = False

    EXPOSE_METRICS: bool = False

    # Optional: .example.com when API and SPA share a parent domain
    AUTH_COOKIE_DOMAIN: str = ""

    # lax (default) or none (cross-site; requires Secure cookies)
    AUTH_COOKIE_SAMESITE: str = "lax"

    # Optional dev override when RDAP returns privacy/redacted WHOIS email
    DOMAIN_VERIFICATION_WHOIS_EMAIL_OVERRIDE: str = ""
    # Set true on Render when SMTP is unreliable; DNS/META_TAG still work
    DOMAIN_VERIFICATION_DISABLE_WHOIS_EMAIL: bool = False
    REQUIRE_DOMAIN_VERIFICATION_BEFORE_PURCHASE: bool = True
    REQUIRE_TECHNOLOGY_VERIFICATION_BEFORE_PURCHASE: bool = True

    # Domain marketplace transfer & escrow
    AUTH_CODE_ENCRYPTION_KEY: str = ""
    DOMAIN_TRANSFER_SELLER_DEADLINE_HOURS: int = 36
    DOMAIN_TRANSFER_BUYER_DEADLINE_DAYS: int = 7
    DOMAIN_TRANSFER_WHOIS_POLL_HOURS: int = 6
    DOMAIN_TRANSFER_OPS_BATCH_LIMIT: int = 50
    ADMIN_TRANSFER_ALERT_EMAIL: str = ""

    # Razorpay (payments) — set RAZORPAY_KEY_ID directly or use sandbox/live pairs below
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""
    RAZORPAY_SANDBOX_KEY_ID: str = ""
    RAZORPAY_SANDBOX_KEY_SECRET: str = ""
    RAZORPAY_LIVE_KEY_ID: str = ""
    RAZORPAY_LIVE_KEY_SECRET: str = ""
    RAZORPAY_LIVE_WEBHOOK_SECRET: str = ""

    # Bro chatbot provider metadata
    CHAT_AI_PROVIDER: str = ""
    OPENROUTER_MODEL: str = "openai/gpt-4.1-mini"
    OPENROUTER_FALLBACK_MODELS: str = ""
    OPENROUTER_SITE_URL: str = "https://co-brother-frontend.vercel.app"
    OPENROUTER_APP_NAME: str = "Bro"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    AI_REQUEST_TIMEOUT_SECONDS: int = 45
    AI_STREAM_TOKEN_BATCH_MS: int = 40

    # GSTIN (venture listings) — sheet.gstincheck.co.in; use sandbox when no API key in dev
    GSTIN_API_KEY: str = ""
    GSTIN_API_SANDBOX: bool = False

    # Active registrar: openprovider
    DOMAIN_REGISTRAR: str = "openprovider"

    # OpenProvider (domain availability check + registration)
    # Sandbox: https://cp.sandbox.openprovider.nl — API http://api.sandbox.openprovider.nl:8480
    # Production: https://cp.openprovider.eu — API https://api.openprovider.eu
    OPENPROVIDER_USE_SANDBOX: bool = False
    OPENPROVIDER_USERNAME: str = ""
    OPENPROVIDER_PASSWORD: str = ""
    OPENPROVIDER_API_BASE_URL: str = "https://api.openprovider.eu"
    OPENPROVIDER_CLIENT_IP: str = "127.0.0.1"
    # Force IPv4 for OpenProvider API calls. Some hosts egress over IPv6 while
    # the API IP whitelist only lists an IPv4 address, causing code=10005
    # "Access denied" on every data call (login still works). Set False if the
    # whitelist is IPv6 or you intentionally need IPv6 egress.
    OPENPROVIDER_FORCE_IPV4: bool = True
    # Vanity HubRegistrar NS (glue + OP NS group). CoBrother and legacy
    # openprovider.* hosts remain valid for existing domains via
    # platform-nameserver detection in the OP client. Production still
    # overrides this from .env until that env is changed separately.
    OPENPROVIDER_DEFAULT_NAMESERVERS: str = (
        "ns1.hubregistrar.com,ns2.hubregistrar.com,ns3.hubregistrar.com"
    )
    OPENPROVIDER_WEBHOOK_SECRET: str = ""
    # Optional legacy FX bridge: historically OpenProvider API reseller INR could
    # understate cp panel display for USD/EUR/GBP products. Default is 1.0 (off) so
    # Storefront/Homepage/Cart show the API reseller price + admin commission only.
    # Set >1.0 only if you intentionally need to uplift API INR toward panel FX.
    OPENPROVIDER_PANEL_INR_FACTOR: float = 1.0
    # ResellerClub / LogicBoxes registrar (alternative to OpenProvider).
    DOMAIN_PROVIDER: str = ""
    RESELLERCLUB_ENABLED: bool = False
    RESELLERCLUB_ENV: str = "live"
    RESELLERCLUB_API_BASE_URL: str = ""
    RESELLERCLUB_DOMAINCHECK_BASE_URL: str = ""
    RESELLERCLUB_RESELLER_ID: str = ""
    RESELLERCLUB_API_KEY: str = ""
    RESELLERCLUB_AUTH_USERID: str = ""
    RESELLERCLUB_SANDBOX_RESELLER_ID: str = ""
    RESELLERCLUB_SANDBOX_API_KEY: str = ""
    RESELLERCLUB_LIVE_RESELLER_ID: str = ""
    RESELLERCLUB_LIVE_API_KEY: str = ""
    RESELLERCLUB_DEFAULT_NAMESERVERS: str = ""
    RESELLERCLUB_LIVE_DEFAULT_NAMESERVERS: str = ""
    RESELLERCLUB_SANDBOX_DEFAULT_NAMESERVERS: str = ""
    RESELLERCLUB_DEFAULT_NS1: str = ""
    RESELLERCLUB_DEFAULT_NS2: str = ""
    RESELLERCLUB_DEFAULT_CUSTOMER_ID: str = ""
    RESELLERCLUB_DEFAULT_CONTACT_ID: str = ""
    RESELLERCLUB_FETCH_NAMESERVERS_FROM_API: bool = True
    RESELLERCLUB_INVOICE_OPTION: str = "NoInvoice"
    # ResellPortal integration settings
    RESELLPORTAL_BASE_URL: str = "https://panel.resellportal.com/wp-json/resellportal/v1"
    RESELLPORTAL_API_KEY: str = ""
    RESELLPORTAL_API_SECRET: str = ""
    RESELLPORTAL_TEST_MODE: bool = True
    RESELLPORTAL_ALLOW_LIVE: bool = False
    # Technology subscription provisioning retry worker. Disabled by default:
    # the worker must be validated in test mode before it is enabled.
    TECH_SUBSCRIPTION_RETRY_ENABLED: bool = False
    # Maximum automatic provisioning attempts (initial + retries) per subscription.
    TECH_SUBSCRIPTION_MAX_RETRIES: int = 5

    DOMAIN_STOREFRONT_DEMO_FALLBACK: bool = False
    DOMAIN_STOREFRONT_RENEWAL_FALLBACK_UNIT_INR: float = 100.0
    DOMAIN_REGISTRATION_PENDING_ALERT_HOURS: float = 6.0
    # After this many minutes in REGISTRATION_PENDING without becoming ACTIVE,
    # background recovery marks PROVISION_FAILED (after one final reconcile attempt).
    DOMAIN_REGISTRATION_PENDING_TIMEOUT_MINUTES: float = 10.0
    DOMAIN_REGISTRATION_RECONCILE_BATCH_LIMIT: int = 25
    DOMAIN_REGISTRATION_MAX_PROVISION_ATTEMPTS: int = 5
    # Domain registration GST (charged on Razorpay checkout, ex-GST base from registrar API)
    DOMAIN_GST_ENABLED: bool = True
    DOMAIN_GST_RATE: float = 18.0
    DOMAIN_PRICE_GST_INCLUSIVE: bool = False
    COBROTHER_GSTIN: str = "29DXMPA9959L2ZF"
    COBROTHER_BILLING_LEGAL_NAME: str = "Aultum International"

    # AI Domains (OpenRouter)
    AI_PROVIDER: str = "openrouter"
    AI_MODEL: str = ""
    AI_DOMAIN_MAX_TOKENS: int = 2000
    AI_TIMEOUT_SECONDS: float = 30.0
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    AI_DOMAIN_CACHE_TTL_SECONDS: int = 86400
    AI_DOMAIN_GENERATION_TARGET_SECONDS: float = 4.0
    AI_DOMAIN_LIVE_AVAILABILITY_ENABLED: bool = False
    AI_DOMAIN_RATE_LIMIT_GUEST_DAILY: int = 5
    AI_DOMAIN_RATE_LIMIT_AUTH_DAILY: int = 25
    REDIS_URL: str = ""

    # Cloudflare Turnstile (bot protection on auth/forms)
    TURNSTILE_SITE_KEY: str = ""
    TURNSTILE_SECRET_KEY: str = ""

    # Share & Earn anti-abuse limits (referral tracking / rewards)
    REFERRAL_TRACK_LIMIT_WINDOW_SECONDS: int = 3600
    REFERRAL_TRACK_LIMIT_PER_IDENTITY: int = 30
    REFERRAL_TRACK_LIMIT_PER_TOKEN: int = 10
    REFERRAL_REWARD_LIMIT_PER_REFERRER_DAILY: int = 200

    _OPENPROVIDER_PRODUCTION_API_BASE: str = "https://api.openprovider.eu"
    _OPENPROVIDER_SANDBOX_API_BASE: str = "http://api.sandbox.openprovider.nl:8480"

    def resolved_razorpay_key_id(self) -> str:
        """Active Razorpay key id, preferring explicit sandbox/live pairs.

        Resolution order:
        1. RAZORPAY_SANDBOX_KEY_ID (when present)
        2. RAZORPAY_LIVE_KEY_ID (when present)
        3. RAZORPAY_KEY_ID (generic fallback)
        """
        return (
            self.RAZORPAY_SANDBOX_KEY_ID.strip()
            or self.RAZORPAY_LIVE_KEY_ID.strip()
            or self.RAZORPAY_KEY_ID.strip()
        )

    def resolved_razorpay_key_secret(self) -> str:
        """Active Razorpay key secret, matching the resolved key id.

        Uses the same environment family as the resolved key id so the
        key/secret pair always belongs to the same Razorpay account.
        """
        sandbox_id = self.RAZORPAY_SANDBOX_KEY_ID.strip()
        live_id = self.RAZORPAY_LIVE_KEY_ID.strip()
        resolved_id = sandbox_id or live_id or self.RAZORPAY_KEY_ID.strip()

        if resolved_id == sandbox_id:
            return self.RAZORPAY_SANDBOX_KEY_SECRET.strip() or self.RAZORPAY_KEY_SECRET.strip()
        if resolved_id == live_id:
            return self.RAZORPAY_LIVE_KEY_SECRET.strip() or self.RAZORPAY_KEY_SECRET.strip()
        return self.RAZORPAY_KEY_SECRET.strip()

    def resolved_razorpay_webhook_secret(self) -> str:
        return self.RAZORPAY_WEBHOOK_SECRET.strip()

    def openprovider_configured(self) -> bool:
        return bool(self.OPENPROVIDER_USERNAME.strip() and self.OPENPROVIDER_PASSWORD.strip())

    def openprovider_use_sandbox(self) -> bool:
        return bool(self.OPENPROVIDER_USE_SANDBOX)

    def resolved_openprovider_api_base_url(self) -> str:
        """Production or sandbox API origin (no trailing slash).

        When sandbox is off, never keep a leftover sandbox host in
        OPENPROVIDER_API_BASE_URL — that silently left live mode on sandbox
        prices (e.g. ₹1265 vs live panel ₹1201).
        """
        custom = self.OPENPROVIDER_API_BASE_URL.strip().rstrip("/")
        sandbox_hosts = (
            "api.sandbox.openprovider.nl",
            "sandbox.openprovider.nl",
        )
        custom_is_sandbox = any(h in custom.lower() for h in sandbox_hosts) if custom else False

        if self.openprovider_use_sandbox():
            if custom and custom != self._OPENPROVIDER_PRODUCTION_API_BASE:
                return custom
            return self._OPENPROVIDER_SANDBOX_API_BASE

        if custom and not custom_is_sandbox:
            return custom
        return self._OPENPROVIDER_PRODUCTION_API_BASE

    def domain_storefront_demo_fallback(self) -> bool:
        """Simulated pricing/registration when fallback explicitly enabled or registrar unconfigured."""
        if self.DOMAIN_STOREFRONT_DEMO_FALLBACK:
            return True
        if self.domain_registrar() == "resellerclub" and not self.resellerclub_configured():
            return True
        if self.domain_registrar() == "openprovider" and not self.openprovider_configured():
            return True
        return False

    # ── ResellerClub registrar resolution ──────────────────────────────────
    def domain_registrar(self) -> str:
        """Active registrar name. DOMAIN_PROVIDER wins when explicitly set."""
        provider = (self.DOMAIN_PROVIDER or "").strip().lower()
        if provider:
            return provider
        return "openprovider"

    def resellerclub_use_sandbox(self) -> bool:
        return str(self.RESELLERCLUB_ENV or "live").strip().lower() == "sandbox"

    def _resellerclub_custom_api_base(self) -> str:
        return (self.RESELLERCLUB_API_BASE_URL or "").strip().rstrip("/")

    def _resellerclub_host_matches_env(self, custom_base: str, *, sandbox: bool) -> bool:
        base = (custom_base or "").strip().lower()
        if not base:
            return False
        if sandbox:
            return "test.httpapi" in base
        return "test.httpapi" not in base and "httpapi.com" in base

    def resolved_resellerclub_api_base(self) -> str:
        """Resolved ResellerClub API origin (no trailing slash).

        Sandbox always uses https://test.httpapi.com and ignores a conflicting
        live RESELLERCLUB_API_BASE_URL override. Live uses the custom base or
        https://httpapi.com.
        """
        if self.resellerclub_use_sandbox():
            custom = self._resellerclub_custom_api_base()
            if custom and self._resellerclub_host_matches_env(custom, sandbox=True):
                return custom
            return "https://test.httpapi.com"
        custom = self._resellerclub_custom_api_base()
        if custom:
            return custom
        return "https://httpapi.com"

    def resolved_resellerclub_domaincheck_base(self) -> str:
        """Resolved ResellerClub availability (domaincheck) origin.

        Sandbox → https://test.httpapi.com; live → custom
        RESELLERCLUB_DOMAINCHECK_BASE_URL or https://domaincheck.httpapi.com.
        """
        if self.resellerclub_use_sandbox():
            return "https://test.httpapi.com"
        custom = (self.RESELLERCLUB_DOMAINCHECK_BASE_URL or "").strip().rstrip("/")
        if custom:
            return custom
        return "https://domaincheck.httpapi.com"

    def resellerclub_reseller_id(self) -> str:
        """Active reseller id, preferring the paired (sandbox/live) credential."""
        if self.resellerclub_use_sandbox():
            return (
                self.RESELLERCLUB_SANDBOX_RESELLER_ID.strip()
                or self.RESELLERCLUB_RESELLER_ID.strip()
                or self.RESELLERCLUB_AUTH_USERID.strip()
            )
        return (
            self.RESELLERCLUB_LIVE_RESELLER_ID.strip()
            or self.RESELLERCLUB_RESELLER_ID.strip()
            or self.RESELLERCLUB_AUTH_USERID.strip()
        )

    def resellerclub_api_key(self) -> str:
        """Active API key, preferring the paired (sandbox/live) credential."""
        if self.resellerclub_use_sandbox():
            return self.RESELLERCLUB_SANDBOX_API_KEY.strip() or self.RESELLERCLUB_API_KEY.strip()
        return self.RESELLERCLUB_LIVE_API_KEY.strip() or self.RESELLERCLUB_API_KEY.strip()

    def resellerclub_configured(self) -> bool:
        if not self.RESELLERCLUB_ENABLED:
            return False
        return bool(self.resellerclub_reseller_id() and self.resellerclub_api_key())

    def resellerclub_control_panel_url(self) -> str:
        if self.resellerclub_use_sandbox():
            return "https://cp.resellerclub.com"
        return "https://cp.resellerclub.com"

    def resolved_resellerclub_default_nameservers(self) -> list[str]:
        """Default nameservers for the active RESELLERCLUB_ENV.

        Sandbox prefers RESELLERCLUB_SANDBOX_DEFAULT_NAMESERVERS then
        RESELLERCLUB_DEFAULT_NAMESERVERS, falling back to demo onlyfordemo.net
        hosts. Live prefers RESELLERCLUB_LIVE_DEFAULT_NAMESERVERS then
        RESELLERCLUB_DEFAULT_NAMESERVERS, with no demo fallback.
        """
        if self.resellerclub_use_sandbox():
            raw = (
                self.RESELLERCLUB_SANDBOX_DEFAULT_NAMESERVERS.strip()
                or self.RESELLERCLUB_DEFAULT_NAMESERVERS.strip()
            )
            if raw:
                return [ns.strip() for ns in raw.split(",") if ns.strip()]
            return ["ns1.onlyfordemo.net", "ns2.onlyfordemo.net"]
        raw = (
            self.RESELLERCLUB_LIVE_DEFAULT_NAMESERVERS.strip()
            or self.RESELLERCLUB_DEFAULT_NAMESERVERS.strip()
        )
        if not raw:
            return []
        return [ns.strip() for ns in raw.split(",") if ns.strip()]

    def resellerclub_runtime_profile(self) -> dict[str, Any]:
        """Profile dict consumed by ResellerClub runtime validation."""
        return {
            "sandbox": self.resellerclub_use_sandbox(),
            "configured": self.resellerclub_configured(),
            "apiBaseUrl": self.resolved_resellerclub_api_base(),
            "domaincheckBaseUrl": self.resolved_resellerclub_domaincheck_base(),
            "resellerId": self.resellerclub_reseller_id(),
            "enabled": self.RESELLERCLUB_ENABLED,
        }

    def resellportal_configured(self) -> bool:
        """Returns True only when API Key and API Secret are provided."""
        return bool((self.RESELLPORTAL_API_KEY or "").strip() and (self.RESELLPORTAL_API_SECRET or "").strip())

    def resellportal_test_mode(self) -> bool:
        """Returns True if test_mode should be attached to POST/DELETE calls."""
        if self.RESELLPORTAL_ALLOW_LIVE and not self.RESELLPORTAL_TEST_MODE:
            return False
        return True

    def gstin_sandbox_enabled(self) -> bool:
        """Format-only mock verification — never used in production."""
        if self.ENVIRONMENT == "production":
            return False
        if self.GSTIN_API_SANDBOX:
            return True
        if self.ENVIRONMENT == "development" and not self.GSTIN_API_KEY.strip():
            return True
        return False

    def gstin_live_configured(self) -> bool:
        return bool(self.GSTIN_API_KEY.strip()) and not self.gstin_sandbox_enabled()

    def storage_backend(self) -> str:
        """Resolved storage provider: ``supabase`` or ``aws``."""
        explicit = (self.STORAGE_BACKEND or "auto").strip().lower()
        if explicit in ("supabase", "aws"):
            return explicit
        # auto: keep Supabase when project URL is present (production default).
        if self.SUPABASE_URL.strip():
            return "supabase"
        if self.AWS_BUCKET_NAME.strip():
            return "aws"
        return "supabase"

    def storage_uses_supabase(self) -> bool:
        return self.storage_backend() == "supabase"

    def storage_uses_aws(self) -> bool:
        return self.storage_backend() == "aws"

    def storage_configured(self) -> bool:
        if self.storage_uses_supabase():
            return bool(
                self.SUPABASE_URL.strip()
                and self.resolved_storage_bucket().strip()
                and self.resolved_storage_access_key_id().strip()
                and self.resolved_storage_secret_access_key().strip()
            )
        return bool(
            self.AWS_BUCKET_NAME.strip()
            and self.AWS_ACCESS_KEY_ID.strip()
            and self.AWS_SECRET_ACCESS_KEY.strip()
            and self.resolved_storage_region().strip()
        )

    def resolved_storage_bucket(self) -> str:
        if self.storage_uses_aws():
            return self.AWS_BUCKET_NAME.strip()
        return self.SUPABASE_STORAGE_BUCKET.strip()

    def resolved_storage_access_key_id(self) -> str:
        if self.storage_uses_aws():
            return self.AWS_ACCESS_KEY_ID.strip()
        return self.SUPABASE_S3_ACCESS_KEY_ID.strip()

    def resolved_storage_secret_access_key(self) -> str:
        if self.storage_uses_aws():
            return self.AWS_SECRET_ACCESS_KEY.strip()
        return self.SUPABASE_S3_SECRET_ACCESS_KEY.strip()

    def resolved_storage_region(self) -> str:
        if self.storage_uses_aws():
            region = (self.AWS_REGION or "ap-south-1").strip()
            return region or "ap-south-1"
        region = (self.SUPABASE_S3_REGION or "ap-south-1").strip()
        return region or "ap-south-1"

    def database_host_label(self) -> str:
        """Short label for health checks (no credentials)."""
        from urllib.parse import urlparse

        try:
            host = urlparse(self.resolved_database_url()).hostname or "unknown"
        except Exception:
            return "unknown"
        if "pooler.supabase.com" in host:
            return "supabase-pooler"
        if host.endswith(".rds.amazonaws.com"):
            return "aws-rds"
        return host

    def mail_configured(self) -> bool:
        return bool(
            (self.MAIL_USERNAME or "").strip()
            and (self.MAIL_PASSWORD or "").strip()
            and (self.MAIL_SERVER or "").strip()
            and (self.MAIL_FROM or "").strip()
        )

    def turnstile_enabled(self) -> bool:
        return bool(self.TURNSTILE_SECRET_KEY.strip())

    def resolved_mail_reply_to(self) -> str:
        return (self.MAIL_REPLY_TO or "support@deltapreneur.com").strip()

    def resolved_mail_domains_from(self) -> str:
        """From address for domain registration lifecycle emails."""
        explicit = (self.MAIL_DOMAINS_FROM or "").strip()
        if explicit:
            return explicit
        return (self.MAIL_FROM or "").strip()

    def resolved_mail_domains_username(self) -> str:
        explicit = (self.MAIL_DOMAINS_USERNAME or "").strip()
        if explicit:
            return explicit
        # Prefer authenticating as the domains From mailbox when set.
        domains_from = (self.MAIL_DOMAINS_FROM or "").strip()
        if domains_from:
            return domains_from
        return (self.MAIL_USERNAME or "").strip()

    def resolved_mail_domains_password(self) -> str:
        explicit = (self.MAIL_DOMAINS_PASSWORD or "").strip()
        if explicit:
            return explicit.replace(" ", "")
        return (self.MAIL_PASSWORD or "").replace(" ", "").strip()

    def resolved_mail_support_inbox(self) -> str:
        """Inbound address for feedback, applications, and internal alerts."""
        explicit = (self.BECOBROTHER_APPLICATION_RECIPIENT or "").strip()
        if explicit:
            return explicit
        return self.resolved_mail_reply_to()

    def resolved_becobrother_application_recipient(self) -> str:
        return self.resolved_mail_support_inbox()

    def domain_verification_whois_email_enabled(self) -> bool:
        if self.DOMAIN_VERIFICATION_DISABLE_WHOIS_EMAIL:
            return False
        if not self.mail_configured():
            return False
        return True

    def model_post_init(self, __context):
        mail_password = (self.MAIL_PASSWORD or "").replace(" ", "").strip()
        if mail_password != (self.MAIL_PASSWORD or ""):
            object.__setattr__(self, "MAIL_PASSWORD", mail_password)

        backend = (self.STORAGE_BACKEND or "auto").strip().lower()
        # Legacy: Supabase S3 keys were sometimes stored under AWS_* names.
        if backend != "aws":
            if not self.SUPABASE_S3_ACCESS_KEY_ID.strip() and self.AWS_ACCESS_KEY_ID.strip():
                object.__setattr__(self, "SUPABASE_S3_ACCESS_KEY_ID", self.AWS_ACCESS_KEY_ID)
            if (
                not self.SUPABASE_S3_SECRET_ACCESS_KEY.strip()
                and self.AWS_SECRET_ACCESS_KEY.strip()
            ):
                object.__setattr__(
                    self, "SUPABASE_S3_SECRET_ACCESS_KEY", self.AWS_SECRET_ACCESS_KEY
                )
            if not self.SUPABASE_STORAGE_BUCKET.strip() and self.AWS_BUCKET_NAME.strip():
                object.__setattr__(self, "SUPABASE_STORAGE_BUCKET", self.AWS_BUCKET_NAME)
            if self.AWS_REGION.strip() and self.SUPABASE_S3_REGION == "ap-south-1":
                object.__setattr__(self, "SUPABASE_S3_REGION", self.AWS_REGION)

        if len(self.JWT_REFRESH_TOKEN_PEPPER) < 32:
            raise ValueError(
                "JWT_REFRESH_TOKEN_PEPPER must be at least 32 characters"
            )
        if not self.JWT_REFRESH_TOKEN_PEPPER_KID.strip():
            raise ValueError(
                "JWT_REFRESH_TOKEN_PEPPER_KID must be a non-empty identifier"
            )
        samesite = (self.AUTH_COOKIE_SAMESITE or "lax").strip().lower()
        if samesite not in ("lax", "none", "strict"):
            raise ValueError(
                "AUTH_COOKIE_SAMESITE must be lax, strict, or none"
            )
        object.__setattr__(self, "AUTH_COOKIE_SAMESITE", samesite)
        if samesite == "none" and self.ENVIRONMENT == "production":
            if not self.AUTH_COOKIE_DOMAIN.strip():
                raise ValueError(
                    "AUTH_COOKIE_DOMAIN is required when "
                    "AUTH_COOKIE_SAMESITE=none in production"
                )

    @staticmethod
    def _normalize_cors_origin(origin: str) -> str:
        cleaned = origin.strip().strip('"').strip("'")
        return cleaned.rstrip("/")

    _BRAND_SPA_ORIGINS = (
        "https://deltapreneur.com",
        "https://www.deltapreneur.com",
    )
    _BRAND_SPA_ORIGIN_REGEX = r"^https://([a-z0-9-]+\.)*deltapreneur\.com$"

    def _is_production_env(self) -> bool:
        return (self.ENVIRONMENT or "").strip().lower() == "production"

    def resolved_cors_origins(self) -> list[str]:
        raw = (self.CORS_ALLOW_ORIGINS or "").strip()
        seen: set[str] = set()
        origins: list[str] = []
        for part in raw.split(","):
            normalized = self._normalize_cors_origin(part)
            if normalized and normalized not in seen:
                seen.add(normalized)
                origins.append(normalized)
        # Always trust configured app URLs even if CORS_ALLOW_ORIGINS on the server is stale.
        for url in (self.FRONTEND_BASE_URL, self.BACKEND_BASE_URL):
            normalized = self._normalize_cors_origin(url)
            if normalized and normalized not in seen:
                seen.add(normalized)
                origins.append(normalized)
        if (self.ENVIRONMENT or "").strip().lower() == "development":
            for origin in (
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:8000",
                "http://127.0.0.1:8000",
                "http://localhost:8080",
                "http://127.0.0.1:8080",
            ):
                if origin not in origins:
                    origins.append(origin)
        # Always include this product's SPA. Do not inject cobrother/hubregistrar
        # origins — those sites must not call the isolated Deltapreneur API.
        for origin in self._BRAND_SPA_ORIGINS:
            if origin not in origins:
                origins.append(origin)
        return origins

    def resolved_cors_origin_regex(self) -> str | None:
        """Allow https://*.deltapreneur.com SPA origins."""
        raw = (self.CORS_ALLOW_ORIGIN_REGEX or "").strip()
        if raw:
            return raw
        if self._is_production_env():
            return self._BRAND_SPA_ORIGIN_REGEX
        return None

    def google_oauth_success_redirect_url(self) -> str:
        if self.GOOGLE_OAUTH_SUCCESS_REDIRECT.strip():
            return self.GOOGLE_OAUTH_SUCCESS_REDIRECT.strip()
        return f"{self.FRONTEND_BASE_URL.rstrip('/')}/auth/callback"

    def resolved_linkedin_redirect_uri(self) -> str | None:
        """OAuth callback URL sent to LinkedIn — must match a portal-registered redirect exactly."""
        explicit = (self.LINKEDIN_REDIRECT_URI or "").strip()
        if explicit:
            return explicit.rstrip("/")
        base = (self.BACKEND_BASE_URL or "").strip().rstrip("/")
        if not base:
            return None
        return f"{base}/api/v1/community/linkedin/callback"

    @staticmethod
    def _tcp_port_open(host: str, port: int, timeout: float = 2.5) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def resolved_database_url(self) -> str:
        """
        Prefer DATABASE_URL. When it targets a local RDS tunnel (127.0.0.1:5433)
        and that port is closed, fall back to DATABASE_URL_DIRECT when reachable.
        """
        url = (self.DATABASE_URL or "").strip()
        if not url:
            return url

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port or 5432

        if host not in {"127.0.0.1", "localhost"}:
            return url

        if self._tcp_port_open(host, port):
            return url

        direct = (self.DATABASE_URL_DIRECT or "").strip()
        if not direct:
            logger.warning(
                "[DB] Local tunnel %s:%s is unavailable and DATABASE_URL_DIRECT is not set.",
                host,
                port,
            )
            return url

        direct_parsed = urlparse(direct)
        direct_host = direct_parsed.hostname or ""
        direct_port = direct_parsed.port or 5432
        if direct_host and self._tcp_port_open(direct_host, direct_port):
            logger.info(
                "[DB] Local tunnel %s:%s unavailable; using DATABASE_URL_DIRECT (%s:%s).",
                host,
                port,
                direct_host,
                direct_port,
            )
            return direct

        logger.warning(
            "[DB] Local tunnel %s:%s and DATABASE_URL_DIRECT (%s:%s) are both unreachable.",
            host,
            port,
            direct_host,
            direct_port,
        )
        return url


settings = Settings()
