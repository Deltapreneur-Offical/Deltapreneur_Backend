"""Seed ResellPortal provider_product_key values for confirmed services.

Revision ID: rp_seed_provider_keys_001
Revises: rp_provider_map_001
Create Date: 2026-08-13 11:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "rp_seed_provider_keys_001"
down_revision: Union[str, Sequence[str], None] = "rp_provider_map_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PROVIDER_KEYS = {
    "ai-business-suite": "ai_business_tools",
    "website-builder": "website_builder",
    "web-hosting": "web_hosting",
    "cloud-storage": "cloud_storage",
    "email-marketing": "email_marketing",
    "esim": "esim",
    "smm-growth": "smm",
    "vpn": "vpn",
    "crm": "crm",
    "invoice-ai": "invoice_ai",
    "appointment-booking": "appointments",
    "document-signer": "docsign",
    "business-phone": "business_phone",
    "social-media-automation": "social_media_automation",
    "reputation-management": "reputation_management",
    "link-in-bio": "link_in_bio",
    # wordpress-plugin-pack is NOT available (404 invalid_product)
}


def upgrade() -> None:
    connection = op.get_bind()
    for slug, product_key in PROVIDER_KEYS.items():
        connection.execute(
            sa.text(
                "UPDATE technology_services_catalogue SET provider_product_key = :pk WHERE slug = :slug"
            ),
            {"pk": product_key, "slug": slug},
        )


def downgrade() -> None:
    connection = op.get_bind()
    for slug in PROVIDER_KEYS:
        connection.execute(
            sa.text(
                "UPDATE technology_services_catalogue SET provider_product_key = NULL WHERE slug = :slug"
            ),
            {"slug": slug},
        )
