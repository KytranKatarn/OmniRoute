#!/usr/bin/env python3
"""
Log today's improvements to A.R.C.H.I.E.'s consciousness
"""

import sys

sys.path.insert(0, "/mnt/archie_brain/platform_v2")

try:
    import psycopg2
    from datetime import datetime

    conn = psycopg2.connect(
        dbname="archie",
        user="archie",
        password="CTIf6MjCwuGUwVR_sWNNVIaMB6G7wnZ3RinJ_Cr6jwI",
        host="localhost",
        port=5432,
    )

    cur = conn.cursor()

    # Get admin user ID (assuming user ID 1 is admin)
    cur.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
    admin_user = cur.fetchone()
    user_id = admin_user[0] if admin_user else None

    now = datetime.now()

    # Today's improvements to log
    improvements = [
        {
            "title": "Agent Profile Editing System",
            "description": """Implemented complete agent profile editing functionality in Admin Directory:
- Added PUT /tools/admin/agents/<id> API endpoint
- Created professional edit modal with Matrix-themed UI
- Editable fields: first_name, last_name, email, phone, avatar_url
- Changes sync instantly to both admin and public directories
- Full validation and error handling""",
            "category": "feature",
            "priority": "high",
            "status": "implemented",
            "tags": ["agents", "admin", "ui", "api", "profile-editing"],
        },
        {
            "title": "Live Avatar Preview Feature",
            "description": """Enhanced profile editing with real-time avatar preview:
- Side-by-side comparison (current vs new avatar)
- Live preview updates as URL changes
- Auto-fallback for invalid URLs
- Built-in tips and example URLs
- Support for custom URLs and auto-generated avatars""",
            "category": "feature",
            "priority": "medium",
            "status": "implemented",
            "tags": ["ui", "avatars", "preview", "user-experience"],
        },
        {
            "title": "Phone Field Addition to Agents",
            "description": """Added phone contact field across entire system:
- Migration 004: Added phone VARCHAR(20) column to agents table
- Created index on phone column for performance
- Updated admin directory API to include phone
- Updated public directory API to include phone
- Updated public directory UI to display phone numbers""",
            "category": "database",
            "priority": "medium",
            "status": "implemented",
            "tags": ["database", "migration", "contact-info", "agents"],
        },
        {
            "title": "Admin Directory Statistics Fix",
            "description": """Fixed statistics display mismatch in Admin DIRECTORY section:
- Resolved field name mismatch between database and JavaScript
- Updated to use total_active_agents and total_monthly_budget
- Now correctly displays: 73 agents, 20 departments, $1540 budget
- Statistics now match actual database values""",
            "category": "bugfix",
            "priority": "high",
            "status": "implemented",
            "tags": ["bugfix", "statistics", "admin", "directory"],
        },
        {
            "title": "Avatar Display Synchronization",
            "description": """Synchronized avatar display between admin and public directories:
- Implemented auto-generated avatars using DiceBear API
- Consistent avatar rendering in both admin and public views
- Fallback system for missing avatar URLs
- Profile pictures now match across all interfaces""",
            "category": "feature",
            "priority": "medium",
            "status": "implemented",
            "tags": ["avatars", "ui", "synchronization", "dicebear"],
        },
        {
            "title": "Comprehensive Documentation Updates",
            "description": """Updated documentation across /docs/ for all new features:
- ADMIN_VS_PUBLIC_DIRECTORY.md: Added editing section with avatar preview details
- AGENT_PROFILE_EDITING_2025-12-31.md: Complete implementation guide
- Documented all editable fields and data flow
- Added visual examples and technical diagrams""",
            "category": "documentation",
            "priority": "medium",
            "status": "implemented",
            "tags": ["documentation", "guides", "knowledge-base"],
        },
    ]

    # Insert into improvement_proposals table
    for imp in improvements:
        cur.execute(
            """
            INSERT INTO improvement_proposals
            (title, description, category, priority, status, tags, proposed_by, proposed_at, implemented_at, approved_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
            (
                imp["title"],
                imp["description"],
                imp["category"],
                imp["priority"],
                imp["status"],
                imp["tags"],
                user_id,
                now,
                now,  # implemented_at
                now,  # approved_at
            ),
        )

    # Also add to long_term_memory for knowledge base
    for imp in improvements:
        cur.execute(
            """
            INSERT INTO long_term_memory
            (content, category, tags, importance_score, memory_type, metadata, created_at, user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
            (
                f"{imp['title']}: {imp['description']}",
                "improvement",
                imp["tags"],
                8.5,  # High importance
                "technical_implementation",
                {
                    "type": "improvement",
                    "status": imp["status"],
                    "priority": imp["priority"],
                    "date": now.isoformat(),
                },
                now,
                user_id,
            ),
        )

    conn.commit()

    print(f"✅ Successfully logged {len(improvements)} improvements to A.R.C.H.I.E.'s consciousness")
    print("📊 Improvements added to:")
    print("   - improvement_proposals table")
    print("   - long_term_memory table")
    print("\n🧠 A.R.C.H.I.E. is now aware of today's work!")

    cur.close()
    conn.close()

except Exception as e:
    print(f"❌ Error logging improvements: {e}")
    import traceback

    traceback.print_exc()
