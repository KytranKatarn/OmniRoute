"""Faith care routes — chat, practices, check-ins, journal, and chaplain contact."""

from __future__ import annotations

import logging

from flask import Response, jsonify, request
from flask_login import current_user, login_required
from psycopg2 import Error as PsycopgError
from psycopg2.extras import Json
from services.time_utils import now_utc

from . import faith_bp, routes as _R
from ._constants import (
    ALLOWED_PRAYER_TYPES,
    MAX_CHAPLAIN_CONTEXT_IDS,
    MAX_CHAPLAIN_MESSAGE_CHARS,
    MAX_LECTIO_PASSAGE_CHARS,
    MAX_PRAYER_INTENTION_CHARS,
    TRADITION_LABELS,
    JsonDict,
    JsonResponse,
)

logger = logging.getLogger(__name__)


@faith_bp.route("/api/faith/chat", methods=["POST"])
@login_required
def chat() -> JsonResponse:
    data: JsonDict = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"success": False, "error": "message required"}), 400

    user_id = current_user.id
    crisis = _R._detect_crisis(message)
    _R._save_message(user_id, "user", message)
    profile = _R._get_user_faith_profile(user_id)
    system_prompt = _R._faith_system_prompt_for_profile(profile)

    result = None
    try:
        result = _R.archie_bridge(message, system_prompt)
        response_text = result.get("response", "") if result else ""
        response_text = response_text.strip()
    except (OSError, RuntimeError, ValueError) as e:
        logger.error(f"[Faith] dispatch failed: {e}")
        response_text = "F.A.I.T.H. is unavailable right now."

    if crisis:
        crisis_block = (
            "I am concerned about your safety. Please contact immediate support now: "
            "call or text 988, or text HOME to 741741 for the Crisis Text Line. "
            "If there is immediate danger, call emergency services. You can also use "
            "Connect with Emmanuel for chaplain support, but crisis services are the "
            "right first step right now."
        )
        response_text = f"{crisis_block}\n\n{response_text}" if response_text else crisis_block

    _R._save_message(user_id, "assistant", response_text)

    return jsonify(
        {
            "success": bool(response_text),
            "response": response_text,
            "model": result.get("model_used", "dhq") if result else "dhq",
            "agent": result.get("agent", "F.A.I.T.H.") if result else "F.A.I.T.H.",
            "crisis_detected": crisis,
        }
    )


@faith_bp.route("/api/reflection")
@faith_bp.route("/api/faith/reflection")
@faith_bp.route("/api/faith/devotional")
@login_required
def devotional() -> Response:
    today = now_utc().date().isoformat()
    profile = _R._get_user_faith_profile(current_user.id)
    tradition = TRADITION_LABELS.get(profile.get("tradition_preference"), "broad Christian")
    prompt = (
        f"Generate a daily spiritual reflection for {today} for a {tradition} user. "
        "Include: (1) one appropriate sacred-text passage or wisdom excerpt with reference, "
        "(2) 2-3 sentence reflection, (3) one meditation question. Under 150 words. "
        "Respect the user's tradition and do not substitute another tradition unless the profile is interfaith or unspecified."
    )
    result = _R._practice_dispatch(current_user.id, "devotional", prompt, profile=profile)
    return jsonify({"success": result.get("success", False), "response": result.get("response", ""), "date": today})


