#!/usr/bin/env python3
"""
Comprehensive Documentation Ingestion Script
Scans all documentation files and ingests them into A.R.C.H.I.E.'s knowledge base
with intelligent tagging and categorization.
"""

import os
import sys
import psycopg2
import psycopg2.extras
from datetime import datetime
import re

# Add platform to path
sys.path.insert(0, "/mnt/archie_brain/platform_v2")


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host="localhost",
        port=5432,
        user="archie",
        password="archie_secure_pass_2024",
        database="archie",
    )


def extract_tags_from_filename(filename):
    """Extract tags from filename"""
    # Remove extension and split by underscores
    name = os.path.splitext(filename)[0]
    parts = name.lower().split("_")

    # Common tag mappings
    tag_map = {
        "admin": ["admin", "administration"],
        "agent": ["agent", "team"],
        "ai": ["ai", "artificial-intelligence"],
        "backup": ["backup", "recovery"],
        "business": ["business"],
        "code": ["code", "development"],
        "deployment": ["deployment", "production"],
        "guide": ["guide", "documentation"],
        "reference": ["reference", "documentation"],
        "instructions": ["how-to", "guide"],
        "checklist": ["checklist", "procedure"],
        "consciousness": ["consciousness", "memory", "knowledge"],
        "directory": ["directory", "reference"],
        "platform": ["platform", "system"],
        "recovery": ["recovery", "backup"],
        "setup": ["setup", "installation"],
        "updates": ["updates", "changelog"],
    }

    tags = set()
    for part in parts:
        if part in tag_map:
            tags.update(tag_map[part])
        else:
            tags.add(part)

    return list(tags)


def extract_tags_from_content(content):
    """Extract additional tags from content analysis"""
    tags = set()
    content_lower = content.lower()

    # Technology/tool mentions
    tech_keywords = {
        "docker": "docker",
        "postgresql": "postgresql",
        "python": "python",
        "flask": "flask",
        "api": "api",
        "database": "database",
        "nginx": "nginx",
        "gunicorn": "gunicorn",
        "claude": "claude-ai",
        "anthropic": "anthropic",
        "n8n": "n8n",
        "automation": "automation",
    }

    for keyword, tag in tech_keywords.items():
        if keyword in content_lower:
            tags.add(tag)

    # Concept keywords
    if any(word in content_lower for word in ["agent", "agents", "team"]):
        tags.add("agents")
    if any(word in content_lower for word in ["memory", "knowledge", "consciousness"]):
        tags.add("consciousness")
    if any(word in content_lower for word in ["backup", "restore", "recovery"]):
        tags.add("backup")
    if any(word in content_lower for word in ["deploy", "deployment", "production"]):
        tags.add("deployment")
    if any(word in content_lower for word in ["install", "setup", "configuration"]):
        tags.add("setup")

    return list(tags)


def determine_category(filename, content):
    """Determine the best category for a document"""
    filename_lower = filename.lower()
    content_lower = content.lower()

    # Category priority rules
    if "admin" in filename_lower or "reference" in filename_lower:
        return "documentation"
    elif "agent" in filename_lower or "directory" in filename_lower:
        return "business"
    elif "consciousness" in filename_lower or "memory" in filename_lower:
        return "technical"
    elif "backup" in filename_lower or "recovery" in filename_lower:
        return "procedure"
    elif "deployment" in filename_lower or "setup" in filename_lower:
        return "procedure"
    elif "business" in filename_lower:
        return "business"
    elif "update" in filename_lower or "changelog" in filename_lower:
        return "documentation"
    elif "guide" in filename_lower or "instructions" in filename_lower:
        return "documentation"
    else:
        return "documentation"


def calculate_importance(filename, content, tags):
    """Calculate importance score based on content and metadata"""
    importance = 0.5  # Base importance

    # Boost for critical files
    critical_files = ["archie_consciousness", "agent_directory", "admin_reference"]
    if any(cf in filename.lower() for cf in critical_files):
        importance += 0.3

    # Boost for recent updates
    if "update" in filename.lower() or "changelog" in filename.lower():
        importance += 0.2

    # Boost for longer, detailed documents
    if len(content) > 10000:
        importance += 0.1

    # Boost for documents with many tags (comprehensive)
    if len(tags) > 5:
        importance += 0.1

    return min(importance, 1.0)  # Cap at 1.0


def chunk_content(content, filename, max_chunk_size=8000):
    """Split large documents into manageable chunks"""
    chunks = []

    # If content is small enough, return as single chunk
    if len(content) <= max_chunk_size:
        return [content]

    # Split by sections (markdown headers)
    sections = re.split(r"\n(?=#+\s)", content)

    current_chunk = ""
    for section in sections:
        if len(current_chunk) + len(section) <= max_chunk_size:
            current_chunk += "\n" + section
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = section

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks if chunks else [content[:max_chunk_size]]


