"""Add explicit seller payout account number fields.

Revision ID: t9u0v1w2x3y4
Revises: s8t9u0v1w2x3
Create Date: 2026-06-11 21:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "t9u0v1w2x3y4"
down_revision: Union[str, Sequence[str], None] = "s8t9u0v1w2x3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("seller_payout_profiles", sa.Column("account_number", sa.String(length=100), nullable=True))
    op.add_column("seller_payout_profiles", sa.Column("account_number_last4", sa.String(length=4), nullable=True))
    try:
        from app.service.security.auth_code_encryption_service import decrypt_secret
    except Exception:
        return

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, bank_account_number_encrypted
            FROM seller_payout_profiles
            WHERE account_number IS NULL
              AND bank_account_number_encrypted IS NOT NULL
            """
        )
    ).mappings().all()
    for row in rows:
        try:
            account_number = decrypt_secret(row["bank_account_number_encrypted"]).strip()
        except Exception:
            continue
        if not account_number:
            continue
        bind.execute(
            sa.text(
                """
                UPDATE seller_payout_profiles
                SET account_number = :account_number,
                    account_number_last4 = :account_number_last4
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "account_number": account_number,
                "account_number_last4": account_number[-4:],
            },
        )


def downgrade() -> None:
    op.drop_column("seller_payout_profiles", "account_number_last4")
    op.drop_column("seller_payout_profiles", "account_number")
