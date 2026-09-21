"""Faith routes for devotionals, profiles, multi-tradition scripture, reflection, and safety support.

The module is split across several files to stay under the Code Health
LARGE_FILE threshold (600 lines) while keeping this ``routes`` module as the
single namespace the Faith tests ``mock.patch("tools.faith.routes.X")`` target:

- ``_constants.py``  — static data, limits, type aliases
- ``_data.py``       — scripture loaders / readers / search helpers (re-exported below)
- ``_scripture_routes.py``, ``_profile_routes.py``, ``_care_routes.py`` — handler blueprints

Handler submodules resolve module-level helpers through ``routes`` (``_R.*``) at
call time, so patches applied to ``tools.faith.routes.<name>`` are observed.
"""

from __future__ import annotations

import logging
from smtplib import SMTPException
from typing import Any

from flask import Response, jsonify, request
from psycopg2 import Error as PsycopgError
from werkzeug.exceptions import HTTPException

from . import faith_bp

from tools.department_hq.services.department_dispatcher import dispatch

BRIDGE_AVAILABLE = True

from database import get_db_cursor

logger = logging.getLogger(__name__)

from ._constants import (
    CRISIS_KEYWORDS,
    EMMANUEL_EMAIL,
    FAITH_SYSTEM_PROMPT,
    TRADITION_LABELS,
    JsonDict,
    JsonResponse,
)
from ._data import (
    _clamped_search_limit,
    _collection_meta,
    _load_encyclopedia_entries,
    _load_scripture_corpus,
    _load_tao_legge,
    _load_web_bible,
    _lookup_book_code,
    _public_scripture_record,
    _reader_units,
    _scripture_toc,
    _serialize_book,
)

__all__ = [
    "BRIDGE_AVAILABLE",
    "archie_bridge",
    "faith_bp",
    "_care_routes",
    "_clamped_search_limit",
    "_collection_meta",
    "_ensure_tables",
    "_get_user_faith_profile",
    "_load_encyclopedia_entries",
    "_load_scripture_corpus",
    "_load_tao_legge",
    "_load_web_bible",
    "_lookup_book_code",
    "_practice_dispatch",
    "_profile_routes",
    "_public_scripture_record",
    "_reader_units",
    "_save_message",
    "_scripture_routes",
    "_scripture_toc",
    "_serialize_book",
]


@faith_bp.errorhandler(Exception)
def handle_unexpected_error(error: Exception) -> JsonResponse | HTTPException:
    if isinstance(error, HTTPException):
        return error
    logger.error("[Faith] Unhandled route error", exc_info=True)
    return jsonify({"success": False, "error": "Faith module error"}), 500


def _faith_system_prompt_for_profile(profile: JsonDict | None = None) -> str:
    profile = profile or {}
    tradition = profile.get("tradition_preference") or "christian"
    prayer_style = profile.get("prayer_style") or "guided"
    tradition_label = TRADITION_LABELS.get(tradition, tradition)
    return (
        FAITH_SYSTEM_PROMPT
        + "\n\nUser faith profile:\n"
        + f"- Tradition preference: {tradition_label}\n"
        + f"- Prayer/meditation style: {prayer_style}\n"
        + "- Keep all guidance aligned with this profile unless the user asks otherwise."
    )


def _row_value(row: Any, key: str, index: int = 0, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError):
        try:
            return row[index]
        except (IndexError, TypeError):
            return default


def _default_profile() -> JsonDict:
    return {
        "tradition_preference": "christian",
        "prayer_style": "guided",
        "scripture_translation": "web",
    }


def _validation_error(message: str) -> tuple[Response, int]:
    return jsonify({"success": False, "error": message}), 400


def _json_body() -> tuple[JsonDict, str | None]:
    data = request.get_json(force=True, silent=True)
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return {}, "JSON body must be an object"
    return data, None


def _string_field(
    data: JsonDict,
    field: str,
    *,
    required: bool = False,
    max_chars: int | None = None,
) -> tuple[str, str | None]:
    value = data.get(field)
    if value is None:
        return "", f"{field} required" if required else None
    if not isinstance(value, str):
        return "", f"{field} must be a string"
    value = value.strip()
    if required and not value:
        return "", f"{field} required"
    if max_chars is not None and len(value) > max_chars:
        return "", f"{field} must be {max_chars} characters or fewer"
    return value, None


