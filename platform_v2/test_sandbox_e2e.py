#!/usr/bin/env python3
"""
End-to-End Sandbox Testing Script
Tests the complete proposal → sandbox → testing → deployment workflow
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
from datetime import datetime

def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'archie_database'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', 'password')
    )

def print_section(title):
    """Print a section header"""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")

def test_current_sandboxes():
    """Check all active sandboxes"""
    print_section("1. CURRENT SANDBOX STATUS")

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Get all sandboxes
    cur.execute("""
        SELECT
            si.id,
            si.proposal_id,
            si.sandbox_type,
            si.schema_name,
            si.container_id,
            si.status,
            si.created_at,
            si.destroyed_at,
            ip.title as proposal_title,
            ip.status as proposal_status,
            ip.priority
        FROM sandbox_instances si
        LEFT JOIN improvement_proposals ip ON si.proposal_id = ip.id
        ORDER BY si.created_at DESC
        LIMIT 10
    """)

    sandboxes = cur.fetchall()

    if not sandboxes:
        print("❌ No sandboxes found in database")
    else:
        print(f"Found {len(sandboxes)} sandbox instance(s):\n")
        for sb in sandboxes:
            status_icon = "🟢" if sb['destroyed_at'] is None else "🔴"
            print(f"{status_icon} Sandbox #{sb['id']}")
            print(f"   Proposal: #{sb['proposal_id']} - {sb['proposal_title']}")
            print(f"   Type: {sb['sandbox_type']}")
            print(f"   Schema: {sb['schema_name']}")
            print(f"   Status: {sb['status']}")
            print(f"   Created: {sb['created_at']}")
            print(f"   Destroyed: {sb['destroyed_at'] or 'Still Active'}")
            print()

    # Count active sandboxes
    active_sandboxes = [s for s in sandboxes if s['destroyed_at'] is None]
    print(f"📊 Active sandboxes: {len(active_sandboxes)}")
    print(f"📊 Destroyed sandboxes: {len(sandboxes) - len(active_sandboxes)}")

    cur.close()
    conn.close()

    return active_sandboxes

def test_sandbox_schemas():
    """Check which sandbox schemas exist in the database"""
    print_section("2. DATABASE SCHEMAS")

    conn = get_db()
    cur = conn.cursor()

    # Get all schemas
    cur.execute("""
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name LIKE 'sandbox%'
        ORDER BY schema_name
    """)

    schemas = cur.fetchall()

    if not schemas:
        print("❌ No sandbox schemas found")
    else:
        print(f"Found {len(schemas)} sandbox schema(s):\n")
        for schema in schemas:
            schema_name = schema[0]

            # Count tables in schema
            cur.execute(f"""
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = %s
            """, (schema_name,))
            table_count = cur.fetchone()[0]

            print(f"🗄️  {schema_name}")
            print(f"   Tables: {table_count}")
            print()

    cur.close()
    conn.close()

    return schemas

def test_queue_status():
    """Check the sandbox queue"""
    print_section("3. SANDBOX QUEUE STATUS")

    from sandbox_queue import get_queue_status

    status = get_queue_status()

    print(f"Sandbox in use: {'✅ YES' if status['sandbox_in_use'] else '❌ NO'}")
    print()

    if status['current_proposal']:
        cp = status['current_proposal']
        print("🧪 CURRENT PROPOSAL IN SANDBOX:")
        print(f"   Proposal #{cp['proposal_id']}: {cp['title']}")
        print(f"   Status: {cp['sandbox_status']}")
        print(f"   Priority: {cp['priority']}")
        print(f"   Category: {cp['category']}")
        print()

    print(f"Queue length: {status['queue_length']}")

    if status['queue']:
        print("\n⏳ WAITING IN QUEUE:\n")
        for idx, q in enumerate(status['queue'], 1):
            hours = int(q['hours_waiting'])
            minutes = int((q['hours_waiting'] % 1) * 60)
            print(f"   #{idx}. Proposal #{q['id']}")
            print(f"       Title: {q['title']}")
            print(f"       Priority: {q['priority']}")
            print(f"       Waiting: {hours}h {minutes}m")
            print()

def test_proposal_details():
    """Show details of proposals"""
    print_section("4. APPROVED PROPOSALS")

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Get approved proposals
    cur.execute("""
        SELECT
            id,
            title,
            status,
            priority,
            category,
            approved_at,
            team_size
        FROM improvement_proposals
        WHERE status IN ('approved', 'in_progress', 'testing')
        ORDER BY priority, approved_at
        LIMIT 5
    """)

    proposals = cur.fetchall()

    if not proposals:
        print("❌ No approved proposals found")
    else:
        print(f"Found {len(proposals)} approved proposal(s):\n")
        for p in proposals:
            print(f"📋 Proposal #{p['id']}: {p['title']}")
            print(f"   Status: {p['status']}")
            print(f"   Priority: {p['priority']}")
            print(f"   Category: {p['category']}")
            print(f"   Team Size: {p['team_size']}")
            print(f"   Approved: {p['approved_at']}")
            print()

    cur.close()
    conn.close()

    return proposals

def test_sandbox_connectivity(schema_name):
    """Test if we can connect to a sandbox schema"""
    print_section(f"5. TESTING SANDBOX CONNECTIVITY: {schema_name}")

    conn = get_db()
    cur = conn.cursor()

    try:
        # Set search path to sandbox schema
        cur.execute(f"SET search_path TO {schema_name}, public")
        print(f"✅ Successfully set search_path to {schema_name}")

        # Count tables in sandbox
        cur.execute("""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = %s
        """, (schema_name,))
        table_count = cur.fetchone()[0]
        print(f"✅ Found {table_count} tables in sandbox schema")

        # Test query on sandbox data
        cur.execute("""
            SELECT COUNT(*)
            FROM improvement_proposals
        """)
        proposal_count = cur.fetchone()[0]
        print(f"✅ Found {proposal_count} improvement_proposals in sandbox")

        # List some tables
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
            ORDER BY table_name
            LIMIT 10
        """, (schema_name,))
        tables = cur.fetchall()
        print(f"\n📋 Sample tables in {schema_name}:")
        for table in tables:
            print(f"   - {table[0]}")

        cur.close()
        conn.close()

        return True

    except Exception as e:
        print(f"❌ Error testing sandbox connectivity: {e}")
        cur.close()
        conn.close()
        return False

