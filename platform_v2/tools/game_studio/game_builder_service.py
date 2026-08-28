"""
Game Builder Service — AI-driven 4-stage pipeline for generating game projects.
Stages: concept -> level -> mechanics -> qa (with checkpoints at concept + qa)
"""

import json
import logging
import re
import threading
from datetime import datetime

from tools.department_hq.services.department_dispatcher import dispatch_json

from database import get_db_cursor

logger = logging.getLogger(__name__)

PIPELINE_STAGES = [
    {"id": "concept", "name": "Game Concept", "checkpoint": True},
    {"id": "level", "name": "Level Design", "checkpoint": False},
    {"id": "mechanics", "name": "Game Mechanics", "checkpoint": False},
    {"id": "qa", "name": "Quality Check", "checkpoint": True},
]

STAGE_PROMPTS = {
    "concept": (
        "You are a game concept designer. Given a game description, output ONLY valid JSON: "
        '{"game_type": "...", "theme": "...", "mechanics": [...], '
        '"entities": [{"name": "...", "type": "...", "behavior": "..."}], '
        '"win_condition": "...", "difficulty_curve": "..."}'
    ),
    "level": (
        "You are a level designer. Generate a complete game config JSON matching the {game_type} schema. "
        "Place entities strategically. Output ONLY valid JSON."
    ),
    "mechanics": (
        "You are a game mechanics programmer. Write custom behavior functions. "
        'Output ONLY valid JSON: {"behaviors": [{"name": "...", "code": "function(entity, engine, dt) {...}"}]}'
    ),
    "qa": (
        "You are a QA analyst. Review config + behaviors for issues. "
        'Output ONLY valid JSON: {"issues": [{"severity": "...", "description": "...", "fix": "..."}], '
        '"score": 0, "summary": "..."}'
    ),
}


def _serialize_session(row):
    """Convert a DB row dict to JSON-serializable dict."""
    result = dict(row)
    for key in ("created_at", "completed_at"):
        if result.get(key) and isinstance(result[key], datetime):
            result[key] = result[key].isoformat()
    return result