def _ensure_tables() -> None:
    """Create the small Faith-owned tables when a migration is not available."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS faith_profiles (
                user_id INTEGER PRIMARY KEY,
                tradition_preference TEXT NOT NULL DEFAULT 'christian',
                prayer_style TEXT NOT NULL DEFAULT 'guided',
                scripture_translation TEXT NOT NULL DEFAULT 'web',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS faith_sessions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                role TEXT,
                message TEXT,
                session_type TEXT NOT NULL DEFAULT 'chat',
                title TEXT,
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS faith_checkins (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
                reflection TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS faith_journal (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                title TEXT,
                content TEXT NOT NULL,
                scripture_ref TEXT,
                tags TEXT[] NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS faith_practices_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                practice_type TEXT NOT NULL,
                notes TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute("ALTER TABLE faith_profiles ADD COLUMN IF NOT EXISTS user_id INTEGER")
        cur.execute(
            "ALTER TABLE faith_profiles ADD COLUMN IF NOT EXISTS tradition_preference TEXT NOT NULL DEFAULT 'christian'"
        )
        cur.execute("ALTER TABLE faith_profiles ADD COLUMN IF NOT EXISTS prayer_style TEXT NOT NULL DEFAULT 'guided'")
        cur.execute(
            "ALTER TABLE faith_profiles ADD COLUMN IF NOT EXISTS scripture_translation TEXT NOT NULL DEFAULT 'web'"
        )
        cur.execute("ALTER TABLE faith_profiles ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
        cur.execute("ALTER TABLE faith_profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
        cur.execute("ALTER TABLE faith_sessions ADD COLUMN IF NOT EXISTS user_id INTEGER")
        cur.execute("ALTER TABLE faith_sessions ADD COLUMN IF NOT EXISTS role TEXT")
        cur.execute("ALTER TABLE faith_sessions ADD COLUMN IF NOT EXISTS message TEXT")
        cur.execute("ALTER TABLE faith_sessions ADD COLUMN IF NOT EXISTS session_type TEXT NOT NULL DEFAULT 'chat'")
        cur.execute("ALTER TABLE faith_sessions ADD COLUMN IF NOT EXISTS title TEXT")
        cur.execute("ALTER TABLE faith_sessions ADD COLUMN IF NOT EXISTS duration_seconds INTEGER NOT NULL DEFAULT 0")
        cur.execute("ALTER TABLE faith_sessions ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb")
        cur.execute("ALTER TABLE faith_sessions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
        cur.execute("ALTER TABLE faith_checkins ADD COLUMN IF NOT EXISTS user_id INTEGER")
        cur.execute("ALTER TABLE faith_checkins ADD COLUMN IF NOT EXISTS score INTEGER")
        cur.execute("ALTER TABLE faith_checkins ADD COLUMN IF NOT EXISTS reflection TEXT")
        cur.execute("ALTER TABLE faith_checkins ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
        cur.execute("ALTER TABLE faith_journal ADD COLUMN IF NOT EXISTS user_id INTEGER")
        cur.execute("ALTER TABLE faith_journal ADD COLUMN IF NOT EXISTS title TEXT")
        cur.execute("ALTER TABLE faith_journal ADD COLUMN IF NOT EXISTS content TEXT")
        cur.execute("ALTER TABLE faith_journal ADD COLUMN IF NOT EXISTS scripture_ref TEXT")
        cur.execute("ALTER TABLE faith_journal ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}'")
        cur.execute("ALTER TABLE faith_journal ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
        cur.execute("ALTER TABLE faith_practices_log ADD COLUMN IF NOT EXISTS user_id INTEGER")
        cur.execute("ALTER TABLE faith_practices_log ADD COLUMN IF NOT EXISTS practice_type TEXT")
        cur.execute("ALTER TABLE faith_practices_log ADD COLUMN IF NOT EXISTS notes TEXT")
        cur.execute(
            "ALTER TABLE faith_practices_log ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
        )


def _get_user_faith_profile(user_id: int) -> JsonDict:
    try:
        _ensure_tables()
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                SELECT tradition_preference, prayer_style, scripture_translation
                FROM faith_profiles
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                cur.execute(
                    """
                    INSERT INTO faith_profiles (user_id)
                    VALUES (%s)
                    RETURNING tradition_preference, prayer_style, scripture_translation
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
    except PsycopgError:
        logger.exception("[Faith] Failed to load faith profile context")
        return _default_profile()

    return {
        "tradition_preference": _row_value(row, "tradition_preference", 0, "christian"),
        "prayer_style": _row_value(row, "prayer_style", 1, "guided"),
        "scripture_translation": _row_value(row, "scripture_translation", 2, "web"),
    }


