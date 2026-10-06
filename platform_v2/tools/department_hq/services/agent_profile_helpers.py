"""Agent profile reads, validation and governance audit helpers."""


def get_identity_prompt(agent_id: int, *, logger):
    """Fetch identity_prompt from agent_portraits (single source of truth)."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT COALESCE(NULLIF(a.avatar_generation_prompt, ''), "
                "NULLIF(a.portrait_prompt, ''), NULLIF(ap.identity_prompt, '')) AS identity_prompt "
                "FROM agents a LEFT JOIN agent_portraits ap ON ap.agent_id = a.id "
                "WHERE a.id = %s",
                (agent_id,),
            )
            row = cur.fetchone()
            return row["identity_prompt"] if row else None
    except Exception as exc:
        logger.warning("Could not load identity prompt for agent %s: %s", agent_id, exc)
        return None


def get_voice_profile(agent_id: int, *, logger):
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT profile_name, speaker, speed, pitch_shift, warmth,
                       default_emotion, emotion_overrides, is_active, updated_at
                FROM agent_voice_profiles
                WHERE agent_id = %s AND is_active = TRUE
                ORDER BY updated_at DESC NULLS LAST, id DESC
                LIMIT 1
                """,
                (agent_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            profile = dict(row)
            for key in ("speed", "pitch_shift", "warmth"):
                if profile.get(key) is not None:
                    profile[key] = float(profile[key])
            if profile.get("updated_at"):
                profile["updated_at"] = profile["updated_at"].isoformat()
            return profile
    except Exception as exc:
        logger.warning("Could not load voice profile for agent %s: %s", agent_id, exc)
        return None


def validate_patch_payload(agent_id, payload, *, departments, get_agent, is_model_available):
    """Return None if ok; else dict with error + field keys (for jsonify)."""
    if "temperature" in payload:
        t = payload["temperature"]
        if not isinstance(t, (int, float)) or isinstance(t, bool) or not (0.0 <= float(t) <= 2.0):
            return {"error": "invalid_value", "field": "temperature"}
    if "max_tokens" in payload:
        mt = payload["max_tokens"]
        if not isinstance(mt, int) or isinstance(mt, bool) or not (1 <= mt <= 8192):
            return {"error": "invalid_value", "field": "max_tokens"}
    if "auto_approve_threshold" in payload:
        th = payload["auto_approve_threshold"]
        if not isinstance(th, (int, float)) or isinstance(th, bool) or not (0.0 <= float(th) <= 1000.0):
            return {"error": "invalid_value", "field": "auto_approve_threshold"}
    if "is_department_ai" in payload and not isinstance(payload["is_department_ai"], bool):
        return {"error": "invalid_value", "field": "is_department_ai"}
    if "social_topics" in payload:
        s = payload["social_topics"]
        if not isinstance(s, list) or not all(isinstance(x, str) for x in s):
            return {"error": "invalid_value", "field": "social_topics"}
    if "department" in payload:
        if payload["department"] not in departments:
            return {"error": "invalid_value", "field": "department"}
    if "reports_to_agent_id" in payload:
        rt = payload["reports_to_agent_id"]
        if rt is not None:
            if rt == agent_id:
                return {
                    "error": "reports_to_self",
                    "field": "reports_to_agent_id",
                }
            target = get_agent(rt)
            if not target:
                return {
                    "error": "reports_to_missing",
                    "field": "reports_to_agent_id",
                }
    if "model" in payload:
        ok, msg = is_model_available(payload["model"])
        if not ok:
            return {
                "error": "model_not_available",
                "field": "model",
                "detail": msg,
            }
    return None


def audit_profile_update(*, agent_id, user_id, before, after, serialize, logger):
    """Write one governance_audit_log row per successful profile save."""
    from database import get_db_cursor

    details = {"before": before, "after": after}
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO governance_audit_log
                    (event_type, event_category, agent_id, user_id,
                     action, details, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, NOW())
                """,
                (
                    "agent_profile_update",
                    "agent_management",
                    agent_id,
                    user_id,
                    "profile_update",
                    serialize(details, default=str),
                ),
            )
    except Exception as e:
        logger.warning("governance_audit_log write failed for agent %s: %s", agent_id, e)
