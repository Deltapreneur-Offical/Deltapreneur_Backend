"""READ-ONLY duplicate audit of `referral_tracks` (production RDS).

Only SELECTs are executed. The session is forced read-only and autocommit, so
no transaction can mutate anything. Run:

    ./.venv/Scripts/python.exe scripts/referral_duplicate_scan.py

Exit code 0 = scan complete (results printed). Nothing is written anywhere.
"""

from __future__ import annotations

import os
from pathlib import Path

import dotenv

dotenv.load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import create_engine, text  # noqa: E402

URL = os.getenv("DATABASE_URL_DIRECT") or os.getenv("DATABASE_URL")
assert URL, "DATABASE_URL_DIRECT / DATABASE_URL not set"

engine = create_engine(URL, connect_args={"connect_timeout": 15})

with engine.connect() as conn:
    # Belt and braces: this connection can never write.
    conn.execute(text("SET default_transaction_read_only = on"))
    conn.execute(text("SET statement_timeout = 60000"))

    total = conn.execute(text("SELECT count(*) FROM referral_tracks")).scalar()
    awarded = conn.execute(
        text("SELECT count(*) FROM referral_tracks WHERE points_awarded > 0")
    ).scalar()
    with_visitor = conn.execute(
        text("SELECT count(*) FROM referral_tracks WHERE visitor_id IS NOT NULL")
    ).scalar()

    dup_logged_in = conn.execute(
        text(
            """
            SELECT referrer_id, listing_id, visitor_id, count(*) AS cnt,
                   sum(CASE WHEN points_awarded > 0 THEN 1 ELSE 0 END) AS awarded_rows,
                   sum(points_awarded) AS total_points
            FROM referral_tracks
            WHERE visitor_id IS NOT NULL
            GROUP BY referrer_id, listing_id, visitor_id
            HAVING count(*) > 1
            ORDER BY cnt DESC
            LIMIT 25
            """
        )
    ).all()

    dup_anon = conn.execute(
        text(
            """
            SELECT referrer_id, listing_id, visitor_ip, count(*) AS cnt,
                   sum(CASE WHEN points_awarded > 0 THEN 1 ELSE 0 END) AS awarded_rows,
                   sum(points_awarded) AS total_points
            FROM referral_tracks
            WHERE visitor_id IS NULL
            GROUP BY referrer_id, listing_id, visitor_ip
            HAVING count(*) > 1
            ORDER BY cnt DESC
            LIMIT 25
            """
        )
    ).all()

    dup_counts = conn.execute(
        text(
            """
            SELECT
              (SELECT count(*) FROM (
                SELECT 1 FROM referral_tracks
                WHERE visitor_id IS NOT NULL
                GROUP BY referrer_id, listing_id, visitor_id HAVING count(*) > 1
              ) t) AS logged_in_dup_groups,
              (SELECT count(*) FROM (
                SELECT 1 FROM referral_tracks
                WHERE visitor_id IS NULL
                GROUP BY referrer_id, listing_id, visitor_ip HAVING count(*) > 1
              ) t) AS anon_dup_groups
            """
        )
    ).one()

print("=== referral_tracks READ-ONLY AUDIT ===")
print(f"total rows                 : {total}")
print(f"rows with points_awarded>0 : {awarded}")
print(f"rows with visitor_id       : {with_visitor}")
print(f"logged-in duplicate groups : {dup_counts.logged_in_dup_groups}")
print(f"anonymous duplicate groups : {dup_counts.anon_dup_groups}")
print()
if dup_logged_in:
    print("--- logged-in duplicate keys (referrer, listing, visitor) ---")
    for r in dup_logged_in:
        print(
            f"  {r.referrer_id} | {r.listing_id} | {r.visitor_id} "
            f"rows={r.cnt} awarded_rows={r.awarded_rows} points={r.total_points}"
        )
else:
    print("--- no logged-in duplicate keys ---")
print()
if dup_anon:
    print("--- anonymous duplicate keys (referrer, listing, ip) ---")
    for r in dup_anon:
        print(
            f"  {r.referrer_id} | {r.listing_id} | {r.visitor_ip} "
            f"rows={r.cnt} awarded_rows={r.awarded_rows} points={r.total_points}"
        )
else:
    print("--- no anonymous duplicate keys ---")
print()
print("AUDIT COMPLETE (read-only, nothing modified)")
