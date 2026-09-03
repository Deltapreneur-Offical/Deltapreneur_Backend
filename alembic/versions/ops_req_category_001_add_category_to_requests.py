"""Add category to operations_service_requests. Revision ID: ops_req_category_001
"""
from alembic import op
import sqlalchemy as sa

revision = "ops_req_category_001"
down_revision = "merge_payout_hubreg_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "operations_service_requests",
        sa.Column("category", sa.String(64), nullable=True),
    )
    # Backfill existing requests from their linked Hub Registrar service
    op.execute(
        """
        UPDATE operations_service_requests AS req
        SET category = svc.category
        FROM operations_services AS svc
        WHERE req.operations_service_id = svc.id
          AND req.category IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("operations_service_requests", "category")
