from typing import Dict
from database import get_db_cursor


def get_agent_picker() -> Dict:
    """Returns grouped agent list for Generate tab. Pulls live from DHQ — new agents auto-appear."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT a.id, a.name, a.display_name, a.department, a.worker_type,
                   ap.canonical_image_path,
                   COUNT(DISTINCT ml.id)
                     + CASE WHEN ap.canonical_image_path IS NOT NULL AND ap.approved = true
                         AND NOT EXISTS (
                             SELECT 1 FROM media_library ml2
                             WHERE ml2.owner_id = a.id AND ml2.owner_type = 'agent'
                               AND ml2.file_path = ap.canonical_image_path AND ml2.is_deleted = false
                         ) THEN 1 ELSE 0 END
                     AS asset_count
            FROM agents a
            LEFT JOIN agent_portraits ap ON ap.agent_id = a.id
            LEFT JOIN media_library ml ON ml.owner_id = a.id
                AND ml.owner_type = 'agent' AND ml.is_deleted = false
            WHERE a.shift_state != 'decommissioned' AND a.worker_type IN ('internal', 'ai')
            GROUP BY a.id, a.name, a.display_name, a.department, a.worker_type,
                     ap.canonical_image_path, ap.approved
            ORDER BY a.worker_type DESC, a.name
        """
        )
        rows = cur.fetchall()

    humans, ai_agents = [], []
    for row in rows:
        d = dict(row)
        d["avatar_thumb_url"] = d.pop("canonical_image_path", None) or ""
        if d["worker_type"] == "internal":
            humans.append(d)
        else:
            ai_agents.append(d)
    return {"humans": humans, "ai_agents": ai_agents}


def get_gallery_subjects() -> Dict:
    """Returns sidebar subject list for Gallery tab with asset counts per agent."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT a.id, a.name, a.display_name, a.department, a.worker_type,
                   ap.canonical_image_path,
                   COUNT(DISTINCT ml.id)
                     + CASE WHEN ap.canonical_image_path IS NOT NULL AND ap.approved = true
                         AND NOT EXISTS (
                             SELECT 1 FROM media_library ml2
                             WHERE ml2.owner_id = a.id AND ml2.owner_type = 'agent'
                               AND ml2.file_path = ap.canonical_image_path AND ml2.is_deleted = false
                         ) THEN 1 ELSE 0 END
                     AS asset_count
            FROM agents a
            LEFT JOIN agent_portraits ap ON ap.agent_id = a.id
            LEFT JOIN media_library ml ON ml.owner_id = a.id
                AND ml.owner_type = 'agent' AND ml.is_deleted = false
            WHERE a.shift_state != 'decommissioned' AND a.worker_type IN ('internal', 'ai')
            GROUP BY a.id, a.name, a.display_name, a.department, a.worker_type,
                     ap.canonical_image_path, ap.approved
            ORDER BY a.worker_type DESC, a.name
        """
        )
        rows = cur.fetchall()
        cur.execute("SELECT COUNT(*) AS cnt FROM media_library WHERE owner_type='brand' AND is_deleted=false")
        brand_count = cur.fetchone()["cnt"]

    humans, ai_agents = [], []
    for row in rows:
        d = dict(row)
        d["avatar_thumb_url"] = d.pop("canonical_image_path", None) or ""
        if d["worker_type"] == "internal":
            humans.append(d)
        else:
            ai_agents.append(d)
    return {
        "humans": humans,
        "ai_agents": ai_agents,
        "brand": {"name": "Kytran Empowerment", "asset_count": brand_count},
    }
