"""cobrother ai operating system tables

Revision ID: a9b8c7d6e5f4
Revises: ee3232f7a617
Create Date: 2026-05-29 18:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "a9b8c7d6e5f4"
down_revision = "ee3232f7a617"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    op.create_table(
        "chat_history",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("mode", sa.String(length=40), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_chat_history_updated_at", "chat_history", ["updated_at"])
    op.create_index("idx_chat_history_user_id", "chat_history", ["user_id"])

    op.create_table(
        "chat_messages",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=40), nullable=False),
        sa.Column("context_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_history.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_chat_messages_created_at", "chat_messages", ["created_at"])
    op.create_index("idx_chat_messages_session_id", "chat_messages", ["session_id"])

    op.create_table(
        "user_preferences",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("favorite_categories", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("naming_preferences", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("venture_interests", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("domain_interests", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("voice_enabled", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_preferences_user_id"),
    )
    op.create_index("idx_user_preferences_user_id", "user_preferences", ["user_id"])

    op.create_table(
        "favorites",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_type", sa.String(length=40), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "asset_type", "asset_id", name="uq_favorites_user_asset"),
    )
    op.create_index("idx_favorites_asset", "favorites", ["asset_type", "asset_id"])
    op.create_index("idx_favorites_user_id", "favorites", ["user_id"])

    if "ai_analytics_events" in existing_tables:
        existing_columns = {
            column["name"]
            for column in inspector.get_columns("ai_analytics_events")
        }
        if "user_id" not in existing_columns:
            op.add_column(
                "ai_analytics_events",
                sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
        if "mode" not in existing_columns:
            op.add_column("ai_analytics_events", sa.Column("mode", sa.String(length=40), nullable=True))
        if "query" not in existing_columns:
            op.add_column("ai_analytics_events", sa.Column("query", sa.Text(), nullable=True))
        if "asset_type" not in existing_columns:
            op.add_column("ai_analytics_events", sa.Column("asset_type", sa.String(length=40), nullable=True))
        if "asset_id" not in existing_columns:
            op.add_column(
                "ai_analytics_events",
                sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
        if "metadata_json" not in existing_columns:
            op.add_column(
                "ai_analytics_events",
                sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            )
        op.create_foreign_key(
            "fk_ai_analytics_events_user_id_users",
            "ai_analytics_events",
            "users",
            ["user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    else:
        op.create_table(
            "ai_analytics_events",
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("mode", sa.String(length=40), nullable=True),
            sa.Column("query", sa.Text(), nullable=True),
            sa.Column("asset_type", sa.String(length=40), nullable=True),
            sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    op.execute("CREATE INDEX IF NOT EXISTS idx_ai_analytics_created_at ON ai_analytics_events (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ai_analytics_event_type ON ai_analytics_events (event_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ai_analytics_user_id ON ai_analytics_events (user_id)")


def downgrade() -> None:
    op.drop_index("idx_ai_analytics_user_id", table_name="ai_analytics_events")
    op.drop_index("idx_ai_analytics_event_type", table_name="ai_analytics_events")
    op.drop_index("idx_ai_analytics_created_at", table_name="ai_analytics_events")
    op.drop_table("ai_analytics_events")
    op.drop_index("idx_favorites_user_id", table_name="favorites")
    op.drop_index("idx_favorites_asset", table_name="favorites")
    op.drop_table("favorites")
    op.drop_index("idx_user_preferences_user_id", table_name="user_preferences")
    op.drop_table("user_preferences")
    op.drop_index("idx_chat_messages_session_id", table_name="chat_messages")
    op.drop_index("idx_chat_messages_created_at", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("idx_chat_history_user_id", table_name="chat_history")
    op.drop_index("idx_chat_history_updated_at", table_name="chat_history")
    op.drop_table("chat_history")
