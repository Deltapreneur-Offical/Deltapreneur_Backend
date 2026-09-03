"""One-off: re-link orphaned registration orders to current users by buyer_email.

Only touches orders whose buyer_id no longer matches any user AND whose
buyer_email matches exactly one existing user. Prints every change.
(Safe to delete after running.)
"""
import asyncio

import asyncpg

DSN = "postgresql://cobrotherpython:Aultum12345@database-1.cno8smi8qae3.ap-south-1.rds.amazonaws.com:5432/postgres"


async def main() -> None:
    conn = await asyncpg.connect(DSN)

    candidates = await conn.fetch(
        """
        SELECT o.id, o.domain_name || o.domain_extension AS fqdn, o.buyer_id AS old_buyer_id,
               o.buyer_email, u.id AS new_buyer_id, u.email AS new_email
        FROM domain_registration_orders o
        JOIN users u ON lower(u.email) = lower(o.buyer_email)
        LEFT JOIN users old_u ON old_u.id = o.buyer_id
        WHERE old_u.id IS NULL
        ORDER BY o.created_at
        """
    )
    print(f"Orphaned orders with a matching current user: {len(candidates)}")
    for r in candidates:
        print(
            f"  {r['fqdn']}: old buyer {r['old_buyer_id']} -> new buyer {r['new_buyer_id']} ({r['new_email']})"
        )

    if not candidates:
        print("Nothing to relink.")
        await conn.close()
        return

    async with conn.transaction():
        for r in candidates:
            await conn.execute(
                "UPDATE domain_registration_orders SET buyer_id = $1 WHERE id = $2",
                r["new_buyer_id"],
                r["id"],
            )
    print("Relinked", len(candidates), "orders.")

    remaining = await conn.fetch(
        """
        SELECT o.domain_name || o.domain_extension AS fqdn, o.buyer_email, o.status
        FROM domain_registration_orders o
        LEFT JOIN users u ON u.id = o.buyer_id
        WHERE u.id IS NULL
        ORDER BY o.created_at DESC
        """
    )
    print(f"\nStill orphaned (no current user with that email): {len(remaining)}")
    for r in remaining:
        print(f"  {r['fqdn']} — {r['buyer_email']} ({r['status']})")

    await conn.close()


asyncio.run(main())
