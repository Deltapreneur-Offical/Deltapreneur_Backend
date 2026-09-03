"""Rename venture pitches table, tighten payment FKs, drop legacy enum values.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-06-16 18:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- venture_acquisition_applications → venture_pitches ---
    op.rename_table("venture_acquisition_applications", "venture_pitches")
    op.execute("ALTER INDEX IF EXISTS idx_vaa_venture_id RENAME TO idx_venture_pitches_venture_id")
    op.execute(
        "ALTER INDEX IF EXISTS idx_vaa_buyer_user_id RENAME TO idx_venture_pitches_buyer_user_id"
    )
    op.execute("ALTER INDEX IF EXISTS idx_vaa_status RENAME TO idx_venture_pitches_status")
    op.execute(
        "ALTER TABLE venture_pitches RENAME CONSTRAINT uq_vaa_venture_buyer "
        "TO uq_venture_pitches_venture_buyer"
    )

    # --- payment integrity: user_id → users ---
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM auction_fee_payments afp
                WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.id = afp.user_id)
            ) THEN
                RAISE EXCEPTION
                    'auction_fee_payments contains orphan user_id values; fix before migrating';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM auction_participations ap
                WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.id = ap.user_id)
            ) THEN
                RAISE EXCEPTION
                    'auction_participations contains orphan user_id values; fix before migrating';
            END IF;
        END $$;
        """
    )
    op.create_foreign_key(
        "fk_auction_fee_payments_user_id_users",
        "auction_fee_payments",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_auction_participations_user_id_users",
        "auction_participations",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- drop legacy VENTURE from auction_fee_auction_type_enum ---
    op.execute("DELETE FROM auction_fee_payments WHERE auction_type::text = 'VENTURE'")
    op.execute(
        """
        CREATE TYPE auction_fee_auction_type_enum_new AS ENUM (
            'DOMAIN', 'SOFTWARE', 'COMMUNITY'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE auction_fee_payments
        ALTER COLUMN auction_type TYPE auction_fee_auction_type_enum_new
        USING auction_type::text::auction_fee_auction_type_enum_new
        """
    )
    op.execute("DROP TYPE auction_fee_auction_type_enum")
    op.execute(
        "ALTER TYPE auction_fee_auction_type_enum_new RENAME TO auction_fee_auction_type_enum"
    )

    # --- drop legacy AUCTION from venture_sale_type_enum ---
    op.execute("UPDATE ventures SET sale_type = 'REGULAR' WHERE sale_type::text = 'AUCTION'")
    op.execute("CREATE TYPE venture_sale_type_enum_new AS ENUM ('REGULAR')")
    op.execute(
        """
        ALTER TABLE ventures
        ALTER COLUMN sale_type TYPE venture_sale_type_enum_new
        USING sale_type::text::venture_sale_type_enum_new
        """
    )
    op.execute("DROP TYPE venture_sale_type_enum")
    op.execute("ALTER TYPE venture_sale_type_enum_new RENAME TO venture_sale_type_enum")


def downgrade() -> None:
    raise NotImplementedError(
        "venture_pitches rename, payment FKs, and enum cleanup cannot be rolled back automatically."
    )
