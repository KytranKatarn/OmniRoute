"""
Public roster service — single source of truth for the public agent directory.

Backs /api/public/directory + /api/public/directory/live in public_api.py.
The service applies the AI/public/non-decommissioned boundary in its query so
callers cannot accidentally bypass the projection with the legacy view.

Previously, two parallel implementations existed:
  - /tools/department-hq/api/agents/public-roster  (rich shape, direct agents query)
  - /api/public/directory                          (lean shape, minimal view)

This service consolidates both. The avatar URL / thumb URL / wellness helpers
were moved here from tools/department_hq/roster_routes.py.
"""

import os
import logging

from database import get_db_cursor

logger = logging.getLogger(__name__)

PUBLIC_PORTRAIT_HOST = os.getenv("PUBLIC_PORTRAIT_HOST", "https://platform.kytranempowerment.com").rstrip("/")


def public_avatar_url(raw):
    """Normalize agents.avatar_url to a publicly-reachable absolute URL.

    - Absolute URLs (http/https) pass through.
    - Paths starting with / are prefixed with PUBLIC_PORTRAIT_HOST.
    - Empty / None returns "" so the client can render a placeholder.
    """
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        return raw
    if raw.startswith("/"):
        return PUBLIC_PORTRAIT_HOST + raw
    return raw


def public_avatar_thumb_url(raw):
    """Derive an absolute thumb URL from agents.avatar_url.

    Thumbs live at /assets/portraits/<stem>.jpg on the platform host.
    Returns an absolute URL using PUBLIC_PORTRAIT_HOST so external pages
    (kytranempowerment.com on Hostinger CDN, creed-ai.org, etc.) can load
    portraits correctly — relative paths would resolve against Hostinger, not
    the platform, breaking the images.
    """
    if not raw:
        return ""
    tail = raw.rsplit("/", 1)[-1]
    if not tail or "." not in tail:
        return ""
    stem = tail.rsplit(".", 1)[0]
    return f"{PUBLIC_PORTRAIT_HOST}/assets/portraits/{stem}.jpg"


def compute_wellness(stress, mood):
    """Compute wellness badge color from stress_level + mood_intensity."""
    if stress is None and mood is None:
        return "green"
    s = float(stress) if stress is not None else 0.2
    m = float(mood) if mood is not None else 0.5
    if s >= 0.8 or m <= 0.1:
        return "red"
    if s >= 0.5 or m <= 0.3:
        return "yellow"
    return "green"


def get_public_roster(department=None, agent_type=None, search=None):
    """Full public roster snapshot.

    Args:
        department: optional department name filter
        agent_type: optional agent_type name filter
        search: optional substring search against full_name / acronym

    Returns:
        {
            "success": bool,
            "agents": [ {id, display_name, code_name, title, department, floor,
                         acronym, acronym_expansion, bio, avatar_url,
                         avatar_thumb_url, is_director, worker_type,
                         visibility, shift_state, pronouns, agent_type} ],
            "summary": {total, active, directors, departments},
        }

    On DB error returns success=False with empty agents list.
    """
    try:
        clauses = [
            "a.worker_type = %s",
            "a.visibility = %s",
            "a.shift_state <> 'decommissioned'",
        ]
        params = ["ai", "public"]
        full_name_expr = (
            "COALESCE(NULLIF(TRIM(COALESCE(a.first_name, '')::text || ' ' || "
            "COALESCE(a.last_name, '')::text), ''), a.display_name::text, a.name::text)"
        )
        if department:
            clauses.append("a.department = %s")
            params.append(department)
        if agent_type:
            clauses.append("at.name = %s")
            params.append(agent_type)
        if search:
            clauses.append(f"({full_name_expr} ILIKE %s OR a.acronym ILIKE %s)")
            needle = f"%{search}%"
            params.extend([needle, needle])

        sql = f"""
            SELECT
                a.id,
                {full_name_expr} AS full_name,
                a.display_name,
                a.name AS code_name,
                a.acronym,
                a.acronym_expansion,
                a.title,
                a.department,
                a.floor,
                a.bio,
                a.avatar_url,
                a.pronouns,
                a.status,
                a.shift_state,
                a.worker_type,
                a.visibility,
                a.is_department_ai,
                at.name AS agent_type
            FROM agents a
            LEFT JOIN agent_types at ON a.type_id = at.id
            WHERE {' AND '.join(clauses)}
        """

        with get_db_cursor() as (conn, cur):
            cur.execute(sql, params)
            rows = cur.fetchall()

        agents = [
            {
                "id": r["id"],
                "display_name": r["display_name"],
                "code_name": r["code_name"],
                "title": r["title"],
                "department": r["department"],
                "floor": r["floor"],
                "acronym": r["acronym"],
                "acronym_expansion": r["acronym_expansion"],
                "bio": r["bio"],
                "avatar_url": public_avatar_url(r["avatar_url"]),
                "avatar_thumb_url": public_avatar_thumb_url(r["avatar_url"]),
                "is_director": bool(r["is_department_ai"]),
                "worker_type": r["worker_type"],
                "visibility": r["visibility"],
                "shift_state": r["shift_state"],
                "pronouns": r["pronouns"],
                "agent_type": r["agent_type"],
            }
            for r in rows
        ]

        summary = {
            "total": len(agents),
            "active": sum(1 for a in agents if a["shift_state"] == "active"),
            "directors": sum(1 for a in agents if a["is_director"]),
            "departments": len({a["department"] for a in agents if a["department"]}),
        }

        return {"success": True, "agents": agents, "summary": summary}

    except Exception as e:
        logger.error("get_public_roster failed: %s", e)
        return {
            "success": False,
            "agents": [],
            "summary": {"total": 0, "active": 0, "directors": 0, "departments": 0},
            "error": str(e),
        }