@faith_bp.route("/api/timer", methods=["POST"])
@faith_bp.route("/api/faith/timer", methods=["POST"])
@login_required
def save_timer_session() -> JsonResponse:
    data: JsonDict = request.get_json(force=True, silent=True) or {}
    session_type = (data.get("session_type") or data.get("type") or "meditation").strip().lower()
    title = (data.get("title") or "").strip() or session_type.title()
    notes = (data.get("notes") or "").strip()
    try:
        duration_seconds = int(data.get("duration_seconds") or data.get("duration") or 0)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "duration_seconds must be a number"}), 400
    if duration_seconds < 1 or duration_seconds > 86400:
        return jsonify({"success": False, "error": "duration_seconds must be between 1 and 86400"}), 400

    try:
        _R._ensure_tables()
        with _R.get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO faith_sessions (
                    user_id, session_type, title, duration_seconds, message, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (
                    current_user.id,
                    session_type,
                    title,
                    duration_seconds,
                    notes or None,
                    Json({"source": "timer"}),
                ),
            )
            row = cur.fetchone()
    except PsycopgError:
        logger.exception("[Faith] Failed to save timer session")
        return jsonify({"success": False, "error": "Failed to save timer session"}), 500

    return (
        jsonify(
            {
                "success": True,
                "session": {
                    "id": _R._row_value(row, "id", 0),
                    "session_type": session_type,
                    "title": title,
                    "duration_seconds": duration_seconds,
                    "created_at": (
                        _R._row_value(row, "created_at", 1).isoformat() if _R._row_value(row, "created_at", 1) else None
                    ),
                },
            }
        ),
        201,
    )


@faith_bp.route("/api/sessions", methods=["GET"])
@faith_bp.route("/api/faith/sessions", methods=["GET"])
@login_required
def list_sessions() -> JsonResponse:
    try:
        limit = min(max(int(request.args.get("limit", "20")), 1), 100)
    except ValueError:
        limit = 20
    try:
        _R._ensure_tables()
        with _R.get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT id, session_type, title, duration_seconds, role, message, created_at
                FROM faith_sessions
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (current_user.id, limit),
            )
            rows = cur.fetchall()
    except PsycopgError:
        logger.exception("[Faith] Failed to load sessions")
        return jsonify({"success": False, "error": "Failed to load sessions"}), 500

    sessions: list[JsonDict] = []
    for row in rows:
        created_at = _R._row_value(row, "created_at", 6)
        sessions.append(
            {
                "id": _R._row_value(row, "id", 0),
                "session_type": _R._row_value(row, "session_type", 1),
                "title": _R._row_value(row, "title", 2),
                "duration_seconds": _R._row_value(row, "duration_seconds", 3),
                "role": _R._row_value(row, "role", 4),
                "message": _R._row_value(row, "message", 5),
                "created_at": created_at.isoformat() if created_at else None,
            }
        )
    return jsonify({"success": True, "sessions": sessions})


@faith_bp.route("/api/faith/prayer", methods=["POST"])
@login_required
def guided_prayer() -> JsonResponse:
    data: JsonDict
    error: str | None
    data, error = _R._json_body()
    if error:
        return _R._validation_error(error)
    if "prayer_type" in data:
        prayer_type, error = _R._string_field(data, "prayer_type", required=True, max_chars=32)
    else:
        prayer_type, error = _R._string_field(data, "type", required=True, max_chars=32)
    if error:
        return _R._validation_error("prayer_type required" if error == "type required" else error)
    prayer_type = prayer_type.lower()
    if prayer_type not in ALLOWED_PRAYER_TYPES:
        return _R._validation_error("prayer_type must be one of: " + ", ".join(sorted(ALLOWED_PRAYER_TYPES)))

    intention, error = _R._string_field(data, "intention", max_chars=MAX_PRAYER_INTENTION_CHARS)
    if error:
        return _R._validation_error(error)
    profile = _R._get_user_faith_profile(current_user.id)
    tradition = TRADITION_LABELS.get(profile.get("tradition_preference"), "broad Christian")
    style = profile.get("prayer_style") or "guided"
    prompt = (
        f"Guide me through a {style} {prayer_type} prayer or meditation for a {tradition} user"
        + (f" for: {intention}" if intention else "")
        + ". Structure: Opening, Body, Silence ('...'), Closing. Under 120 words. "
        "For non-theistic traditions, use contemplative language instead of imposed prayer language."
    )
    result = _R._practice_dispatch(
        current_user.id,
        "prayer",
        prompt,
        notes=f"{prayer_type}: {intention}",
        profile=profile,
    )
    return jsonify({"success": result.get("success", False), "response": result.get("response", "")})


