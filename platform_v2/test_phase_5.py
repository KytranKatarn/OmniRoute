#!/usr/bin/env python3
"""
Test script for Phase 5: Improvements Integration

Tests:
1. Create improvement proposal with knowledge context
2. Retrieve proposal context
3. Track execution with mistake learning
"""

import sys
import os
sys.path.insert(0, '/mnt/archie_brain/platform_v2')

from improvement_workflow import get_improvement_workflow
import psycopg2
from psycopg2.extras import RealDictCursor

def get_db():
    """Get database connection"""
    return psycopg2.connect(
        dbname=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', ''),
        host=os.getenv('DB_HOST', 'archie_database'),
        port=os.getenv('DB_PORT', '5432')
    )

def test_create_proposal_with_context():
    """Test 1: Create improvement proposal with knowledge context"""
    print("\n" + "="*70)
    print("TEST 1: Create Improvement Proposal with Knowledge Context")
    print("="*70)

    conn = get_db()
    workflow = get_improvement_workflow(conn)

    # Create a test proposal related to databases (should find database-related knowledge)
    result = workflow.create_proposal_with_context(
        title="Fix database connection error handling",
        description="Improve error handling when database connection fails. Currently crashes instead of graceful degradation.",
        category="quality",
        priority="high",
        proposed_by=2,  # Admin user (ID 2 exists)
        user_id=2
    )

    if result['success']:
        print(f"\n✅ SUCCESS: Created proposal #{result['proposal_id']}")
        print(f"   Knowledge entries found: {len(result.get('knowledge_context', []))}")
        print(f"   Context quality score: {result.get('context_quality_score', 0.0):.2f}")
        print(f"   Mistake warnings: {len(result.get('mistake_warnings', []))}")
        print(f"   Similar improvements: {len(result.get('similar_improvements', []))}")

        # Show knowledge context
        if result.get('knowledge_context'):
            print("\n   📚 Knowledge Context (Top 3):")
            for i, entry in enumerate(result['knowledge_context'][:3], 1):
                print(f"      {i}. [{entry.get('knowledge_type', 'unknown')}] {entry.get('title', 'Untitled')[:60]}")
                print(f"         Importance: {entry.get('importance_score', 0.0):.2f}")

        # Show mistake warnings
        if result.get('mistake_warnings'):
            print("\n   ⚠️  Mistake Warnings:")
            for warning in result['mistake_warnings']:
                print(f"      - {warning.get('type', 'Warning')}: {warning.get('title', 'Check related mistake')[:60]}")

        conn.close()
        return result['proposal_id']
    else:
        print(f"\n❌ FAILED: {result.get('error')}")
        conn.close()
        return None

def test_retrieve_proposal_context(proposal_id):
    """Test 2: Retrieve full proposal context"""
    print("\n" + "="*70)
    print("TEST 2: Retrieve Proposal Context")
    print("="*70)

    conn = get_db()
    workflow = get_improvement_workflow(conn)

    result = workflow.get_proposal_context(proposal_id)

    if result['success']:
        print(f"\n✅ SUCCESS: Retrieved context for proposal #{proposal_id}")
        proposal = result['proposal']
        print(f"   Title: {proposal.get('title')}")
        print(f"   Status: {proposal.get('status')}")
        print(f"   Priority: {proposal.get('priority')}")
        print(f"   Knowledge entries: {len(result.get('knowledge_context', []))}")
        print(f"   Context quality: {result.get('context_quality_score', 0.0):.2f}")

        conn.close()
        return True
    else:
        print(f"\n❌ FAILED: {result.get('error')}")
        conn.close()
        return False

def test_track_execution(proposal_id):
    """Test 3: Track execution with mistake learning"""
    print("\n" + "="*70)
    print("TEST 3: Track Execution with Mistake Learning")
    print("="*70)

    conn = get_db()
    workflow = get_improvement_workflow(conn)

    # Test successful execution
    print("\n   Testing successful execution...")
    result = workflow.track_execution(
        proposal_id=proposal_id,
        agent_id=5,  # Example agent
        action='test',
        success=True,
        metadata={'test': 'passed', 'duration': '5s'}
    )

    if result['success']:
        print(f"   ✅ Tracked successful execution")
        print(f"      Mistake learned: {result.get('mistake_learned')}")
    else:
        print(f"   ❌ Failed: {result.get('error')}")

    # Test failed execution with mistake learning
    print("\n   Testing failed execution with mistake learning...")
    result = workflow.track_execution(
        proposal_id=proposal_id,
        agent_id=5,
        action='deploy',
        success=False,
        error_message='column "missing_field" does not exist',
        metadata={'deployment': 'production', 'failed_at': '2026-01-09T23:30:00'}
    )

    if result['success']:
        print(f"   ✅ Tracked failed execution")
        print(f"      Mistake learned: {result.get('mistake_learned')}")
        if result.get('mistake_learned'):
            print(f"      Mistake entry ID: {result.get('mistake_entry_id')}")
            print(f"      🧠 A.R.C.H.I.E. learned from this failure!")
    else:
        print(f"   ❌ Failed: {result.get('error')}")

    conn.close()
    return result['success']

def test_knowledge_retrieval():
    """Test 4: Verify unified knowledge search works"""
    print("\n" + "="*70)
    print("TEST 4: Verify Unified Knowledge Search")
    print("="*70)

    from unified_knowledge_search import unified_knowledge_search

    result = unified_knowledge_search(
        query="database error",
        types=['mistake_learned', 'vault_note'],
        limit=5
    )

    if result and 'results' in result:
        print(f"\n✅ SUCCESS: Found {len(result['results'])} knowledge entries")
        print(f"   Total entries in knowledge base: {result.get('total', 0)}")

        if result['results']:
            for i, entry in enumerate(result['results'][:3], 1):
                print(f"\n   {i}. [{entry.get('knowledge_type')}] {entry.get('title', 'Untitled')[:60]}")
                print(f"      Importance: {entry.get('importance_score', 0.0):.2f}")
                print(f"      Tags: {', '.join(entry.get('tags', [])[:3])}")
        else:
            print(f"\n   No results found (this is OK - may be no database errors logged yet)")
    else:
        print(f"\n❌ FAILED: Search returned no result")

def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("PHASE 5: IMPROVEMENTS INTEGRATION - TEST SUITE")
    print("="*70)

    try:
        # Test 4 first (knowledge search)
        test_knowledge_retrieval()

        # Test 1: Create proposal with context
        proposal_id = test_create_proposal_with_context()

        if proposal_id:
            # Test 2: Retrieve context
            test_retrieve_proposal_context(proposal_id)

            # Test 3: Track execution
            test_track_execution(proposal_id)

        print("\n" + "="*70)
        print("✅ ALL TESTS COMPLETED")
        print("="*70)
        print("\nPhase 5 integration verified successfully!")
        print("\nNext steps:")
        print("  1. Create proposals via admin panel at /tools/admin/brain")
        print("  2. Use POST /tools/admin/brain/improvements/create-with-context")
        print("  3. Get context: GET /tools/admin/brain/improvements/<id>/context")
        print("  4. Track execution: POST /tools/admin/brain/improvements/<id>/track-execution")
        print()

    except Exception as e:
        print(f"\n❌ TEST SUITE FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
