"""
Game Studio — World State Service (Phase 4)
Manages shared world resources, events, and player profiles for multiplayer.
"""

import logging
import random
import string
from datetime import datetime

from database import get_db_cursor

logger = logging.getLogger(__name__)

_ADJECTIVES = ["Swift", "Bold", "Keen", "Iron", "Star", "Nova", "Dark", "Bright"]
_NOUNS = ["Pilot", "Scout", "Ranger", "Warden", "Hunter", "Trader", "Sentinel", "Voyager"]


def _random_display_name():
    adj = random.choice(_ADJECTIVES)
    noun = random.choice(_NOUNS)
    suffix = "".join(random.choices(string.digits, k=3))
    return f"{adj}{noun}{suffix}"


def _serialize_row(row):
    """Convert a dict row — serialize datetime values to ISO strings."""
    if row is None:
        return None
    result = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# World Resources
# ---------------------------------------------------------------------------


def get_world_resources():
    """Return all world resources as {resource_type: float(amount)}."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT resource_type, amount FROM game_world_state")
            rows = cur.fetchall()
            return {row["resource_type"]: float(row["amount"]) for row in rows}
    except Exception as e:
        logger.error(f"[world_state] get_world_resources error: {e}")
        return {}


def update_resource(resource_type, delta, profile_id=None):
    """Apply delta to a resource (floor at 0). Returns new amount."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE game_world_state
                   SET amount = GREATEST(0, amount + %s),
                       last_updated_by = %s,
                       updated_at = NOW()
                 WHERE resource_type = %s
                RETURNING amount
                """,
                (delta, profile_id, resource_type),
            )
            row = cur.fetchone()
            return float(row["amount"]) if row else None
    except Exception as e:
        logger.error(f"[world_state] update_resource error: {e}")
        return None


def apply_session_effects(session_id):
    """Load world_effects from a game session and apply each delta."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT world_effects, host_profile_id FROM game_sessions WHERE id = %s",
                (session_id,),
            )
            row = cur.fetchone()
        if not row or not row["world_effects"]:
            return {}
        effects = row["world_effects"]  # {resource_type: delta}
        profile_id = row["host_profile_id"]
        results = {}
        for resource_type, delta in effects.items():
            new_amount = update_resource(resource_type, delta, profile_id)
            results[resource_type] = new_amount
        return results
    except Exception as e:
        logger.error(f"[world_state] apply_session_effects error: {e}")
        return {}


# ---------------------------------------------------------------------------
# World Events
# ---------------------------------------------------------------------------


def create_world_event(event_type, source_game_type=None, profile_id=None, data=None):
    """Insert a new world event, return event_id."""
    import psycopg2.extras as pex

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO game_world_events
                    (event_type, source_game_type, profile_id, data, consumed_by)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    event_type,
                    source_game_type,
                    profile_id,
                    pex.Json(data or {}),
                    pex.Json([]),
                ),
            )
            row = cur.fetchone()
            return row["id"] if row else None
    except Exception as e:
        logger.error(f"[world_state] create_world_event error: {e}")
        return None


def get_pending_events(game_type, limit=20):
    """Return events not yet consumed by the given game_type."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, event_type, source_game_type, source_session_id,
                       profile_id, data, consumed_by, created_at
                  FROM game_world_events
                 WHERE NOT (consumed_by @> %s::jsonb)
                 ORDER BY created_at DESC
                 LIMIT %s
                """,
                (f'["{game_type}"]', limit),
            )
            rows = cur.fetchall()
            return [_serialize_row(dict(r)) for r in rows]
    except Exception as e:
        logger.error(f"[world_state] get_pending_events error: {e}")
        return []


def mark_event_consumed(event_id, game_type):
    """Append game_type to the consumed_by array for an event."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE game_world_events
                   SET consumed_by = consumed_by || %s::jsonb
                 WHERE id = %s
                   AND NOT (consumed_by @> %s::jsonb)
                """,
                (f'["{game_type}"]', event_id, f'["{game_type}"]'),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"[world_state] mark_event_consumed error: {e}")
        return False


# ---------------------------------------------------------------------------
# Player Profiles
# ---------------------------------------------------------------------------


def create_profile(user_id=None, guest_session_id=None, display_name=None):
    """Create a player profile. Returns {profile_id, display_name}."""
    import psycopg2.extras as pex

    name = display_name or _random_display_name()
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO game_player_profiles
                    (user_id, guest_session_id, display_name, avatar_config, stats, inventory)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, display_name
                """,
                (
                    user_id,
                    guest_session_id,
                    name,
                    pex.Json({}),
                    pex.Json({}),
                    pex.Json([]),
                ),
            )
            row = cur.fetchone()
            return {"profile_id": row["id"], "display_name": row["display_name"]}
    except Exception as e:
        logger.error(f"[world_state] create_profile error: {e}")
        return None


def get_profile(profile_id):
    """Return a player profile dict with serialized datetimes."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT * FROM game_player_profiles WHERE id = %s",
                (profile_id,),
            )
            row = cur.fetchone()
            return _serialize_row(dict(row)) if row else None
    except Exception as e:
        logger.error(f"[world_state] get_profile error: {e}")
        return None


def get_profile_by_user(user_id):
    """Return the profile for a given user_id."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT * FROM game_player_profiles WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            )
            row = cur.fetchone()
            return _serialize_row(dict(row)) if row else None
    except Exception as e:
        logger.error(f"[world_state] get_profile_by_user error: {e}")
        return None


def update_stats(profile_id, stat_deltas):
    """Merge numeric deltas into the profile's stats JSONB, return updated stats."""
    import psycopg2.extras as pex

    try:
        # Load current stats
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT stats FROM game_player_profiles WHERE id = %s",
                (profile_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        current = row["stats"] or {}
        for key, delta in stat_deltas.items():
            current[key] = current.get(key, 0) + delta
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE game_player_profiles SET stats = %s WHERE id = %s RETURNING stats",
                (pex.Json(current), profile_id),
            )
            updated = cur.fetchone()
            return updated["stats"] if updated else current
    except Exception as e:
        logger.error(f"[world_state] update_stats error: {e}")
        return None


def convert_guest(guest_session_id, user_id):
    """Promote a guest profile to a linked user profile."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE game_player_profiles
                   SET user_id = %s,
                       guest_session_id = NULL
                 WHERE guest_session_id = %s
                RETURNING id
                """,
                (user_id, guest_session_id),
            )
            row = cur.fetchone()
            return row["id"] if row else None
    except Exception as e:
        logger.error(f"[world_state] convert_guest error: {e}")
        return None
