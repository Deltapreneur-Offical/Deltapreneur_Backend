"""add_cart_items_table

Revision ID: ac0c34ac14f3
Revises: bc2a24942095
Create Date: 2026-07-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "ac0c34ac14f3"
down_revision: Union[str, Sequence[str], None] = "bc2a24942095"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cart_items",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "product_type",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("selected_plan", sa.String(length=64), nullable=True),
        sa.Column("addon_services", sa.Text(), nullable=True),
        sa.Column("co_brother_opt_in", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_cart_items_user", "cart_items", ["user_id"])
    op.create_index(
        "uq_cart_user_product",
        "cart_items",
        ["user_id", "product_type", "product_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_cart_user_product", table_name="cart_items")
    op.drop_index("idx_cart_items_user", table_name="cart_items")
    op.drop_table("cart_items")
