"""Create hub_registrar_categories table and seed existing categories.

Revision ID: hubreg006
Revises: ops_req_category_001
Create Date: 2026-09-01 12:00:00.000000

SAFETY: additive only — new table, no existing data affected.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "hubreg006"
down_revision: Union[str, Sequence[str], None] = "ops_req_category_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ──────────────────────────────────────────────────────────────────────────────
# Seed data — copied from frontend operationsCategories.js so both the static
# frontend constants and the database stay in sync until the frontend is switched
# to read from the API.
# ──────────────────────────────────────────────────────────────────────────────
SEED_CATEGORIES = [
    {"slug": "business_entity",        "name": "Business / Entity Registration", "description": "Incorporate proprietorships, partnerships, LLPs, private limited companies, and other legal entities.", "starting_price": 1,      "icon": "Building2", "display_order": 1},
    {"slug": "tax_identity",           "name": "Tax and Identity",              "description": "PAN, TAN, GST, and professional tax support for compliant tax identity.",                                 "starting_price": 99,     "icon": "Receipt",  "display_order": 2},
    {"slug": "local_licences",         "name": "Local Licences",                "description": "Shops & Establishments, trade licences, and municipal permissions.",                                   "starting_price": 999,    "icon": "Landmark", "display_order": 3},
    {"slug": "msme_udyam",             "name": "MSME / Udyam",                  "description": "Udyam registration for eligible micro, small, and medium enterprises.",                                "starting_price": 1,      "icon": "Factory",  "display_order": 4},
    {"slug": "startup_dpiit",          "name": "Startup / DPIIT Recognition",   "description": "DPIIT Startup recognition for eligible Indian startups.",                                              "starting_price": 2999,   "icon": "Rocket",   "display_order": 5},
    {"slug": "food_fssai",             "name": "Food and FSSAI",                "description": "FSSAI registration and licensing for food businesses of every scale.",                                  "starting_price": 1499,   "icon": "UtensilsCrossed", "display_order": 6},
    {"slug": "import_export",          "name": "Import / Export",               "description": "IEC, DGFT, and customs-related support for international trade.",                                      "starting_price": 999,    "icon": "Globe",    "display_order": 7},
    {"slug": "manufacturing",          "name": "Manufacturing",                 "description": "Factory, pollution, and plant-level compliance for manufacturers.",                                    "starting_price": 4999,   "icon": "Factory",  "display_order": 8},
    {"slug": "technology_saas",        "name": "Technology / SaaS / IT",        "description": "Entity, GST, and operating registrations for software and IT companies.",                              "starting_price": 2999,   "icon": "Cpu",      "display_order": 9},
    {"slug": "ecommerce",              "name": "E-commerce",                    "description": "Marketplace and inventory e-commerce compliance, from GST to packaged goods.",                         "starting_price": 2499,   "icon": "ShoppingBag", "display_order": 10},
    {"slug": "fintech",                "name": "Financial / FinTech",           "description": "RBI, SEBI, NBFC, and other activity-specific financial licences.",                                    "starting_price": 7999,   "icon": "Landmark", "display_order": 11},
    {"slug": "aviation",               "name": "Aviation",                      "description": "DGCA, operator, drone, and aviation-training approvals.",                                             "starting_price": 9999,   "icon": "Plane",    "display_order": 12},
    {"slug": "construction_real_estate", "name": "Construction / Real Estate",  "description": "Contractor licences, building permissions, and RERA support.",                                        "starting_price": 4999,   "icon": "HardHat",  "display_order": 13},
    {"slug": "healthcare",             "name": "Healthcare",                    "description": "Clinical establishment, pharmacy, and medical-device registrations.",                                 "starting_price": 4999,   "icon": "HeartPulse", "display_order": 14},
    {"slug": "education",              "name": "Education",                     "description": "School, coaching, college, and EdTech recognition and affiliation support.",                           "starting_price": 2499,   "icon": "GraduationCap", "display_order": 15},
    {"slug": "professional_services",  "name": "Professional Services",         "description": "Practice setup for CAs, lawyers, doctors, architects, and consultants.",                              "starting_price": 1999,   "icon": "Briefcase", "display_order": 16},
    {"slug": "telecom",                "name": "Telecom / Communications",      "description": "DoT, ISP, and communications-related authorisations.",                                               "starting_price": 7999,   "icon": "Radio",    "display_order": 17},
    {"slug": "pharma_chemical",        "name": "Pharmaceutical / Chemical",     "description": "Drug licences, CDSCO, and chemical manufacturing approvals.",                                        "starting_price": 7999,   "icon": "FlaskConical", "display_order": 18},
    {"slug": "automotive",             "name": "Automotive",                    "description": "Vehicle, EV, component, and dealer certification pathways.",                                          "starting_price": 4999,   "icon": "Car",      "display_order": 19},
    {"slug": "agriculture",            "name": "Agriculture",                   "description": "FPO, APMC, seed, fertiliser, and agri-trade licences.",                                              "starting_price": 2499,   "icon": "Wheat",    "display_order": 20},
    {"slug": "logistics_transport",    "name": "Logistics / Transport",         "description": "Transport permits, warehousing, and freight compliance.",                                             "starting_price": 2999,   "icon": "Truck",    "display_order": 21},
    {"slug": "tourism_hospitality",    "name": "Tourism / Hospitality",         "description": "Hotels, travel agencies, homestays, and tourism department registrations.",                           "starting_price": 2499,   "icon": "Hotel",    "display_order": 22},
    {"slug": "entertainment_media",    "name": "Entertainment / Media",         "description": "Production, OTT, events, gaming, and media permissions.",                                             "starting_price": 2999,   "icon": "Clapperboard", "display_order": 23},
    {"slug": "energy_power",           "name": "Energy / Solar / Power",        "description": "Solar, power, EV charging, and electricity-related approvals.",                                       "starting_price": 4999,   "icon": "Zap",      "display_order": 24},
    {"slug": "defence_aerospace",      "name": "Defence / Aerospace",           "description": "Industrial licences, export controls, and aerospace clearances.",                                     "starting_price": 9999,   "icon": "Shield",   "display_order": 25},
    {"slug": "intellectual_property",  "name": "Intellectual Property",         "description": "Trademark, patent, copyright, and design protection.",                                                "starting_price": 2999,   "icon": "Copyright", "display_order": 26},
    {"slug": "employer_labour",        "name": "Employer / Labour",             "description": "EPFO, ESIC, shops, and labour registrations for employers.",                                          "starting_price": 2499,   "icon": "Users",    "display_order": 27},
    {"slug": "environmental",          "name": "Environmental",                 "description": "Pollution consent, environmental clearance, and waste authorisations.",                              "starting_price": 4999,   "icon": "Leaf",     "display_order": 28},
    {"slug": "digital_services",       "name": "Digital Services",              "description": "Website, DSC, and digital operating services for filings and presence.",                              "starting_price": 1999,   "icon": "Monitor",  "display_order": 29},
]


def upgrade() -> None:
    op.create_table(
        "hub_registrar_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starting_price", sa.Float(), nullable=True),
        sa.Column("icon", sa.String(length=64), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hub_registrar_categories")),
    )
    op.create_index(
        "idx_hub_registrar_categories_public_browse",
        "hub_registrar_categories",
        ["is_deleted", "is_active", "display_order"],
        unique=False,
    )
    op.create_index(
        "idx_hub_registrar_categories_slug",
        "hub_registrar_categories",
        ["slug"],
        unique=True,
    )

    # ── Seed existing categories ───────────────────────────────────────────
    # Use raw SQL to generate UUIDs and timestamps in a single insert so the
    # seed is idempotent-safe (only runs on fresh table).
    op.execute(
        """
        INSERT INTO hub_registrar_categories
            (id, slug, name, description, starting_price, icon, display_order,
             is_active, is_deleted, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            s.slug,
            s.name,
            s.description,
            s.starting_price,
            s.icon,
            s.display_order,
            true,
            false,
            NOW(),
            NOW()
        FROM (VALUES
            {values}
        ) AS s(slug, name, description, starting_price, icon, display_order)
        ON CONFLICT (slug) DO NOTHING
        """.format(
            values=", ".join(
                f"('{c['slug']}', '{c['name'].replace(chr(39), chr(39)+chr(39))}', "
                f"'{c['description'].replace(chr(39), chr(39)+chr(39))}', "
                f"{c['starting_price']}, '{c['icon']}', {c['display_order']})"
                for c in SEED_CATEGORIES
            )
        )
    )


def downgrade() -> None:
    op.drop_index("idx_hub_registrar_categories_slug", table_name="hub_registrar_categories")
    op.drop_index("idx_hub_registrar_categories_public_browse", table_name="hub_registrar_categories")
    op.drop_table("hub_registrar_categories")
