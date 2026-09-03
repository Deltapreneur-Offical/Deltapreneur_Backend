"""seed compliance operations services

Revision ID: q3r4s5t6u7v8
Revises: p2q3r4s5t6u7
Create Date: 2026-06-12 16:00:00.000000

"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "q3r4s5t6u7v8"
down_revision: Union[str, Sequence[str], None] = "p2q3r4s5t6u7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COMPLIANCE_SEED_ROWS = [
    ("GST Registration", 3000.0, "Calculator", "GST_REGISTRATION", "gst registration tax compliance", 1,
     "End-to-end GST registration support for your business."),
    ("Trademark Registration", 0.0, "ShieldCheck", "TRADEMARK_REGISTRATION", "trademark brand ip registration", 2,
     "Protect your brand with trademark registration assistance."),
    ("Company / LLP / Proprietorship Registration", 0.0, "Briefcase", "COMPANY_REGISTRATION",
     "company llp proprietorship incorporation registration", 3,
     "Company, LLP, or proprietorship incorporation support."),
    ("Udyam Registration", 1500.0, "ClipboardList", "UDYAM_REGISTRATION", "udyam msme registration", 4,
     "MSME Udyam registration for government benefits and recognition."),
    ("Website Development", 0.0, "Code", "WEBSITE_DEVELOPMENT", "website development web design", 5,
     "Professional website development for your business presence."),
    ("Import Export Code (IEC) Registration", 2000.0, "Globe", "IEC_REGISTRATION", "iec import export code trade", 6,
     "Import Export Code registration for international trade."),
    ("Digital Signature Certificate", 3000.0, "FileCheck", "DIGITAL_SIGNATURE", "digital signature dsc certificate", 7,
     "Digital Signature Certificate for secure online filings."),
    ("Professional Tax Registration", 2500.0, "Receipt", "PROFESSIONAL_TAX", "professional tax registration", 8,
     "Professional tax registration and compliance support."),
    ("Startup India Registration", 3000.0, "Rocket", "STARTUP_INDIA", "startup india registration dpiit", 9,
     "Startup India recognition and registration assistance."),
]


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    for name, price, icon, addon_key, skills, display_order, description in COMPLIANCE_SEED_ROWS:
        exists = conn.execute(
            sa.text(
                """
                SELECT 1 FROM operations_services
                WHERE service_type = 'compliance'
                  AND skills = :skills
                  AND is_deleted = false
                LIMIT 1
                """
            ),
            {"skills": addon_key},
        ).fetchone()
        if exists:
            continue

        conn.execute(
            sa.text(
                """
                INSERT INTO operations_services (
                    id, name, category, description, price, is_available,
                    icon, display_order, skills, service_type,
                    created_at, updated_at, is_deleted
                ) VALUES (
                    :id, :name, 'compliance', :description, :price, true,
                    :icon, :display_order, :skills, 'compliance',
                    :created_at, :updated_at, false
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "name": name,
                "description": description,
                "price": price,
                "icon": icon,
                "display_order": display_order,
                "skills": addon_key,
                "created_at": now,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    keys = [row[3] for row in COMPLIANCE_SEED_ROWS]
    conn.execute(
        sa.text(
            """
            DELETE FROM operations_services
            WHERE service_type = 'compliance'
              AND skills = ANY(:keys)
            """
        ),
        {"keys": keys},
    )
