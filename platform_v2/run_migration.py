#!/usr/bin/env python3
"""Run database migration to add phone field"""

import sys
sys.path.insert(0, '/mnt/archie_brain/platform_v2')

from app import get_db

def run_migration():
    try:
        conn = get_db()
        cur = conn.cursor()

        # Read migration file
        with open('/mnt/archie_brain/platform_v2/migrations/004_add_agent_phone.sql', 'r') as f:
            migration_sql = f.read()

        # Execute migration
        cur.execute(migration_sql)
        conn.commit()

        print("✅ Migration 004 completed successfully - phone field added to agents table")

        cur.close()
        conn.close()

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    run_migration()
