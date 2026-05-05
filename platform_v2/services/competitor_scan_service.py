"""Competitor landscape auto-scan — refreshes AI competitor data in knowledge_base.

Job #52 in agent loop. Runs every 2 weeks. Compares current competitor list against
knowledge_base entries, updates stale records, and returns a summary for Telegram.
"""

import logging
from datetime import datetime, timedelta, timezone

from database import get_db_cursor
from psycopg2.extras import Json

logger = logging.getLogger(__name__)

# Canonical competitor categories and names (mirrors public_api._fetch_competitors)
COMPETITOR_CATEGORIES = {
    "orchestration": [
        "CrewAI",
        "AG2 (AutoGen fork)",
        "LangGraph",
        "MetaGPT",
        "OpenAI Agents SDK",
    ],
    "workflow_builders": ["Langflow", "n8n", "Dify", "Flowise"],
    "coding_agents": [
        "Devin",
        "Cursor",
        "Windsurf",
        "Claude Code",
        "Codex CLI",
        "Cline",
        "Aider",
    ],
    "enterprise": [
        "Microsoft Agent Framework",
        "Haystack",
        "Relevance AI",
        "Dust.tt",
        "OpenAI Assistants",
    ],
    "self_hosted": ["Goose (Block/AAIF)", "LocalAGI", "Aider", "Ollama", "Open WebUI"],
}


def run_competitor_scan():
    """Scan competitor landscape and upsert knowledge_base entries.

    Returns dict with counts: {updated, created, total, summary_lines}.
    """
    created = 0
    updated = 0
    summary_lines = []
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(days=30)

    with get_db_cursor(commit=True) as (conn, cur):
        for category, competitors in COMPETITOR_CATEGORIES.items():
            for name in competitors:
                title = f"Competitor: {name}"

                # Check if entry exists
                cur.execute(
                    "SELECT id, updated_at FROM knowledge_base WHERE title = %s",
                    (title,),
                )
                existing = cur.fetchone()

                content = (
                    f"AI competitor in category: {category}. "
                    f"Name: {name}. "
                    f"Last scanned: {now.strftime('%Y-%m-%d')}. "
                    f"Category: {category}."
                )

                if existing:
                    entry_updated = existing["updated_at"]
                    if entry_updated and entry_updated.replace(tzinfo=None) > stale_threshold:
                        continue  # Still fresh, skip
                    # Update stale entry
                    cur.execute(
                        """UPDATE knowledge_base
                           SET content = %s, updated_at = NOW(), tags = %s
                           WHERE id = %s""",
                        (
                            content,
                            Json(["competitor", category, "ai_landscape", "auto_scan"]),
                            existing["id"],
                        ),
                    )
                    updated += 1
                    summary_lines.append(f"  Updated: {name} ({category})")
                else:
                    # Create new entry
                    cur.execute(
                        """INSERT INTO knowledge_base
                           (title, content, category, importance, tags, knowledge_type)
                           VALUES (%s, %s, 'competitor_analysis', 0.6, %s, 'vault_note')
                           ON CONFLICT (title) DO NOTHING""",
                        (
                            title,
                            content,
                            Json(["competitor", category, "ai_landscape", "auto_scan"]),
                        ),
                    )
                    created += 1
                    summary_lines.append(f"  New: {name} ({category})")

    total = sum(len(v) for v in COMPETITOR_CATEGORIES.values())

    return {
        "created": created,
        "updated": updated,
        "total": total,
        "summary_lines": summary_lines,
    }
