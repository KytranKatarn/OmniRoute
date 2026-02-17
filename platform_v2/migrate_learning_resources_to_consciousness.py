#!/usr/bin/env python3
"""
Migrate Learning Resources to A.R.C.H.I.E.'s Consciousness
Syncs knowledge_base (GitHub repos) to long_term_memory for better awareness
"""

import psycopg2
from datetime import datetime
import json

# Database connection
conn = psycopg2.connect(
    dbname="archie",
    user="archie",
    password="CTIf6MjCwuGUwVR_sWNNVIaMB6G7wnZ3RinJ_Cr6jwI",
    host="archie_database",
    port=5432,
)

cur = conn.cursor()

# Get admin user ID
cur.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
admin_user = cur.fetchone()
user_id = admin_user[0] if admin_user else None

now = datetime.now()

print("📚 Migrating Learning Resources to A.R.C.H.I.E.'s Consciousness...")
print("=" * 70)

# Get repository summary
cur.execute(
    """
    SELECT
        repo_type,
        COUNT(*) as file_count,
        COUNT(*) FILTER (WHERE is_documentation = true) as docs,
        COUNT(*) FILTER (WHERE is_code = true) as code_files
    FROM knowledge_base
    GROUP BY repo_type
    ORDER BY COUNT(*) DESC
"""
)

repos = cur.fetchall()

migrated_count = 0

for repo in repos:
    repo_type, file_count, docs, code_files = repo

    # Create a summary entry in long_term_memory for each repository
    content = f"""Learning Resource Repository: {repo_type}

Files Indexed: {file_count}
- Documentation: {docs}
- Code Files: {code_files}

This external GitHub repository has been cloned and indexed for A.R.C.H.I.E.'s learning and reference.
"""

    # Determine category and tags based on repo type
    category_map = {
        "ai-agents": "ai_examples",
        "prompts": "prompts_library",
        "n8n": "automation_workflows",
        "python-basics": "programming_tutorials",
        "python-iot": "programming_tutorials",
        "python-compiler": "programming_tutorials",
        "python-practice": "programming_tutorials",
        "python-programs": "programming_tutorials",
        "python-testing": "programming_tutorials",
        "python-tutorials": "programming_tutorials",
        "python-database": "programming_tutorials",
    }

    tags_map = {
        "ai-agents": ["learning-resource", "ai-agents", "examples", "github"],
        "prompts": ["learning-resource", "system-prompts", "ai-models", "github"],
        "n8n": ["learning-resource", "n8n", "automation", "workflows", "github"],
        "python-basics": [
            "learning-resource",
            "python",
            "programming",
            "basics",
            "github",
        ],
        "python-iot": ["learning-resource", "python", "iot", "dataloggers", "github"],
        "python-compiler": [
            "learning-resource",
            "python",
            "compiler",
            "llvm",
            "github",
        ],
        "python-practice": [
            "learning-resource",
            "python",
            "practice",
            "examples",
            "github",
        ],
        "python-programs": [
            "learning-resource",
            "python",
            "programs",
            "examples",
            "github",
        ],
        "python-testing": ["learning-resource", "python", "testing", "github"],
        "python-tutorials": ["learning-resource", "python", "tutorials", "github"],
        "python-database": ["learning-resource", "python", "database", "github"],
    }

    category = category_map.get(repo_type, "learning_resource")
    tags = tags_map.get(repo_type, ["learning-resource", "github"])

    # Insert into long_term_memory
    metadata = json.dumps(
        {
            "type": "github_repository",
            "repo_type": repo_type,
            "file_count": file_count,
            "docs_count": docs,
            "code_files": code_files,
            "indexed_date": now.isoformat(),
        }
    )

    cur.execute(
        """
        INSERT INTO long_term_memory
        (content, category, tags, importance_score, memory_type, metadata, created_at, user_id)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
        ON CONFLICT DO NOTHING
    """,
        (
            content,
            category,
            tags,
            8.0,  # High importance
            "external_resource",
            metadata,
            now,
            user_id,
        ),
    )

    migrated_count += 1
    print(f"✓ {repo_type:20s} - {file_count:4d} files ({docs:3d} docs, {code_files:3d} code)")

conn.commit()

print("=" * 70)
print(f"✅ Successfully migrated {migrated_count} learning repositories to consciousness")
print(f"🧠 A.R.C.H.I.E. is now aware of {migrated_count} external learning resources!")
print()
print("📊 Total Knowledge Indexed:")
cur.execute("SELECT COUNT(*) FROM knowledge_base")
kb_total = cur.fetchone()[0]
print(f"   - {kb_total:,} files from GitHub repositories")
print(f"   - {migrated_count} repository summaries in long_term_memory")

cur.close()
conn.close()
