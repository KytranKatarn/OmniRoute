"""Session indexer — indexes Claude conversation summaries into knowledge_base."""

import glob
import json
import logging
import os

from database import get_db_cursor
from psycopg2.extras import Json

logger = logging.getLogger(__name__)

SESSIONS_DIR = "/home/kytran/.claude/projects/-mnt-archie-brain"


def index_recent_sessions(max_sessions=5):
    """Index recent Claude session summaries into knowledge_base."""
    # Find JSONL session files
    pattern = os.path.join(SESSIONS_DIR, "*.jsonl")
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)[:max_sessions]

    indexed = 0
    for filepath in files:
        session_id = os.path.basename(filepath).replace(".jsonl", "")

        # Check if already indexed
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id FROM knowledge_base WHERE title = %s",
                (f"Claude Session: {session_id}",),
            )
            if cur.fetchone():
                continue

        # Extract summary from session (first and last few messages)
        try:
            messages = []
            with open(filepath, "r") as f:
                for i, line in enumerate(f):
                    if i > 50:  # cap reading
                        break
                    try:
                        msg = json.loads(line)
                        if msg.get("role") == "assistant" and isinstance(msg.get("content"), str):
                            messages.append(msg["content"][:200])
                    except json.JSONDecodeError:
                        continue

            if not messages:
                continue

            summary = "Session topics: " + " | ".join(messages[:10])

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO knowledge_base (title, content, category, importance, tags, knowledge_type)
                    VALUES (%s, %s, 'session_history', 0.5, %s, 'conversation_memory')
                    ON CONFLICT (title) DO NOTHING
                """,
                    (
                        f"Claude Session: {session_id}",
                        summary[:5000],
                        Json(["session", "claude", "conversation"]),
                    ),
                )
                indexed += 1
        except Exception as e:
            logger.warning(f"Failed to index session {session_id}: {e}")

    return indexed