def cleanup_old_sandboxes():
    """Clean up destroyed sandboxes and orphaned schemas"""
    print_section("6. CLEANUP CHECK")

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Find destroyed sandboxes with schemas that still exist
    cur.execute("""
        SELECT
            id,
            proposal_id,
            schema_name,
            status,
            destroyed_at
        FROM sandbox_instances
        WHERE destroyed_at IS NOT NULL
        AND schema_name IS NOT NULL
        ORDER BY destroyed_at DESC
    """)

    destroyed = cur.fetchall()

    if not destroyed:
        print("✅ No destroyed sandboxes to clean up")
    else:
        print(f"Found {len(destroyed)} destroyed sandbox(es):\n")
        for sb in destroyed:
            print(f"🔴 Sandbox #{sb['id']} (Destroyed)")
            print(f"   Schema: {sb['schema_name']}")
            print(f"   Destroyed: {sb['destroyed_at']}")

            # Check if schema still exists
            cur.execute("""
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name = %s
            """, (sb['schema_name'],))

            if cur.fetchone():
                print(f"   ⚠️  Schema still exists - needs cleanup!")
            else:
                print(f"   ✅ Schema properly removed")
            print()

    cur.close()
    conn.close()

def main():
    """Run all tests"""
    print("""
╔════════════════════════════════════════════════════════════════════════════╗
║                    SANDBOX END-TO-END TEST SUITE                           ║
║                                                                            ║
║  This script tests the complete sandbox workflow:                         ║
║  1. Check current sandbox status                                          ║
║  2. Verify database schemas                                               ║
║  3. Check queue system                                                    ║
║  4. Review proposals                                                      ║
║  5. Test sandbox connectivity                                             ║
║  6. Cleanup check                                                         ║
╚════════════════════════════════════════════════════════════════════════════╝
    """)

    try:
        # Run all tests
        active_sandboxes = test_current_sandboxes()
        schemas = test_sandbox_schemas()
        test_queue_status()
        proposals = test_proposal_details()

        # Test connectivity to active sandbox
        if active_sandboxes:
            for sb in active_sandboxes:
                if sb['schema_name']:
                    test_sandbox_connectivity(sb['schema_name'])

        cleanup_old_sandboxes()

        print_section("TEST SUMMARY")
        print(f"✅ Active Sandboxes: {len(active_sandboxes)}")
        print(f"✅ Database Schemas: {len(schemas)}")
        print(f"✅ Approved Proposals: {len(proposals) if proposals else 0}")
        print("\n🎉 End-to-end test completed!")

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
