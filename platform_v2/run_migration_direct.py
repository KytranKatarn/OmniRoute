#!/usr/bin/env python3
"""Run database migration directly"""

try:
    import psycopg2

    # Connect to database
    conn = psycopg2.connect(
        dbname='archie_brain',
        user='archie_user',
        password='ArchieSecurePass2024!',
        host='localhost',
        port=5432
    )

    cur = conn.cursor()

    # Run migration
    print("Running migration...")

    cur.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS phone VARCHAR(20);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_agents_phone ON agents(phone);")

    conn.commit()

    print("✅ Migration completed successfully - phone field added to agents table")

    cur.close()
    conn.close()

except ImportError:
    print("❌ psycopg2 not available. Trying alternative method...")
    import subprocess

    # Try using psql command directly
    sql = "ALTER TABLE agents ADD COLUMN IF NOT EXISTS phone VARCHAR(20); CREATE INDEX IF NOT EXISTS idx_agents_phone ON agents(phone);"

    result = subprocess.run(
        ['psql', '-U', 'archie_user', '-d', 'archie_brain', '-c', sql],
        env={'PGPASSWORD': 'ArchieSecurePass2024!'},
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print("✅ Migration completed successfully")
        print(result.stdout)
    else:
        print("❌ Migration failed:")
        print(result.stderr)

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
