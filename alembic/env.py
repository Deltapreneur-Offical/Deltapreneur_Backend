from logging.config import fileConfig
import os

from sqlalchemy import MetaData, engine_from_config, pool

from alembic import context

from app.entity.community.community import Community
from app.entity.notification.notification import Notification
from app.entity.community.community_auction import CommunityAuction
from app.entity.community.community_auction_bid import CommunityAuctionBid
from app.entity.community.community_post import CommunityPost
from app.entity.community.community_comment import CommunityComment
from app.entity.likes.like import Like
from app.entity.user.app_user import AppUser
from app.entity.analytics.venture_view import VentureView

from app.core.config import settings
from app.core.database import Base, DATABASE_URL as NORMALIZED_DATABASE_URL

# User module
from app.entity.user.app_user import AppUser            # noqa: F401
from app.entity.user.refresh_token import RefreshToken  # noqa: F401
from app.entity.user.edge_points_redemption import EdgePointsRedemption  # noqa: F401
from app.entity.user.edge_points_history import EdgePointsHistory  # noqa: F401
from app.entity.user.referral_track import ReferralTrack  # noqa: F401
from app.entity.platform.platform_setting_entity import PlatformSetting  # noqa: F401

# Auction module
from app.entity.auction.auction_entity import Auction          # noqa: F401
from app.entity.auction.bid_entity import Bid                  # noqa: F401
from app.entity.auction.domain_entity import Domain            # noqa: F401
from app.entity.auction.payment_entity import Payment          # noqa: F401
from app.entity.auction.transaction_entity import Transaction  # noqa: F401
from app.entity.auction.auction_fee_payment_entity import AuctionFeePayment  # noqa: F401

# Venture / CoCreation / Marketplace
from app.entity.coventure.venture_entity import Venture  # noqa: F401
from app.entity.coventure.venture_pitch_entity import VenturePitch  # noqa: F401
from app.entity.coventure.venture_acquisition_application_entity import (  # noqa: F401
    VentureAcquisitionApplication,
)
from app.entity.coventure.partner_entity import CoVenture  # noqa: F401
from app.entity.coventure.venture_role_entity import VentureRole  # noqa: F401
from app.entity.coventure.brand_details_entity import BrandDetails  # noqa: F401
from app.entity.coventure.contact_info_entity import ContactInfo  # noqa: F401
from app.entity.coventure.agreement_entity import Agreement  # noqa: F401
from app.entity.cobranding.domain_listing_entity import DomainListing  # noqa: F401
from app.entity.cobranding.domain_enquiry_entity import DomainEnquiry  # noqa: F401
from app.entity.cocreation.software_entity import Software  # noqa: F401
from app.entity.cobrother.cobrother_request_entity import CoBrotherRequest  # noqa: F401
from app.entity.becobrother.be_cobrother_entity import BeCoBrotherApplication  # noqa: F401
from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder  # noqa: F401
from app.entity.domain.domain_marketplace_transaction_entity import DomainMarketplaceTransaction  # noqa: F401
from app.entity.domain.domain_transfer_event_entity import DomainTransferEvent  # noqa: F401
from app.entity.domain.domain_dispute_entity import DomainDispute, DomainDisputeEvidence  # noqa: F401
from app.entity.domain.openprovider_managed_acquisition_entity import (  # noqa: F401
    OpenProviderManagedAcquisition,
)
from app.entity.domain.openprovider_showcase_entity import (  # noqa: F401
    OpenProviderShowcaseDomain,
)
from app.entity.payout.seller_payout_profile_entity import SellerPayoutProfile  # noqa: F401
from app.entity.payout.seller_payout_entity import SellerPayout  # noqa: F401
from app.entity.payout.seller_payout_profile_audit_entity import SellerPayoutProfileAuditEvent  # noqa: F401
from app.entity.cocreation.software_purchase_entity import SoftwarePurchase  # noqa: F401
from app.entity.coventure.venture_financial_profile_entity import VentureFinancialProfile  # noqa: F401
from app.entity.coventure.venture_document_entity import VentureDocument  # noqa: F401
from app.entity.coventure.venture_deal_transaction_entity import VentureDealTransaction  # noqa: F401
from app.entity.coventure.venture_deal_event_entity import VentureDealEvent  # noqa: F401
from app.entity.cocreation.software_auction import SoftwareAuction  # noqa: F401
from app.entity.cocreation.software_auction_bid import SoftwareAuctionBid  # noqa: F401
from app.entity.cocreation.software_auction_participation_entity import SoftwareAuctionParticipation  # noqa: F401
from app.entity.community.meeting_schedule import MeetingSchedule  # noqa: F401
from app.entity.operations.operations_service_entity import OperationsService  # noqa: F401
from app.entity.operations.operations_service_request_entity import OperationsServiceRequest  # noqa: F401
from app.entity.cart.cart_item_entity import CartItem  # noqa: F401
from app.entity.ai.cobrother_ai import (  # noqa: F401
    AiAnalyticsEvent,
    ChatMessage,
    ChatSession,
    Favorite,
    UserPreference,
)


# Alembic Config object — provides access to alembic.ini values.
config = context.config

# Inject runtime DB URL so alembic.ini doesn't have to hard-code credentials.
# Alembic always uses a SYNC driver; rewrite asyncpg → psycopg2 if needed.
def _to_sync_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    return url


def _migration_database_url() -> str:
    """Prefer DATABASE_URL from the environment (supports test DB overrides)."""
    raw = os.getenv("DATABASE_URL") or NORMALIZED_DATABASE_URL
    if raw.startswith("postgresql+asyncpg://"):
        raw = raw.replace("postgresql+asyncpg://", "postgresql://", 1)
    # Reuse app pooler normalization (session :5432, not transaction :6543).
    if "pooler.supabase.com" in raw and ":6543" in raw:
        raw = raw.replace(":6543", ":5432", 1)
    return _to_sync_url(raw)


config.set_main_option("sqlalchemy.url", _migration_database_url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
from app.entity.base.base import Base

# Import all models here so Alembic detects them
from app.entity.user.app_user import AppUser
from app.entity.user.refresh_token import RefreshToken
from app.entity.analytics.venture_view import VentureView
from app.entity.analytics.profile_view import ProfileView
from app.entity.analytics.software_view import SoftwareView  # noqa: F401
from app.entity.analytics.domain_listing_view import DomainListingView  # noqa: F401
from app.entity.analytics.virtual_assistant_view import VirtualAssistantView  # noqa: F401
from app.entity.analytics.operations_service_view import OperationsServiceView  # noqa: F401
from app.entity.user.password_reset_token import PasswordResetToken

# ---------------------------------------------------------------------------
# Naming convention — ensures every constraint gets a deterministic, stable
# name across DB engines. Critical for reversible migrations.
# ---------------------------------------------------------------------------

NAMING_CONVENTION = {
    "ix":  "ix_%(table_name)s_%(column_0_N_name)s",
    "uq":  "uq_%(table_name)s_%(column_0_N_name)s",
    "ck":  "ck_%(table_name)s_%(constraint_name)s",
    "fk":  "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk":  "pk_%(table_name)s",
}

# Re-bind metadata to a convention-aware MetaData. SQLAlchemy will fall back
# to model-supplied names where present.
Base.metadata.naming_convention = NAMING_CONVENTION
target_metadata: MetaData = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_schemas=False,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_schemas=False,
            # Render named server-side enums consistently across upgrades.
            render_as_batch=False,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