def archie_bridge(prompt: str, system_prompt: str = FAITH_SYSTEM_PROMPT) -> JsonDict:
    """Compatibility wrapper around DHQ dispatch for existing Faith tests/callers."""
    result = dispatch(
        capability="support",
        prompt=prompt,
        module_id="faith",
        system_prompt=system_prompt,
    )
    return {
        "success": bool(result and result.success),
        "response": getattr(result, "response", "") if result else "",
        "model_used": getattr(result, "model_used", "dhq") if result else "dhq",
        "agent": getattr(result, "agent_name", "F.A.I.T.H.") if result else "F.A.I.T.H.",
        "error": getattr(result, "error", None) if result else None,
    }


def _detect_crisis(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in CRISIS_KEYWORDS)


def _save_message(user_id: int, role: str, message: str) -> None:
    try:
        _ensure_tables()
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO faith_sessions (user_id, role, message, session_type)
                VALUES (%s, %s, %s, 'chat')
                """,
                (user_id, role, message),
            )
    except PsycopgError:
        logger.exception("[Faith] Failed to save session message")


def _practice_dispatch(
    user_id: int,
    practice_type: str,
    prompt: str,
    notes: str = "",
    profile: JsonDict | None = None,
) -> JsonDict:
    system_prompt = _faith_system_prompt_for_profile(profile or _get_user_faith_profile(user_id))
    if BRIDGE_AVAILABLE:
        try:
            result = archie_bridge(prompt, system_prompt)
        except (OSError, RuntimeError, ValueError) as e:
            logger.error(f"[Faith] practice dispatch failed: {e}")
            result = {
                "success": False,
                "response": "F.A.I.T.H. is unavailable.",
                "model_used": "dhq",
                "agent": "F.A.I.T.H.",
            }
    else:
        result = {"success": False, "response": "F.A.I.T.H. is unavailable.", "model_used": "none", "agent": "none"}

    if result.get("success"):
        try:
            _ensure_tables()
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    "INSERT INTO faith_practices_log (user_id, practice_type, notes) VALUES (%s, %s, %s)",
                    (user_id, practice_type, notes or result.get("response", "")[:500]),
                )
        except PsycopgError:
            logger.exception("[Faith] Failed to log practice")
    return result


def _send_chaplain_email(user_display_name: str, message: str, context_entries: list[JsonDict]) -> bool:
    try:
        from services.email_service import send_email  # type: ignore

        context_block = ""
        if context_entries:
            context_block = "\n\nShared journal context:\n" + "\n---\n".join(
                f"{e.get('title', 'Untitled')}: {e.get('content', '')[:300]}" for e in context_entries
            )
        send_email(
            from_address="faith@kytranempowerment.com",
            to_address=EMMANUEL_EMAIL,
            subject=f"Spiritual Care Request — {user_display_name}",
            body=f"Spiritual Care Request\nFrom: {user_display_name}\n\nMessage:\n{message}{context_block}",
        )
        return True
    except (ImportError, OSError, RuntimeError, SMTPException, ValueError):
        logger.exception("[Faith] Failed to send chaplain email")
        return False


# Handler submodules. Imported LAST so circular imports resolve: when a
# submodule does ``from . import routes as _R`` it receives this module as it
# is now, with every helper and re-export already bound above.
from . import _care_routes, _profile_routes, _scripture_routes  # noqa: E402