def get_public_roster_live():
    """Lightweight live-state poll for public pages.

    Returns shift_state + mood per agent so presence badges can refresh
    without re-fetching the full roster. Excludes decommissioned.

    Returns:
        {"success": bool, "agents": [{id, code_name, shift_state,
                                       current_mood, wellness_status}]}
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT a.id, a.name AS code_name, a.shift_state,
                       e.current_mood, e.stress_level, e.mood_intensity
                FROM agents a
                LEFT JOIN LATERAL (
                    SELECT current_mood, stress_level, mood_intensity
                    FROM agent_emotional_state
                    WHERE agent_id = a.id
                    ORDER BY timestamp DESC
                    LIMIT 1
                ) e ON TRUE
                WHERE a.worker_type = 'ai'
                  AND a.visibility = 'public'
                  AND a.shift_state != 'decommissioned'
                """
            )
            rows = cur.fetchall()

        agents = [
            {
                "id": r["id"],
                "code_name": r["code_name"],
                "shift_state": r["shift_state"],
                "current_mood": r["current_mood"] or "neutral",
                "wellness_status": compute_wellness(r["stress_level"], r["mood_intensity"]),
            }
            for r in rows
        ]
        return {"success": True, "agents": agents}

    except Exception as e:
        logger.error("get_public_roster_live failed: %s", e)
        return {"success": False, "agents": [], "error": str(e)}


_KYTRAN_DATA_DIR = os.getenv(
    "KYTRAN_WEBSITE_DATA_DIR",
    "/mnt/archie_brain/website/kytranempowerment.com/data",
)


def validate_directory_snapshot(roster) -> bool:
    """Reject incomplete or non-public roster payloads before writing snapshots."""
    if not isinstance(roster, dict) or roster.get("success") is not True:
        return False

    agents = roster.get("agents")
    if not isinstance(agents, list) or not agents:
        return False

    forbidden_fields = {"email", "phone", "address", "user_id", "notes"}
    for agent in agents:
        if not isinstance(agent, dict):
            return False
        if agent.get("worker_type") != "ai":
            return False
        if agent.get("visibility") != "public":
            return False
        if agent.get("shift_state") == "decommissioned":
            return False
        if forbidden_fields.intersection(agent):
            return False

    return True


def write_directory_snapshot() -> bool:
    """Write directory-fallback.json and directors.json to the website data directory.

    Pulls current agent data from the DB and writes two static files so the
    CDN-served directory and AI-Directors pages don't depend on a live hub call.
    Called before portrait deploys so the snapshot is always fresh in the zip.
    Returns True on success, False on any error.
    """
    import json
    from datetime import datetime, timezone

    try:
        roster = get_public_roster()
        if not validate_directory_snapshot(roster):
            logger.error("[DirectorySnapshot] refusing to write an invalid public roster")
            return False
        agents = roster.get("agents", [])
        generated_at = datetime.now(timezone.utc).isoformat()

        os.makedirs(_KYTRAN_DATA_DIR, exist_ok=True)

        # Full roster — directory.js reads this as primary
        fallback_path = os.path.join(_KYTRAN_DATA_DIR, "directory-fallback.json")
        with open(fallback_path, "w", encoding="utf-8") as f:
            json.dump({"agents": agents, "generated_at": generated_at}, f, ensure_ascii=False, indent=2)

        # Directors only — ai-directors.js reads this as primary
        directors = [a for a in agents if a.get("is_director")]
        directors_path = os.path.join(_KYTRAN_DATA_DIR, "directors.json")
        with open(directors_path, "w", encoding="utf-8") as f:
            json.dump({"agents": directors, "generated_at": generated_at}, f, ensure_ascii=False, indent=2)

        logger.info(
            "[DirectorySnapshot] Wrote %d agents + %d directors to %s",
            len(agents),
            len(directors),
            _KYTRAN_DATA_DIR,
        )
        return True

    except Exception as exc:
        logger.error("[DirectorySnapshot] write_directory_snapshot failed: %s", exc)
        return False
