"""Agent media service — lets agents generate, publish, and browse media.

Entry points:
- agent_generate()        — generate media on behalf of an agent
- publish_generation()    — promote a generation to the shared gallery
- get_agent_gallery()     — retrieve an agent's media library
- orchestration_generate() — thin wrapper for the orchestration engine

Implementation note on owner_id:
  media_library.owner_id is INTEGER.  Agent generations are stored with
  owner_type='agent' and owner_id=0 (sentinel).  The agent name is persisted
  in metadata->>'agent_name' so we can filter per-agent without a schema
  change.  Daily-count and gallery queries therefore use the metadata field.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


from database import get_db_cursor

logger = logging.getLogger(__name__)

# Hard cap on agent-initiated generations per 24-hour window across ALL agents.
GLOBAL_DAILY_CAP = 100


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_agent_config(agent_name: str) -> Optional[Dict]:
    """Load generation config for *agent_name* from media_agent_config.

    Returns the row as a dict, or None if no config exists.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT agent_name, media_type, default_prompt, default_params,
                   daily_cap, gallery_visibility, enabled
            FROM   media_agent_config
            WHERE  agent_name = %s
            """,
            (agent_name,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)


def _get_daily_count(owner_id: Optional[str] = None) -> int:
    """Return the number of agent generations in the last 24 hours.

    If *owner_id* (agent_name) is given, count only that agent's generations
    by matching metadata->>'agent_name'.  Otherwise return the platform-wide
    agent total (owner_type='agent').
    """
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    with get_db_cursor() as (conn, cur):
        if owner_id is not None:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM   media_library
                WHERE  owner_type = 'agent'
                  AND  metadata->>'agent_name' = %s
                  AND  created_at >= %s
                """,
                (owner_id, since),
            )
        else:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM   media_library
                WHERE  owner_type = 'agent'
                  AND  created_at >= %s
                """,
                (since,),
            )
        row = cur.fetchone()
        if not row:
            return 0
        # get_db_cursor yields RealDictCursor dict rows — row[0] raised KeyError: 0
        # on every media-schedule tick (118x/48h, #4641; KB #268832 bug class).
        return next(iter(row.values())) if isinstance(row, dict) else row[0]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def agent_generate(
    agent_name: str,
    media_type: Optional[str] = None,
    prompt: Optional[str] = None,
    params: Optional[Dict] = None,
) -> Dict:
    """Generate media on behalf of *agent_name*.

    1. Load agent config — return error if not found / disabled.
    2. Check global daily cap.
    3. Check per-agent daily cap.
    4. Merge caller params over config defaults and call submit_generation().

    Returns the result dict from submit_generation(), or an error dict.
    """
    # Late import avoids circular dependencies at module load time.
    from tools.media_studio.services.generation_service import submit_generation

    config = _get_agent_config(agent_name)
    if config is None:
        return {"error": f"Agent '{agent_name}' is not configured for media generation"}

    if not config.get("enabled", True):
        return {"error": f"Agent '{agent_name}' media generation is disabled"}

    # Resolve media type — caller overrides config default.
    resolved_media_type = media_type or config.get("media_type") or "image"

    # Resolve prompt.
    resolved_prompt = prompt or config.get("default_prompt") or ""
    if not resolved_prompt:
        return {"error": "No prompt provided and agent has no default_prompt configured"}

    # Global cap check.
    global_count = _get_daily_count()
    if global_count >= GLOBAL_DAILY_CAP:
        return {"error": (f"Global daily agent generation cap reached " f"({GLOBAL_DAILY_CAP} generations/24h)")}

    # Per-agent cap check.
    agent_cap = config.get("daily_cap")
    if agent_cap is not None:
        agent_count = _get_daily_count(owner_id=agent_name)
        if agent_count >= agent_cap:
            return {"error": (f"Agent '{agent_name}' daily cap reached " f"({agent_cap} generations/24h)")}

    # Merge params: config defaults < caller overrides.
    merged_params: Dict[str, Any] = {}
    config_params = config.get("default_params") or {}
    if isinstance(config_params, dict):
        merged_params.update(config_params)
    if params:
        merged_params.update(params)

    # Embed agent_name so we can filter per-agent in media_library queries.
    merged_params["_agent_name"] = agent_name

    try:
        # owner_id=0 because media_library.owner_id is INTEGER;
        # the agent name is carried in params metadata via generation_service.
        result = submit_generation(
            user_id=0,
            media_type=resolved_media_type,
            prompt=resolved_prompt,
            owner_type="agent",
            owner_id=0,
            params=merged_params if merged_params else None,
        )
        return result
    except Exception as exc:
        logger.exception("agent_generate failed for %s: %s", agent_name, exc)
        return {"error": str(exc)}


def publish_generation(generation_id: int, agent_name: str) -> Dict:
    """Set gallery_visibility='shared' on a media_library row.

    Only operates on rows owned by agents where metadata->>'agent_name'
    matches *agent_name* to prevent cross-agent edits.
    Returns a status dict.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE media_library
            SET    gallery_visibility = 'shared'
            WHERE  id         = %s
              AND  owner_type = 'agent'
              AND  metadata->>'agent_name' = %s
            """,
            (generation_id, agent_name),
        )
        updated = cur.rowcount

    if updated == 0:
        return {"error": (f"Generation {generation_id} not found or not owned by '{agent_name}'")}
    return {"success": True, "generation_id": generation_id, "visibility": "shared"}


def get_agent_gallery(agent_name: str, include_private: bool = False) -> List[Dict]:
    """Return media_library rows for *agent_name*.

    Agent name is matched via metadata->>'agent_name'.
    If *include_private* is False (default), only rows where
    gallery_visibility = 'shared' are returned.
    """
    with get_db_cursor() as (conn, cur):
        if include_private:
            cur.execute(
                """
                SELECT id, media_type, prompt, file_path, thumbnail_path,
                       gallery_visibility, created_at, metadata
                FROM   media_library
                WHERE  owner_type = 'agent'
                  AND  metadata->>'agent_name' = %s
                ORDER  BY created_at DESC
                """,
                (agent_name,),
            )
        else:
            cur.execute(
                """
                SELECT id, media_type, prompt, file_path, thumbnail_path,
                       gallery_visibility, created_at, metadata
                FROM   media_library
                WHERE  owner_type          = 'agent'
                  AND  metadata->>'agent_name' = %s
                  AND  gallery_visibility  = 'shared'
                ORDER  BY created_at DESC
                """,
                (agent_name,),
            )
        rows = cur.fetchall()
        return [dict(r) for r in rows] if rows else []


def orchestration_generate(agent_name: str, intent_data: Dict) -> Dict:
    """Entry point for the orchestration engine.

    Unpacks *intent_data* and delegates to agent_generate().

    Expected keys in intent_data (all optional):
        media_type  — "image" | "video" | "audio"
        prompt      — generation prompt
        params      — extra generation parameters (dict)
    """
    return agent_generate(
        agent_name=agent_name,
        media_type=intent_data.get("media_type"),
        prompt=intent_data.get("prompt"),
        params=intent_data.get("params"),
    )
