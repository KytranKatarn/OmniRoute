"""Portrait history: remember what an agent's portrait WAS before each approve/revert, and undo it.

Why (review 2026-10-21, task #7429): seven approvals inside 16 seconds replaced seven agents' portraits and the
previous ones could only be recovered from git history of generated website data. Now ``approve_canonical`` records
the previous canonical image + avatar, and ``revert`` puts them back. A revert is itself recorded, so it can be undone.

Recording must never block an approval: ``record_change`` swallows its own errors and returns ``None``.
"""

import logging
from typing import Callable, Dict, List, Optional

from .media_paths import normalize_static_path

logger = logging.getLogger(__name__)

ACTIONS = ("approve", "revert")


def _same_path(a: Optional[str], b: Optional[str]) -> bool:
    return bool(a and b and a.lstrip("/") == b.lstrip("/"))


# Namespace for the per-agent advisory lock (first key of pg_advisory_xact_lock(int, int)); the agent id is the second.
PORTRAIT_LOCK_NS = 7429


def snapshot_current(cur, agent_id: int) -> Dict:
    """What the agent's portrait is RIGHT NOW (read before it is overwritten). Uses the caller's cursor.

    Takes a transaction-scoped advisory lock for this agent FIRST. Without it two concurrent approvals both read the
    same "previous" portrait and the history records the wrong predecessor for one of them. The lock is held until the
    caller's transaction commits (i.e. through the upsert), so approvals for one agent run one after another and each
    snapshot sees the other's committed result. It works even for an agent with no agent_portraits row yet.
    """
    cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (PORTRAIT_LOCK_NS, agent_id))
    cur.execute(
        """
        SELECT canonical_image_path
          FROM agent_portraits
         WHERE agent_id = %s
         ORDER BY approved DESC NULLS LAST, is_primary DESC NULLS LAST, updated_at DESC NULLS LAST, id DESC
         LIMIT 1
        """,
        (agent_id,),
    )
    row = cur.fetchone()
    canonical = (row or {}).get("canonical_image_path") if row else None
    cur.execute("SELECT avatar_url FROM agents WHERE id = %s", (agent_id,))
    arow = cur.fetchone()
    avatar = (arow or {}).get("avatar_url") if arow else None
    media_id = None
    if canonical:
        cur.execute(
            """
            SELECT id FROM media_library
             WHERE owner_type = 'agent' AND owner_id = %s AND is_deleted = false
               AND ltrim(COALESCE(file_path, ''), '/') = ltrim(%s, '/')
             ORDER BY id DESC LIMIT 1
            """,
            (agent_id, canonical),
        )
        m = cur.fetchone()
        media_id = (m or {}).get("id") if m else None
    return {"prev_canonical_image_path": canonical, "prev_avatar_url": avatar, "prev_media_id": media_id}


def record_change(
    agent_id: int,
    prev: Dict,
    new_path: str,
    new_media_id: Optional[int],
    actor: Optional[str] = None,
    action: str = "approve",
    get_cursor=None,
) -> Optional[int]:
    """Write one history row. Returns its id, or None when nothing changed or the write failed (never raises)."""
    if action not in ACTIONS:
        action = "approve"
    if _same_path(prev.get("prev_canonical_image_path"), new_path):
        return None  # approving the image that is already canonical changes nothing: nothing to undo
    if get_cursor is None:
        from database import get_db_cursor as get_cursor
    try:
        with get_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO agent_portrait_history
                    (agent_id, action, prev_canonical_image_path, prev_avatar_url, prev_media_id,
                     new_canonical_image_path, new_media_id, actor)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    agent_id,
                    action,
                    prev.get("prev_canonical_image_path"),
                    prev.get("prev_avatar_url"),
                    prev.get("prev_media_id"),
                    new_path,
                    new_media_id,
                    actor,
                ),
            )
            return int(cur.fetchone()["id"])
    except Exception as exc:  # noqa: BLE001 - history must never block an approval
        logger.warning("[PortraitHistory] could not record change for agent %s: %s", agent_id, exc)
        return None


def list_history(agent_id: int, limit: int = 10, get_cursor=None) -> List[Dict]:
    """Newest first, with browser-ready thumbnails for what the portrait was (``prev_*``) and became (``new_*``)."""
    if get_cursor is None:
        from database import get_db_cursor as get_cursor
    limit = max(1, min(int(limit), 50))
    with get_cursor() as (_conn, cur):
        cur.execute(
            """
            SELECT h.id, h.action, h.prev_canonical_image_path, h.prev_avatar_url, h.prev_media_id,
                   h.new_canonical_image_path, h.new_media_id, h.actor, h.created_at,
                   pm.thumbnail_path AS prev_thumbnail, pm.model AS prev_model,
                   nm.thumbnail_path AS new_thumbnail, nm.model AS new_model
              FROM agent_portrait_history h
              LEFT JOIN media_library pm ON pm.id = h.prev_media_id
              LEFT JOIN media_library nm ON nm.id = h.new_media_id
             WHERE h.agent_id = %s
             ORDER BY h.created_at DESC, h.id DESC
             LIMIT %s
            """,
            (agent_id, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        prev_img = r.get("prev_thumbnail") or r.get("prev_avatar_url") or r.get("prev_canonical_image_path")
        r["prev_thumbnail_url"] = normalize_static_path(prev_img)
        r["new_thumbnail_url"] = normalize_static_path(r.get("new_thumbnail") or r.get("new_canonical_image_path"))
        r["can_revert"] = bool(r.get("prev_media_id"))  # revert re-approves that library image
        if hasattr(r.get("created_at"), "isoformat"):
            r["created_at"] = r["created_at"].isoformat()
    return rows


def get_entry(agent_id: int, history_id: int, get_cursor=None) -> Optional[Dict]:
    if get_cursor is None:
        from database import get_db_cursor as get_cursor
    with get_cursor() as (_conn, cur):
        cur.execute(
            "SELECT * FROM agent_portrait_history WHERE id = %s AND agent_id = %s",
            (history_id, agent_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def revert(agent_id: int, history_id: int, actor: Optional[str], approve: Callable, get_cursor=None) -> Dict:
    """Put back the portrait that ``history_id`` replaced, by re-approving that library image (recorded as 'revert').

    ``approve`` is ``portrait_service.approve_canonical`` (injected so this module stays dependency-light and testable).
    """
    entry = get_entry(agent_id, history_id, get_cursor)
    if not entry:
        return {"error": "History entry not found for this agent"}
    if not entry.get("prev_media_id"):
        return {"error": "The previous portrait is no longer in the media library, so it cannot be restored"}
    result = approve(agent_id, entry["prev_media_id"], actor=actor, action="revert")
    if "error" in result:
        return result
    return {**result, "status": "reverted", "reverted_history_id": history_id}