@faith_bp.route("/api/faith/scripture-search", methods=["POST"])
@login_required
def scripture_search() -> JsonResponse:
    data: JsonDict = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"success": False, "error": "query required"}), 400
    profile = _R._get_user_faith_profile(current_user.id)
    tradition = TRADITION_LABELS.get(profile.get("tradition_preference"), "broad Christian")
    prompt = (
        f"Find 3 relevant sacred-text passages for a {tradition} user about: '{query}'. "
        "Use the user's tradition when possible; for interfaith or unspecified users, include a clearly labeled mix from the saved local corpus. "
        "For each: reference, short excerpt, one sentence of context. Numbered list."
    )
    result = _R._practice_dispatch(current_user.id, "scripture", prompt, notes=query, profile=profile)
    return jsonify({"success": result.get("success", False), "response": result.get("response", ""), "query": query})


@faith_bp.route("/api/faith/lectio", methods=["POST"])
@login_required
def lectio_divina() -> JsonResponse:
    data: JsonDict
    error: str | None
    data, error = _R._json_body()
    if error:
        return _R._validation_error(error)
    passage, error = _R._string_field(data, "passage", required=True, max_chars=MAX_LECTIO_PASSAGE_CHARS)
    if error:
        return _R._validation_error(error)
    profile = _R._get_user_faith_profile(current_user.id)
    tradition = TRADITION_LABELS.get(profile.get("tradition_preference"), "broad Christian")
    prompt = (
        f"Guide a {tradition} user through sacred reading with {passage}. "
        "Use four movements: 1. Read (passage or excerpt), 2. Reflect (question), "
        "3. Respond (prayer, intention, or meditation prompt), 4. Rest (stillness invitation). 2-3 sentences each. "
        "If Lectio Divina language is not appropriate for the selected tradition, adapt it respectfully."
    )
    result = _R._practice_dispatch(current_user.id, "lectio", prompt, notes=passage, profile=profile)
    return jsonify(
        {"success": result.get("success", False), "response": result.get("response", ""), "passage": passage}
    )


@faith_bp.route("/api/faith/checkin", methods=["POST"])
@login_required
def checkin() -> JsonResponse:
    data: JsonDict = request.get_json(force=True, silent=True) or {}
    try:
        score = int(data.get("score"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "score must be 1-5"}), 400
    reflection = (data.get("reflection") or "").strip()
    if not (1 <= score <= 5):
        return jsonify({"success": False, "error": "score must be 1-5"}), 400
    try:
        _R._ensure_tables()
        with _R.get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_checkins (user_id, score, reflection) VALUES (%s, %s, %s) RETURNING id",
                (current_user.id, score, reflection or None),
            )
            checkin_id = _R._row_value(cur.fetchone(), "id", 0)
        with _R.get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_practices_log (user_id, practice_type, notes) VALUES (%s, 'checkin', %s)",
                (current_user.id, f"score={score}"),
            )
    except PsycopgError:
        logger.exception("[Faith] Failed to save check-in")
        return jsonify({"success": False, "error": "Failed to save"}), 500
    return jsonify({"success": True, "id": checkin_id}), 201


@faith_bp.route("/api/faith/checkin/history")
@login_required
def checkin_history() -> JsonResponse:
    try:
        _R._ensure_tables()
        with _R.get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT id, score, reflection, created_at FROM faith_checkins "
                "WHERE user_id = %s ORDER BY created_at DESC LIMIT 30",
                (current_user.id,),
            )
            rows: list[JsonDict] = [dict(r) for r in cur.fetchall()]
    except PsycopgError:
        logger.exception("[Faith] Failed to load check-in history")
        return jsonify({"success": False, "error": "Failed to load"}), 500
    return jsonify({"success": True, "checkins": rows})


