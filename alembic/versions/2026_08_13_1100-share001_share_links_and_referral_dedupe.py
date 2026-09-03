"""share_links + referral_tracks dedupe columns.

Adds the generic share-link table and the atomic one-reward-per-
(referrer, item, receiver) guard on referral_tracks.

Revision ID: share001
Revises: 131e1cf19e68
Create Date: 2026-08-13 11:00:00

SAFETY NOTES (read before applying to a shared database):
  * This migration is additive: it creates one new table, adds three
    nullable columns, backfills derived dedupe keys, and creates two
    partial UNIQUE indexes.
  * Creating the UNIQUE indexes FAILS if historical duplicate referral
    rows exist. Run the read-only duplicate scan first:
        SELECT referrer_id, listing_id, visitor_id, COUNT(*)
        FROM referral_tracks WHERE visitor_id IS NOT NULL
        GROUP BY 1,2,3 HAVING COUNT(*) > 1;
        SELECT referrer_id, listing_id, visitor_ip, COUNT(*)
        FROM referral_tracks WHERE visitor_id IS NULL
        GROUP BY 1,2,3 HAVING COUNT(*) > 1;
    If any duplicates are found, STOP and resolve them with the data
    owner before applying.
  * No existing column is dropped or renamed; no existing row is deleted
    or modified beyond backfilling the two new derived columns.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
# Chains from 131e1cf19e68 (the current single head — merge of taxinv001 and
# the ResellPortal/technology chain) so the graph keeps exactly one head.
revision: str = "share001"
down_revision: Union[str, Sequence[str], None] = "131e1cf19e68"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── NEW table: share_links ────────────────────────────────────────────────
    op.create_table(
        "share_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("token", sa.String(length=32), nullable=False),
        sa.Column(
            "share_type",
            sa.Enum(
                "MARKETPLACE",
                "DOMAIN_SEARCH",
                "AI_BRAND_DOMAIN",
                name="share_type_enum",
            ),
            nullable=False,
        ),
        # NULL for logged-out senders — no referrer means no Edge Points reward.
        sa.Column("referrer_id", sa.UUID(), nullable=True),
        sa.Column("listing_id", sa.UUID(), nullable=True),
        sa.Column("domain", sa.String(length=253), nullable=True),
        sa.Column("original_query", sa.Text(), nullable=True),
        sa.Column("referrer_visitor_key", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "REVOKED", name="share_status_enum"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(share_type = 'MARKETPLACE' AND listing_id IS NOT NULL AND domain IS NULL) "
            "OR (share_type IN ('DOMAIN_SEARCH', 'AI_BRAND_DOMAIN') "
            "AND domain IS NOT NULL AND listing_id IS NULL)",
            name="ck_share_links_item_reference",
        ),
        sa.ForeignKeyConstraint(
            ["referrer_id"],
            ["users.id"],
            name=op.f("fk_share_links_referrer_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["domain_listings.id"],
            name=op.f("fk_share_links_listing_id_domain_listings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_share_links")),
    )
    op.create_index(
        op.f("ix_share_links_token"), "share_links", ["token"], unique=True
    )
    op.create_index(
        op.f("ix_share_links_referrer_id"), "share_links", ["referrer_id"], unique=False
    )
    op.create_index(
        op.f("ix_share_links_listing_id"), "share_links", ["listing_id"], unique=False
    )
    op.create_index(
        op.f("ix_share_links_domain"), "share_links", ["domain"], unique=False
    )
    op.create_index(
        op.f("ix_share_links_share_type"), "share_links", ["share_type"], unique=False
    )
    op.create_index(
        op.f("ix_share_links_status"), "share_links", ["status"], unique=False
    )
    op.create_index(
        "ix_share_links_referrer_domain",
        "share_links",
        ["referrer_id", "share_type", "domain"],
        unique=False,
    )

    # ── MODIFIED table: referral_tracks (additive columns) ────────────────────
    op.add_column(
        "referral_tracks", sa.Column("share_link_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "referral_tracks", sa.Column("item_key", sa.String(length=253), nullable=True)
    )
    op.add_column(
        "referral_tracks", sa.Column("visitor_key", sa.String(length=64), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_referral_tracks_share_link_id_share_links"),
        "referral_tracks",
        "share_links",
        ["share_link_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_referral_tracks_share_link_id"),
        "referral_tracks",
        ["share_link_id"],
        unique=False,
    )

    # ── Backfill derived dedupe keys for existing rows ────────────────────────
    # item_key:  legacy rows are all marketplace-style → "<listing_type>:<listing_id>"
    # visitor_key: logged-in rows → user id; anonymous rows → IP (today's semantics)
    op.execute(
        "UPDATE referral_tracks SET item_key = listing_type || ':' || listing_id::text "
        "WHERE item_key IS NULL"
    )
    op.execute(
        "UPDATE referral_tracks SET visitor_key = COALESCE(visitor_id::text, visitor_ip) "
        "WHERE visitor_key IS NULL"
    )

    # ── Atomic dedupe guard (partial UNIQUE indexes) ──────────────────────────
    # Fails if the read-only duplicate scan found historical duplicates.
    op.execute(
        "CREATE UNIQUE INDEX uq_referral_referrer_item_visitor_user "
        "ON referral_tracks (referrer_id, item_key, visitor_id) "
        "WHERE visitor_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_referral_referrer_item_visitor_anon "
        "ON referral_tracks (referrer_id, item_key, visitor_key) "
        "WHERE visitor_id IS NULL"
    )


def downgrade() -> None:
    # ── referral_tracks ───────────────────────────────────────────────────────
    op.execute("DROP INDEX IF EXISTS uq_referral_referrer_item_visitor_anon")
    op.execute("DROP INDEX IF EXISTS uq_referral_referrer_item_visitor_user")
    op.drop_index(
        op.f("ix_referral_tracks_share_link_id"), table_name="referral_tracks"
    )
    op.drop_constraint(
        op.f("fk_referral_tracks_share_link_id_share_links"),
        "referral_tracks",
        type_="foreignkey",
    )
    op.drop_column("referral_tracks", "visitor_key")
    op.drop_column("referral_tracks", "item_key")
    op.drop_column("referral_tracks", "share_link_id")

    # ── share_links ───────────────────────────────────────────────────────────
    op.drop_index("ix_share_links_referrer_domain", table_name="share_links")
    op.drop_index(op.f("ix_share_links_status"), table_name="share_links")
    op.drop_index(op.f("ix_share_links_share_type"), table_name="share_links")
    op.drop_index(op.f("ix_share_links_domain"), table_name="share_links")
    op.drop_index(op.f("ix_share_links_listing_id"), table_name="share_links")
    op.drop_index(op.f("ix_share_links_referrer_id"), table_name="share_links")
    op.drop_index(op.f("ix_share_links_token"), table_name="share_links")
    op.drop_table("share_links")
    sa.Enum(name="share_status_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="share_type_enum").drop(op.get_bind(), checkfirst=True)
