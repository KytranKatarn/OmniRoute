#!/usr/bin/env python3
"""
Cleanup Orphaned Sandbox Schemas
Removes database schemas for destroyed sandboxes
"""

import psycopg2
import os
from database import _get_db_password


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def cleanup_orphaned_schemas():
    """Remove sandbox schemas that belong to destroyed sandboxes"""
    conn = get_db()
    cur = conn.cursor()

    print("🔍 Finding orphaned sandbox schemas...")

    # Get all sandbox schemas
    cur.execute(
        """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name LIKE 'sandbox%'
        ORDER BY schema_name
    """
    )

    all_schemas = [row[0] for row in cur.fetchall()]
    print(f"📊 Found {len(all_schemas)} sandbox schema(s) in database")

    # Get active sandboxes
    cur.execute(
        """
        SELECT DISTINCT schema_name
        FROM sandbox_instances
        WHERE destroyed_at IS NULL
        AND schema_name IS NOT NULL
    """
    )

    active_schemas = [row[0] for row in cur.fetchall()]
    print(f"🟢 Found {len(active_schemas)} active sandbox schema(s)")
    for schema in active_schemas:
        print(f"   ✓ {schema} (active - keeping)")

    # Find orphaned schemas
    orphaned_schemas = [s for s in all_schemas if s not in active_schemas]

    if not orphaned_schemas:
        print("\n✅ No orphaned schemas to clean up!")
        cur.close()
        conn.close()
        return

    print(f"\n🔴 Found {len(orphaned_schemas)} orphaned schema(s) to remove:")
    for schema in orphaned_schemas:
        print(f"   × {schema}")

    print("\n⚠️  Starting cleanup...")

    # Drop each orphaned schema
    cleaned = 0
    failed = 0

    for schema_name in orphaned_schemas:
        try:
            print(f"Dropping schema: {schema_name}...", end=" ")
            cur.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
            conn.commit()
            print("✅ DONE")
            cleaned += 1
        except Exception as e:
            print(f"❌ FAILED: {e}")
            failed += 1
            conn.rollback()

    cur.close()
    conn.close()

    print(f"\n{'='*80}")
    print("CLEANUP COMPLETE")
    print(f"{'='*80}")
    print(f"✅ Schemas removed: {cleaned}")
    print(f"❌ Schemas failed: {failed}")
    print(f"🟢 Active schemas kept: {len(active_schemas)}")


if __name__ == "__main__":
    cleanup_orphaned_schemas()