def _parse_ai_json(text):
    """Try json.loads first, then extract from ```json block."""
    if not text:
        return {}
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```json\s*([\s\S]+?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Last resort: find first { ... } block
    match = re.search(r"\{[\s\S]+\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    logger.warning("Could not parse AI response as JSON, storing raw text")
    return {"raw": text}


def _get_stage(stage_id):
    for s in PIPELINE_STAGES:
        if s["id"] == stage_id:
            return s
    return None


def _next_stage(stage_id):
    ids = [s["id"] for s in PIPELINE_STAGES]
    try:
        idx = ids.index(stage_id)
        if idx + 1 < len(ids):
            return ids[idx + 1]
    except ValueError:
        pass
    return None


def _run_stage(session_id, stage_id):
    """Run a single pipeline stage, store output, advance or checkpoint."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT * FROM game_build_sessions WHERE id = %s", (session_id,))
            row = cur.fetchone()

        if not row:
            raise ValueError(f"Session {session_id} not found")

        description = row["description"]
        stage_outputs = row["stage_outputs"] or {}
        stage = _get_stage(stage_id)
        if not stage:
            raise ValueError(f"Unknown stage: {stage_id}")

        # Build system prompt — interpolate game_type if available
        sys_prompt = STAGE_PROMPTS[stage_id]
        concept = stage_outputs.get("concept", {})
        game_type = concept.get("game_type", "2d platformer") if isinstance(concept, dict) else "2d platformer"
        sys_prompt = sys_prompt.replace("{game_type}", game_type)

        # Build context from description + prior stage outputs
        context_parts = [f"Game description: {description}"]
        for prev_stage in PIPELINE_STAGES:
            if prev_stage["id"] == stage_id:
                break
            prev_out = stage_outputs.get(prev_stage["id"])
            if prev_out:
                context_parts.append(f"{prev_stage['name']} output:\n{json.dumps(prev_out, indent=2)}")
        context = "\n\n".join(context_parts)

        # Call AI via DHQ dispatcher (ADR-013)
        result = dispatch_json(
            capability="creative",
            prompt=context,
            module_id="game_studio",
            system_prompt=sys_prompt,
        )
        ai_text = result.get("response", "") if isinstance(result, dict) else str(result)
        parsed = _parse_ai_json(ai_text)

        # Persist stage output and advance state
        import psycopg2.extras

        new_outputs = dict(stage_outputs)
        new_outputs[stage_id] = parsed

        if stage["checkpoint"]:
            new_status = "checkpoint"
            new_stage = stage_id
        else:
            next_id = _next_stage(stage_id)
            if next_id:
                new_status = "running"
                new_stage = next_id
            else:
                new_status = "completed"
                new_stage = stage_id

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE game_build_sessions
                SET stage_outputs = %s, current_stage = %s, status = %s,
                    completed_at = CASE WHEN %s = 'completed' THEN NOW() ELSE completed_at END
                WHERE id = %s
                """,
                (
                    psycopg2.extras.Json(new_outputs),
                    new_stage,
                    new_status,
                    new_status,
                    session_id,
                ),
            )

        # Recurse into next stage if not at a checkpoint
        if new_status == "running" and new_stage != stage_id:
            _run_stage(session_id, new_stage)

    except Exception as e:
        logger.exception("Error in _run_stage(%s, %s): %s", session_id, stage_id, e)
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE game_build_sessions SET status = %s WHERE id = %s",
                ("error", session_id),
            )
        raise


def start_build(user_id, description, game_type=None):
    """Create a project + session and return immediately; pipeline runs in a background thread."""
    try:
        engine = game_type or "2d"
        title = description[:50]

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO game_projects (user_id, title, engine_type, status)
                VALUES (%s, %s, %s, 'building')
                RETURNING id
                """,
                (user_id, title, engine),
            )
            project_id = cur.fetchone()["id"]

            cur.execute(
                """
                INSERT INTO game_build_sessions
                    (project_id, user_id, description, current_stage, status)
                VALUES (%s, %s, %s, 'concept', 'queued')
                RETURNING id
                """,
                (project_id, user_id, description),
            )
            session_id = cur.fetchone()["id"]

        # Run the 4-stage pipeline in a background thread — never block the web request
        def _run_pipeline(sid):
            try:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE game_build_sessions SET status = 'running' WHERE id = %s",
                        (sid,),
                    )
                _run_stage(sid, "concept")
            except Exception:
                logger.exception("Background build pipeline failed for session %s", sid)

        t = threading.Thread(target=_run_pipeline, args=(session_id,), daemon=True, name=f"game-build-{session_id}")
        t.start()

        return {
            "session_id": session_id,
            "project_id": project_id,
            "status": "queued",
            "stage": "concept",
        }

    except Exception as e:
        logger.exception("Error in start_build: %s", e)
        raise


def approve_checkpoint(session_id, user_id):
    """Approve the current checkpoint and advance to the next stage."""
    try:
        import psycopg2.extras

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT * FROM game_build_sessions WHERE id = %s AND user_id = %s",
                (session_id, user_id),
            )
            row = cur.fetchone()

        if not row:
            raise ValueError(f"Session {session_id} not found or not owned by user {user_id}")
        if row["status"] != "checkpoint":
            raise ValueError(f"Session {session_id} is not at a checkpoint (status={row['status']})")

        current_stage = row["current_stage"]
        approved = list(row["checkpoint_approved"] or [])
        if current_stage not in approved:
            approved.append(current_stage)

        next_id = _next_stage(current_stage)

        if next_id:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE game_build_sessions
                    SET checkpoint_approved = %s, current_stage = %s, status = 'running'
                    WHERE id = %s
                    """,
                    (psycopg2.extras.Json(approved), next_id, session_id),
                )
            _run_stage(session_id, next_id)
        else:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE game_build_sessions
                    SET checkpoint_approved = %s, status = 'completed', completed_at = NOW()
                    WHERE id = %s
                    """,
                    (psycopg2.extras.Json(approved), session_id),
                )

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT status, current_stage FROM game_build_sessions WHERE id = %s",
                (session_id,),
            )
            row = cur.fetchone()

        return {"session_id": session_id, "status": row["status"], "stage": row["current_stage"]}

    except Exception as e:
        logger.exception("Error in approve_checkpoint: %s", e)
        raise


def get_build_status(session_id, user_id=None):
    """Return full session dict with serialized datetimes. Filters by user_id when provided."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            if user_id is not None:
                cur.execute(
                    "SELECT * FROM game_build_sessions WHERE id = %s AND user_id = %s",
                    (session_id, user_id),
                )
            else:
                cur.execute("SELECT * FROM game_build_sessions WHERE id = %s", (session_id,))
            row = cur.fetchone()
        if not row:
            return None
        return _serialize_session(row)
    except Exception as e:
        logger.exception("Error in get_build_status: %s", e)
        raise


def apply_build_result(session_id):
    """Materialise completed build: insert scene + code assets, set project to development."""
    try:
        import psycopg2.extras

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT * FROM game_build_sessions WHERE id = %s", (session_id,))
            row = cur.fetchone()

        if not row:
            raise ValueError(f"Session {session_id} not found")
        if row["status"] != "completed":
            raise ValueError(f"Session {session_id} is not completed (status={row['status']})")

        stage_outputs = row["stage_outputs"] or {}
        project_id = row["project_id"]
        user_id = row["user_id"]

        level_config = stage_outputs.get("level", {})
        mechanics = stage_outputs.get("mechanics", {})
        behaviors = mechanics.get("behaviors", []) if isinstance(mechanics, dict) else []

        with get_db_cursor(commit=True) as (conn, cur):
            # Insert game scene
            cur.execute(
                """
                INSERT INTO game_scenes (game_id, name, scene_data)
                VALUES (%s, %s, %s)
                """,
                (project_id, "Generated Level", psycopg2.extras.Json(level_config)),
            )

            # Insert code assets for each behavior
            for behavior in behaviors:
                name = behavior.get("name", "unnamed_behavior")
                code = behavior.get("code", "")
                cur.execute(
                    """
                    INSERT INTO game_assets (game_id, user_id, name, asset_type, file_path, content)
                    VALUES (%s, %s, %s, 'code', '', %s)
                    """,
                    (project_id, user_id, name, code),
                )

            # Mark project as ready for development
            cur.execute(
                "UPDATE game_projects SET status = 'development' WHERE id = %s",
                (project_id,),
            )

        return {"project_id": project_id}

    except Exception as e:
        logger.exception("Error in apply_build_result: %s", e)
        raise
