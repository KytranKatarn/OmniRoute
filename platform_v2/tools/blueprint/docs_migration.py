#!/usr/bin/env python3
"""
Docs Migration Script — Migrate /docs/ markdown files to knowledge_base table.

Phase 1 of Database-Centric Consolidation.
Run inside Docker: docker exec archie_platform python3 /app/tools/blueprint/docs_migration.py

Creates a UNIQUE index on title, then upserts each .md file as a knowledge_base entry
with knowledge_type='vault_note', source_type='docs_migration'.
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

# Add parent paths for imports
sys.path.insert(0, "/app")
from database import get_db

# Directories to scan
DOCS_DIR = "/mnt/archie_brain/docs"
ARCHIVE_DIR = os.path.join(DOCS_DIR, "archive")
PLANS_DIR = os.path.join(DOCS_DIR, "plans")

# Category mapping based on filename keywords
CATEGORY_MAP = {
    "architecture": [
        "ARCHITECTURE",
        "BRIDGE_STATION",
        "MESH_NETWORK",
        "MULTI_AGENT",
        "DIRECTORY_AND_SAAS",
        "DATABASE_SCHEMA",
    ],
    "operations": [
        "DEPLOYMENT",
        "BACKUP",
        "SYSTEM_OPERATIONS",
        "RECOVERY",
        "MAINTENANCE",
        "CHECKLIST",
        "MONITORING",
    ],
    "guide": [
        "GUIDE",
        "REFERENCE",
        "QUICK_REFERENCE",
        "DOCUMENTATION_INDEX",
        "README",
        "COMPLETE_GUIDE",
    ],
    "team": ["AGENT", "TEAM", "STAFFING", "HR_DASHBOARD", "DELEGATION"],
    "planning": ["ROADMAP", "PLAN", "PHASE", "FUTURE", "STATUS", "CHANGELOG"],
    "module_docs": [
        "MODULE",
        "BLUEPRINT",
        "CONSCIOUSNESS",
        "POOL",
        "BUILDER",
        "SENTINEL",
        "CODERABBIT",
        "VAULT",
    ],
    "historical": [
        "IMPROVEMENT",
        "OPTIMIZATION",
        "SUMMARY",
        "SESSION_HANDOFF",
        "IMPLEMENTATION_STATUS",
    ],
}

# Importance scores by category
IMPORTANCE_SCORES = {
    "architecture": 0.90,
    "operations": 0.85,
    "guide": 0.85,
    "team": 0.80,
    "planning": 0.75,
    "module_docs": 0.80,
    "historical": 0.60,
    "general": 0.70,
    "archived": 0.40,
}


def classify_category(filename: str) -> str:
    """Derive category from filename keywords."""
    upper = filename.upper().replace(".MD", "")
    for category, keywords in CATEGORY_MAP.items():
        for kw in keywords:
            if kw in upper:
                return category
    return "general"


def extract_tags(filename: str) -> list:
    """Extract tags from filename parts."""
    name = filename.replace(".md", "").replace(".MD", "")
    parts = [p.lower() for p in name.split("_") if len(p) > 2]
    # Deduplicate while preserving order
    seen = set()
    tags = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            tags.append(p)
    return tags


def get_preview(content: str, max_len: int = 300) -> str:
    """Extract a text preview from markdown content."""
    lines = content.split("\n")
    text_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("---"):
            text_lines.append(stripped)
        if len(" ".join(text_lines)) >= max_len:
            break
    return " ".join(text_lines)[:max_len]


def collect_files() -> list:
    """Collect all .md files from docs directory and subdirectories."""
    files = []

    # Main docs directory
    if os.path.exists(DOCS_DIR):
        for fname in sorted(os.listdir(DOCS_DIR)):
            fpath = os.path.join(DOCS_DIR, fname)
            if fname.endswith(".md") and os.path.isfile(fpath):
                files.append(
                    {
                        "path": fpath,
                        "filename": fname,
                        "is_archived": False,
                        "subfolder": None,
                    }
                )

    # Archive subdirectory
    if os.path.exists(ARCHIVE_DIR):
        for fname in sorted(os.listdir(ARCHIVE_DIR)):
            fpath = os.path.join(ARCHIVE_DIR, fname)
            if fname.endswith(".md") and os.path.isfile(fpath):
                files.append(
                    {
                        "path": fpath,
                        "filename": fname,
                        "is_archived": True,
                        "subfolder": "archive",
                    }
                )

    # Plans subdirectory
    if os.path.exists(PLANS_DIR):
        for fname in sorted(os.listdir(PLANS_DIR)):
            fpath = os.path.join(PLANS_DIR, fname)
            if fname.endswith(".md") and os.path.isfile(fpath):
                files.append(
                    {
                        "path": fpath,
                        "filename": fname,
                        "is_archived": False,
                        "subfolder": "plans",
                    }
                )

    return files


def run_migration():
    """Execute the docs-to-knowledge_base migration."""
    print("=" * 60)
    print("A.R.C.H.I.E. Docs Migration — Phase 1")
    print("=" * 60)

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Step 1: Ensure UNIQUE index on title
    print("\n[1/3] Creating unique index on knowledge_base(title)...")
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_title_unique
        ON knowledge_base(title) WHERE title IS NOT NULL;
    """
    )
    conn.commit()
    print("  ✓ Index ready")

    # Step 2: Collect files
    print("\n[2/3] Scanning docs directory...")
    files = collect_files()
    print(f"  Found {len(files)} markdown files")

    # Step 3: Upsert each file
    print("\n[3/3] Migrating to knowledge_base...")
    migrated = 0
    updated = 0
    errors = 0

    for finfo in files:
        try:
            with open(finfo["path"], "r", encoding="utf-8") as f:
                content = f.read()

            stat = os.stat(finfo["path"])
            filename = finfo["filename"]
            title = filename.replace(".md", "").replace("_", " ")

            is_archived = finfo["is_archived"]
            category = "archived" if is_archived else classify_category(filename)
            importance = IMPORTANCE_SCORES.get(category, 0.70)
            tags = extract_tags(filename)

            if finfo["subfolder"]:
                tags.append(finfo["subfolder"])

            metadata = {
                "original_path": finfo["path"],
                "filename": filename,
                "file_size": stat.st_size,
                "file_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "is_archived": is_archived,
                "subfolder": finfo["subfolder"],
                "preview": get_preview(content),
                "migrated_at": datetime.now().isoformat(),
            }

            cur.execute(
                """
                INSERT INTO knowledge_base (
                    knowledge_type, title, content, category, tags,
                    memory_metadata, importance_score, source_type, source_id,
                    created_at, updated_at, indexed_at
                ) VALUES (
                    'vault_note', %s, %s, %s, %s,
                    %s, %s, 'docs_migration', %s,
                    %s, NOW(), NOW()
                )
                ON CONFLICT (title) WHERE title IS NOT NULL
                DO UPDATE SET
                    content = EXCLUDED.content,
                    category = EXCLUDED.category,
                    tags = EXCLUDED.tags,
                    memory_metadata = EXCLUDED.memory_metadata,
                    importance_score = EXCLUDED.importance_score,
                    updated_at = NOW()
                RETURNING (xmax = 0) AS is_insert
            """,
                (
                    title,
                    content,
                    category,
                    tags,
                    json.dumps(metadata),
                    importance,
                    finfo["path"],
                    datetime.fromtimestamp(stat.st_mtime),
                ),
            )

            result = cur.fetchone()
            if result and result["is_insert"]:
                migrated += 1
            else:
                updated += 1

        except Exception as e:
            errors += 1
            print(f"  ✗ Error migrating {finfo['filename']}: {e}")

    conn.commit()

    # Summary
    print(f"\n{'=' * 60}")
    print(f"Migration Complete!")
    print(f"  New entries:     {migrated}")
    print(f"  Updated entries: {updated}")
    print(f"  Errors:          {errors}")
    print(f"  Total processed: {len(files)}")

    # Verify
    cur.execute(
        """
        SELECT source_type, COUNT(*) as cnt
        FROM knowledge_base
        WHERE source_type = 'docs_migration'
        GROUP BY source_type
    """
    )
    verify = cur.fetchone()
    if verify:
        print(f"\n  Verification: {verify['cnt']} docs_migration entries in knowledge_base")
    else:
        print("\n  ⚠ No docs_migration entries found — check for errors above")

    # Category breakdown
    cur.execute(
        """
        SELECT category, COUNT(*) as cnt
        FROM knowledge_base
        WHERE source_type = 'docs_migration'
        GROUP BY category
        ORDER BY cnt DESC
    """
    )
    print("\n  Category breakdown:")
    for row in cur.fetchall():
        print(f"    {row['category']}: {row['cnt']}")

    cur.close()
    conn.close()
    print(f"\n{'=' * 60}")


if __name__ == "__main__":
    run_migration()
