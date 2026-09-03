"""domain listing verification status for auction admin workflow

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-06-10 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, Sequence[str], None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS_ENUM = postgresql.ENUM(
    "PENDING",
    "VERIFIED",
    "REJECTED",
    "MORE_INFO_REQUESTED",
    name="domain_listing_verification_status_enum",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(
        "PENDING",
        "VERIFIED",
        "REJECTED",
        "MORE_INFO_REQUESTED",
        name="domain_listing_verification_status_enum",
    ).create(bind, checkfirst=True)

    op.add_column(
        "domain_listings",
        sa.Column(
            "verification_status",
            _STATUS_ENUM,
            nullable=False,
            server_default="PENDING",
        ),
    )
    op.add_column(
        "domain_listings",
        sa.Column("verified_by_user_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "domain_listings",
        sa.Column("verification_rejection_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "domain_listings",
        sa.Column("verification_admin_note", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_domain_listings_verified_by_user_id_users"),
        "domain_listings",
        "users",
        ["verified_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ONE_TIME: mirror verified boolean for admin badge display
    op.execute(
        """
        UPDATE domain_listings
        SET verification_status = 'VERIFIED'
        WHERE sale_type = 'ONE_TIME' AND verified = true
        """
    )

    # AUCTION with live auction: grandfather as verified
    op.execute(
        """
        UPDATE domain_listings dl
        SET verification_status = 'VERIFIED'
        WHERE dl.sale_type = 'AUCTION'
          AND EXISTS (
            SELECT 1 FROM auctions a
            WHERE a.domain_id = dl.id
              AND a.is_deleted = false
              AND a.status IN ('ACTIVE', 'EXTENDED')
          )
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_domain_listings_verified_by_user_id_users"),
        "domain_listings",
        type_="foreignkey",
    )
    op.drop_column("domain_listings", "verification_admin_note")
    op.drop_column("domain_listings", "verification_rejection_reason")
    op.drop_column("domain_listings", "verified_by_user_id")
    op.drop_column("domain_listings", "verification_status")
    bind = op.get_bind()
    postgresql.ENUM(
        name="domain_listing_verification_status_enum",
    ).drop(bind, checkfirst=True)