def ingest_file(conn, file_path):
    """Ingest a single file into the knowledge base"""
    try:
        filename = os.path.basename(file_path)

        # Read file content
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        if not content.strip():
            print(f"  ⚠️  Skipping empty file: {filename}")
            return 0

        # Extract tags
        filename_tags = extract_tags_from_filename(filename)
        content_tags = extract_tags_from_content(content)
        all_tags = list(set(filename_tags + content_tags))

        # Determine category
        category = determine_category(filename, content)

        # Calculate importance
        importance = calculate_importance(filename, content, all_tags)

        # Get file stats
        stats = os.stat(file_path)
        file_size = stats.st_size
        modified_time = datetime.fromtimestamp(stats.st_mtime)

        # Chunk content for large files
        chunks = chunk_content(content, filename)

        print(f"  📄 {filename}")
        print(f"      Category: {category} | Tags: {len(all_tags)} | Importance: {importance:.2f}")
        print(f"      Chunks: {len(chunks)} | Size: {file_size} bytes")

        # Insert each chunk
        cur = conn.cursor()
        inserted_count = 0

        for i, chunk in enumerate(chunks):
            chunk_suffix = f" (Part {i+1}/{len(chunks)})" if len(chunks) > 1 else ""

            # Create metadata
            metadata = {
                "file_path": file_path,
                "file_name": filename,
                "file_size": file_size,
                "modified_time": modified_time.isoformat(),
                "chunk_index": i + 1,
                "total_chunks": len(chunks),
                "source": "documentation_ingestion",
                "ingested_at": datetime.now().isoformat(),
            }

            # Insert into long_term_memory
            cur.execute(
                """
                INSERT INTO long_term_memory
                (content, category, tags, importance_score, metadata, created_at, last_accessed)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            """,
                (
                    f"{filename}{chunk_suffix}\n\n{chunk}",
                    category,
                    all_tags,
                    importance,
                    psycopg2.extras.Json(metadata),
                ),
            )
            inserted_count += 1

        conn.commit()
        print(f"      ✅ Inserted {inserted_count} chunk(s)")
        return inserted_count

    except Exception as e:
        print(f"  ❌ Error ingesting {file_path}: {str(e)}")
        conn.rollback()
        return 0


def main():
    """Main ingestion process"""
    print("=" * 80)
    print("A.R.C.H.I.E. DOCUMENTATION INGESTION")
    print("=" * 80)
    print()

    docs_dir = "/mnt/archie_brain/docs"

    # Find all documentation files
    print("📂 Scanning documentation directory...")
    files_to_ingest = []

    for root, dirs, files in os.walk(docs_dir):
        for file in files:
            if file.endswith((".md", ".txt")) and not file.startswith("."):
                file_path = os.path.join(root, file)
                files_to_ingest.append(file_path)

    print(f"   Found {len(files_to_ingest)} documentation files")
    print()

    if not files_to_ingest:
        print("❌ No files found to ingest!")
        return

    # Connect to database
    print("🔌 Connecting to database...")
    try:
        conn = get_db_connection()
        print("   ✅ Connected")
        print()
    except Exception as e:
        print(f"   ❌ Database connection failed: {str(e)}")
        return

    # Ingest all files
    print("📥 Ingesting files...")
    print()

    total_chunks = 0
    successful_files = 0

    for file_path in sorted(files_to_ingest):
        chunks = ingest_file(conn, file_path)
        if chunks > 0:
            total_chunks += chunks
            successful_files += 1
        print()

    # Summary
    print("=" * 80)
    print("INGESTION COMPLETE")
    print("=" * 80)
    print(f"✅ Files processed: {successful_files}/{len(files_to_ingest)}")
    print(f"✅ Total chunks inserted: {total_chunks}")
    print()

    # Show tag summary
    print("📊 Generating tag summary...")
    cur = conn.cursor()
    cur.execute(
        """
        SELECT unnest(tags) as tag, COUNT(*) as count
        FROM long_term_memory
        WHERE metadata->>'source' = 'documentation_ingestion'
        GROUP BY tag
        ORDER BY count DESC
        LIMIT 20
    """
    )

    print()
    print("Top Tags Created:")
    for row in cur.fetchall():
        print(f"   • {row[0]}: {row[1]}")

    print()
    print("🎉 All documentation has been ingested into A.R.C.H.I.E.'s consciousness!")
    print()

    conn.close()


if __name__ == "__main__":
    main()