@faith_bp.route("/api/faith/journal", methods=["POST"])
@login_required
def journal_save() -> JsonResponse:
    data: JsonDict = request.get_json(force=True, silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"success": False, "error": "content required"}), 400
    title = (data.get("title") or "").strip() or None
    scripture_ref = (data.get("scripture_ref") or "").strip() or None
    tags = data.get("tags") or []
    try:
        _R._ensure_tables()
        with _R.get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_journal (user_id, title, content, scripture_ref, tags) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (current_user.id, title, content, scripture_ref, tags),
            )
            entry_id = _R._row_value(cur.fetchone(), "id", 0)
    except PsycopgError:
        logger.exception("[Faith] Failed to save journal entry")
        return jsonify({"success": False, "error": "Failed to save"}), 500
    return jsonify({"success": True, "id": entry_id}), 201


@faith_bp.route("/api/faith/journal")
@login_required
def journal_list() -> JsonResponse:
    tag_filter = request.args.get("tag")
    try:
        _R._ensure_tables()
        with _R.get_db_cursor() as (_conn, cur):
            if tag_filter:
                cur.execute(
                    "SELECT id, title, content, scripture_ref, tags, created_at FROM faith_journal "
                    "WHERE user_id = %s AND %s = ANY(tags) ORDER BY created_at DESC LIMIT 50",
                    (current_user.id, tag_filter),
                )
            else:
                cur.execute(
                    "SELECT id, title, content, scripture_ref, tags, created_at FROM faith_journal "
                    "WHERE user_id = %s ORDER BY created_at DESC LIMIT 50",
                    (current_user.id,),
                )
            rows: list[JsonDict] = [dict(r) for r in cur.fetchall()]
    except PsycopgError:
        logger.exception("[Faith] Failed to load journal")
        return jsonify({"success": False, "error": "Failed to load"}), 500
    return jsonify({"success": True, "entries": rows})


@faith_bp.route("/api/faith/connect-chaplain", methods=["POST"])
@login_required
def connect_chaplain() -> JsonResponse:
    data: JsonDict
    error: str | None
    data, error = _R._json_body()
    if error:
        return _R._validation_error(error)
    message, error = _R._string_field(data, "message", required=True, max_chars=MAX_CHAPLAIN_MESSAGE_CHARS)
    if error:
        return _R._validation_error(error)

    journal_ids_raw = data.get("journal_ids") or []
    if not isinstance(journal_ids_raw, list):
        return _R._validation_error("journal_ids must be a list")
    if len(journal_ids_raw) > MAX_CHAPLAIN_CONTEXT_IDS:
        return _R._validation_error(f"journal_ids may include at most {MAX_CHAPLAIN_CONTEXT_IDS} entries")
    try:
        journal_ids: list[int] = [int(item) for item in journal_ids_raw]
    except (TypeError, ValueError):
        return _R._validation_error("journal_ids must contain only numeric ids")
    context_entries: list[JsonDict] = []
    if journal_ids:
        try:
            with _R.get_db_cursor() as (_conn, cur):
                cur.execute(
                    "SELECT title, content FROM faith_journal WHERE user_id = %s AND id = ANY(%s)",
                    (current_user.id, journal_ids),
                )
                context_entries = [dict(r) for r in cur.fetchall()]
        except PsycopgError:
            logger.warning("[Faith] Failed to load chaplain journal context", exc_info=True)

    display_name = getattr(current_user, "display_name", None) or getattr(current_user, "username", "Platform User")
    sent = _R._send_chaplain_email(display_name, message, context_entries)

    return jsonify(
        {
            "success": True,
            "sent": sent,
            "message": (
                "Your message has been sent to Emmanuel. He will be in touch."
                if sent
                else "Message queued — Emmanuel will receive it shortly."
            ),
        }
    )