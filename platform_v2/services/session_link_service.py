"""Engine-session <-> comms-conversation link store (CLI collaboration, Track B).

The archie_engine posts a link whenever a TUI/CLI session attaches to a comms
conversation, so every surface (cockpit web chat, archie-tui, Claude MCP
co-drive) resolves the same thread. Slice-1 storage rides platform_settings
(zero-migration); promote to a dedicated table when the co-drive UI lands.
"""

import logging

from database import get_db_cursor

logger = logging.getLogger(__name__)

_KEY_PREFIX = "session_link:"


def record_link(session_id, conversation_id):
    """Upsert the link. Returns True when stored, False on empty inputs."""
    if not session_id or not conversation_id:
        return False
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO platform_settings (key, value)
               VALUES (%s, %s)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
            (f"{_KEY_PREFIX}{session_id}", str(conversation_id)),
        )
    return True


def get_link(session_id):
    """Resolve a session's conversation id, or None."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT value FROM platform_settings WHERE key = %s",
            (f"{_KEY_PREFIX}{session_id}",),
        )
        row = cur.fetchone()
    return row["value"] if row else None
