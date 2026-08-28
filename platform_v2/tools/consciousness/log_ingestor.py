"""
Conversation Log Ingestion System for ARCHIE Consciousness

This module processes conversation logs from /mnt/archie_brain/conversation_logs/
and ingests them into the knowledge_base for ARCHIE's learning.

File Types:
- snapshot_*.json: Session snapshots with message arrays
- transcript_*.md: Markdown transcripts (processed text)
- session_end_*.json: Session summary data
"""

import os
from database import _get_db_password
import json
import hashlib
from datetime import datetime
from typing import Optional
import psycopg2
from psycopg2.extras import RealDictCursor

CONVERSATION_LOGS_DIR = "/mnt/archie_brain/conversation_logs"


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def get_file_hash(filepath: str) -> str:
    """Generate hash of file for deduplication"""
    with open(filepath, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def parse_snapshot_file(filepath: str) -> Optional[dict]:
    """
    Parse a snapshot JSON file.

    Returns dict with:
    - session_id: UUID of session
    - timestamp: When snapshot was taken
    - project: Project path
    - message_count: Number of messages
    - messages: Array of message content
    - summary: Generated summary
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        messages = data.get("messages", [])
        content_parts = []
        for msg in messages[:50]:  # Limit to first 50 messages
            content = msg.get("content", "")
            if content and len(content) > 10:  # Skip very short messages
                content_parts.append(content[:500])  # Truncate long messages

        return {
            "type": "snapshot",
            "session_id": data.get("session_id"),
            "timestamp": data.get("timestamp"),
            "project": data.get("project"),
            "message_count": data.get("message_count", len(messages)),
            "summary": data.get("conversation_summary", ""),
            "content": "\n---\n".join(content_parts),
            "metadata": {
                "git_branch": data.get("git_branch"),
                "git_commit": data.get("git_commit"),
                "context_usage": data.get("context_usage"),
                "compact_type": data.get("compact_type"),
            },
        }
    except Exception as e:
        return {"error": str(e), "filepath": filepath}


def parse_transcript_file(filepath: str) -> Optional[dict]:
    """
    Parse a transcript markdown file.

    Returns dict with:
    - session_id: Extracted from filename
    - timestamp: Extracted from filename
    - content: Full transcript text
    """
    try:
        filename = os.path.basename(filepath)
        # Extract timestamp from filename: transcript_YYYYMMDD_HHMMSS.md
        parts = filename.replace(".md", "").split("_")
        if len(parts) >= 3:
            date_str = parts[1]
            time_str = parts[2]
            timestamp_str = (
                f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"
            )
        else:
            timestamp_str = None

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Truncate very long transcripts
        if len(content) > 50000:
            content = content[:50000] + "\n\n[... truncated ...]"

        return {
            "type": "transcript",
            "timestamp": timestamp_str,
            "content": content,
            "filename": filename,
            "file_size": os.path.getsize(filepath),
            "metadata": {"source_file": filepath},
        }
    except Exception as e:
        return {"error": str(e), "filepath": filepath}


def parse_session_end_file(filepath: str) -> Optional[dict]:
    """
    Parse a session_end JSON file.

    Returns dict with session summary information.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        return {
            "type": "session_end",
            "session_id": data.get("session_id"),
            "timestamp": data.get("timestamp"),
            "project": data.get("project"),
            "duration": data.get("duration"),
            "message_count": data.get("message_count"),
            "content": json.dumps(data, indent=2),
            "metadata": data,
        }
    except Exception as e:
        return {"error": str(e), "filepath": filepath}


def check_already_ingested(cur, file_hash: str) -> bool:
    """Check if file has already been ingested"""
    cur.execute(
        """
        SELECT id FROM knowledge_base
        WHERE memory_metadata->>'file_hash' = %s
        LIMIT 1
        """,
        (file_hash,),
    )
    return cur.fetchone() is not None


def ingest_log_file(filepath: str, dry_run: bool = False, conn=None) -> dict:
    """
    Process and ingest a single log file into knowledge_base.

    Args:
        filepath: Path to log file
        dry_run: If True, don't actually insert, just report
        conn: Optional shared DB connection (caller manages lifecycle)

    Returns:
        dict with success status and details
    """
    filename = os.path.basename(filepath)
    file_hash = get_file_hash(filepath)

    # Determine file type and parse
    if filename.startswith("snapshot_") and filename.endswith(".json"):
        parsed = parse_snapshot_file(filepath)
    elif filename.startswith("transcript_") and filename.endswith(".md"):
        parsed = parse_transcript_file(filepath)
    elif filename.startswith("session_end_") and filename.endswith(".json"):
        parsed = parse_session_end_file(filepath)
    else:
        return {"success": False, "error": f"Unknown file type: {filename}"}

    if "error" in parsed:
        return {"success": False, "error": parsed["error"]}

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "would_create": True,
            "type": parsed.get("type"),
            "filename": filename,
        }

    cur = None
    owns_conn = conn is None
    try:
        if owns_conn:
            conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if already ingested
        if check_already_ingested(cur, file_hash):
            cur.close()
            if owns_conn:
                conn.close()
            return {"success": True, "skipped": True, "reason": "already_ingested"}

        # Prepare metadata
        metadata = parsed.get("metadata", {}) or {}
        metadata["file_hash"] = file_hash
        metadata["source_file"] = filepath
        metadata["ingested_at"] = datetime.now().isoformat()
        metadata["log_type"] = parsed.get("type")

        # Generate title (use filename for uniqueness)
        parsed.get("session_id") or "unknown"
        if parsed.get("type") == "snapshot":
            title = f"Session Snapshot: {filename}"
        elif parsed.get("type") == "transcript":
            title = f"Conversation Transcript: {filename}"
        else:
            title = f"Session End: {filename}"

        # Calculate importance (snapshots with more messages = more important)
        message_count = parsed.get("message_count", 0) or 0
        importance = min(0.3 + (message_count / 1000), 0.9)

        # Insert into knowledge_base
        cur.execute(
            """
            INSERT INTO knowledge_base
                (title, content, knowledge_type, source_type, category, importance_score, memory_metadata, tags)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                title,
                parsed.get("content", "")[:100000],  # Limit content size
                "conversation_memory",
                "conversation_log",
                "conversation",
                importance,
                json.dumps(metadata),
                ["conversation", "log", parsed.get("type", "unknown")],
            ),
        )

        result = cur.fetchone()
        conn.commit()
        cur.close()
        if owns_conn:
            conn.close()

        return {
            "success": True,
            "created": True,
            "knowledge_id": result["id"],
            "type": parsed.get("type"),
            "filename": filename,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "filename": filename}
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        try:
            if owns_conn and conn is not None:
                conn.close()
        except Exception:
            pass


def batch_ingest_logs(limit: int = 5000, dry_run: bool = False) -> dict:
    """
    Batch ingest conversation log files.

    Args:
        limit: Maximum number of files to process (default 5000)
        dry_run: If True, don't actually insert

    Returns:
        dict with processing results
    """
    results = {"processed": 0, "created": 0, "skipped": 0, "errors": []}

    if not os.path.exists(CONVERSATION_LOGS_DIR):
        return {
            "success": False,
            "error": f"Directory not found: {CONVERSATION_LOGS_DIR}",
        }

    # Get list of log files (prioritize snapshots, then transcripts)
    files = []
    for filename in os.listdir(CONVERSATION_LOGS_DIR):
        filepath = os.path.join(CONVERSATION_LOGS_DIR, filename)
        if not os.path.isfile(filepath):
            continue
        if filename.startswith("snapshot_") and filename.endswith(".json"):
            files.append((0, filepath))  # Priority 0 - snapshots
        elif filename.startswith("transcript_") and filename.endswith(".md"):
            files.append((1, filepath))  # Priority 1 - transcripts
        elif filename.startswith("session_end_") and filename.endswith(".json"):
            files.append((2, filepath))  # Priority 2 - session ends

    # Sort by priority, then by filename (newest first)
    files.sort(key=lambda x: (x[0], x[1]), reverse=False)

    # Share a single DB connection across all files
    conn = None if dry_run else get_db()
    try:
        for priority, filepath in files[:limit]:
            result = ingest_log_file(filepath, dry_run=dry_run, conn=conn)
            results["processed"] += 1

            if result.get("success"):
                if result.get("created") or result.get("would_create"):
                    results["created"] += 1
                elif result.get("skipped"):
                    results["skipped"] += 1
            else:
                results["errors"].append({"file": os.path.basename(filepath), "error": result.get("error")})
    finally:
        if conn:
            conn.close()

    results["success"] = True
    return results


def get_ingestion_status() -> dict:
    """
    Get status of log ingestion.

    Returns counts of files in conversation_logs and ingested entries.
    """
    status = {
        "snapshots": 0,
        "transcripts": 0,
        "session_ends": 0,
        "ingested": 0,
        "sessions": set(),
    }

    if not os.path.exists(CONVERSATION_LOGS_DIR):
        return {
            "success": False,
            "error": f"Directory not found: {CONVERSATION_LOGS_DIR}",
        }

    # Count files by type
    for filename in os.listdir(CONVERSATION_LOGS_DIR):
        if filename.startswith("snapshot_") and filename.endswith(".json"):
            status["snapshots"] += 1
        elif filename.startswith("transcript_") and filename.endswith(".md"):
            status["transcripts"] += 1
        elif filename.startswith("session_end_") and filename.endswith(".json"):
            status["session_ends"] += 1
            # Extract session ID from filename for unique session count
            parts = filename.replace(".json", "").split("_")
            if len(parts) >= 3:
                status["sessions"].add(f"{parts[2]}_{parts[3] if len(parts) > 3 else ''}")

    # Count ingested entries and last ingestion time
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) as cnt, MAX(created_at) as last_ingested
            FROM knowledge_base
            WHERE source_type = 'conversation_log'
            """
        )
        row = cur.fetchone()
        status["ingested"] = row[0]
        status["last_ingested_at"] = row[1].isoformat() if row[1] else None
        cur.close()
        conn.close()
    except Exception as e:
        status["db_error"] = str(e)

    status["sessions"] = len(status["sessions"])
    status["total_files"] = status["snapshots"] + status["transcripts"] + status["session_ends"]
    status["success"] = True
    return status
