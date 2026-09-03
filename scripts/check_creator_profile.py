"""Quick dev check for creator profiles."""
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
user_id = sys.argv[1] if len(sys.argv) > 1 else "5355b584-3809-4db1-bd32-5bdfc31e7b61"
engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as conn:
    rows = conn.execute(
        text(
            """
            SELECT id, name, app_user_id, role, skills, industry, location,
                   why_im_here, linked_in_profile_url, is_approved, is_deleted, deleted_at
            FROM community
            WHERE app_user_id = :uid
            ORDER BY is_deleted, updated_at DESC
            """
        ),
        {"uid": user_id},
    ).fetchall()
    print("profile_rows", len(rows))
    for row in rows:
        print(dict(row._mapping))

    users = conn.execute(
        text("SELECT id, email FROM users WHERE email ILIKE '%cobrother%' LIMIT 10")
    ).fetchall()
    print("users", len(users))
    for row in users:
        print(dict(row._mapping))
