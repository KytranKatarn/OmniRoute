"""
Game Studio — World Engine (Phase 5)
Processes cross-game world events and applies effects as bonuses/resource
changes/world config patches.  Runs on-demand or periodically.
"""

import logging

import psycopg2.extras as pex

from database import get_db_cursor
from tools.game_studio import world_state_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Effect map — defines what each world event does to each game type
# ---------------------------------------------------------------------------

EFFECT_MAP = {
    "battle_won": {
        "space_explorer": {
            "type": "bonus",
            "key": "pirate_threat_reduction",
            "value": 0.1,
        },
        "base_builder": {
            "type": "resource",
            "key": "supplies",
            "delta": 50,
        },
    },
    "planet_discovered": {
        "top_down_shooter": {
            "type": "world_change",
            "key": "new_arena",
            "generator": "generate_arena_from_planet",
        },
        "base_builder": {
            "type": "world_change",
            "key": "new_location",
            "generator": "generate_build_site",
        },
    },
    "colony_built": {
        "top_down_shooter": {
            "type": "bonus",
            "key": "health_depot",
            "value": 25,
        },
        "space_explorer": {
            "type": "world_change",
            "key": "new_station",
            "generator": "generate_trade_station",
        },
    },
    "raid_survived": {
        "top_down_shooter": {
            "type": "bonus",
            "key": "enemy_wave_reduction",
            "value": 2,
        },
        "space_explorer": {
            "type": "bonus",
            "key": "safe_zone_expansion",
            "value": 50,
        },
    },
    "trade_completed": {
        "top_down_shooter": {
            "type": "bonus",
            "key": "damage_boost",
            "value": 0.15,
        },
        "base_builder": {
            "type": "resource",
            "key": "metal",
            "delta": 20,
        },
    },
}

# ---------------------------------------------------------------------------
# Generator helpers
# ---------------------------------------------------------------------------


def generate_arena_from_planet(event_data: dict) -> dict:
    """Derive arena walls and extra enemies from a planet-discovered event."""
    planet_name = event_data.get("planet_name", "Unknown")
    threat = event_data.get("threat_level", 1)
    return {
        "walls": [
            {"x": 100, "y": 100, "w": 40, "h": 200, "label": f"{planet_name}_wall_1"},
            {"x": 400, "y": 200, "w": 200, "h": 40, "label": f"{planet_name}_wall_2"},
        ],
        "enemies": [{"type": "drone", "count": max(1, threat * 2), "speed": 1.2}],
    }


def generate_build_site(event_data: dict) -> dict:
    """Create new resource nodes for a newly discovered planet."""
    planet_name = event_data.get("planet_name", "NewWorld")
    return {
        "resourceNodes": [
            {
                "id": f"node_{planet_name}_metal",
                "type": "metal",
                "x": 320,
                "y": 240,
                "amount": 500,
            },
            {
                "id": f"node_{planet_name}_crystal",
                "type": "crystal",
                "x": 400,
                "y": 300,
                "amount": 200,
            },
        ]
    }


def generate_trade_station(event_data: dict) -> dict:
    """Generate a new trade station entry for space explorer."""
    colony_name = event_data.get("colony_name", "Colony")
    return {
        "stations": [
            {
                "id": f"station_{colony_name}",
                "name": f"{colony_name} Outpost",
                "x": event_data.get("x", 500),
                "y": event_data.get("y", 300),
                "trades": ["supplies", "trade_goods"],
            }
        ]
    }


_GENERATORS = {
    "generate_arena_from_planet": generate_arena_from_planet,
    "generate_build_site": generate_build_site,
    "generate_trade_station": generate_trade_station,
}

# ---------------------------------------------------------------------------
# Core engine functions
# ---------------------------------------------------------------------------


def process_pending_events() -> int:
    """
    Load all unconsumed world events, apply EFFECT_MAP effects, persist
    bonuses / resource changes / world config changes, then mark consumed.
    Returns the number of (event, game_type) effect pairs applied.
    """
    applied_count = 0
    try:
        # Fetch all events that have at least one unconsumed game type in EFFECT_MAP
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, event_type, source_game_type, profile_id, data, consumed_by
                  FROM game_world_events
                 ORDER BY created_at ASC
                """
            )
            events = cur.fetchall()

        for event in events:
            event_id = event["id"]
            event_type = event["event_type"]
            profile_id = event["profile_id"]
            event_data = event["data"] or {}
            consumed_by = event["consumed_by"] or []

            effects = EFFECT_MAP.get(event_type, {})
            if not effects:
                continue

            for game_type, effect in effects.items():
                # Skip if already consumed by this game type
                if game_type in consumed_by:
                    continue

                _apply_effect(game_type, effect, event_id, event_data, profile_id)
                world_state_service.mark_event_consumed(event_id, game_type)
                applied_count += 1

    except Exception as e:
        logger.error(f"[world_engine] process_pending_events error: {e}")

    return applied_count


def _apply_effect(game_type: str, effect: dict, event_id: int, event_data: dict, profile_id):
    """Dispatch a single effect to the appropriate persistence function."""
    effect_type = effect["type"]

    if effect_type == "bonus":
        _create_bonus(game_type, effect["key"], effect["value"], event_id)

    elif effect_type == "resource":
        world_state_service.update_resource(effect["key"], effect["delta"], profile_id)

    elif effect_type == "world_change":
        generator_fn = _GENERATORS.get(effect.get("generator", ""))
        patch = generator_fn(event_data) if generator_fn else {}
        _create_world_change(game_type, effect["key"], patch, event_id)

    else:
        logger.warning(f"[world_engine] Unknown effect type: {effect_type}")


def _create_bonus(game_type: str, bonus_key: str, bonus_value: float, source_event_id: int):
    """Persist a new bonus row."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO game_world_bonuses
                    (game_type, bonus_key, bonus_value, source_event_id)
                VALUES (%s, %s, %s, %s)
                """,
                (game_type, bonus_key, bonus_value, source_event_id),
            )
    except Exception as e:
        logger.error(f"[world_engine] _create_bonus error: {e}")


def _create_world_change(game_type: str, change_key: str, config_patch: dict, source_event_id: int):
    """Persist a new world change row."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO game_world_changes
                    (game_type, change_key, config_patch, source_event_id)
                VALUES (%s, %s, %s, %s)
                """,
                (game_type, change_key, pex.Json(config_patch), source_event_id),
            )
    except Exception as e:
        logger.error(f"[world_engine] _create_world_change error: {e}")


def get_active_bonuses(game_type: str) -> list:
    """Return all unexpired, unconsumed bonuses for the given game type."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT bonus_key, bonus_value
                  FROM game_world_bonuses
                 WHERE game_type = %s
                   AND consumed = FALSE
                   AND expires_at > NOW()
                 ORDER BY created_at ASC
                """,
                (game_type,),
            )
            rows = cur.fetchall()
            return [{"bonus_key": r["bonus_key"], "bonus_value": r["bonus_value"]} for r in rows]
    except Exception as e:
        logger.error(f"[world_engine] get_active_bonuses error: {e}")
        return []


def get_pending_world_changes(game_type: str) -> list:
    """Return all unapplied world config changes for the given game type."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT change_key, config_patch
                  FROM game_world_changes
                 WHERE game_type = %s
                   AND applied = FALSE
                 ORDER BY created_at ASC
                """,
                (game_type,),
            )
            rows = cur.fetchall()
            return [{"change_key": r["change_key"], "config_patch": r["config_patch"]} for r in rows]
    except Exception as e:
        logger.error(f"[world_engine] get_pending_world_changes error: {e}")
        return []


def mark_changes_applied(game_type: str) -> int:
    """Mark all unapplied world changes for game_type as applied. Returns rows updated."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE game_world_changes
                   SET applied = TRUE
                 WHERE game_type = %s
                   AND applied = FALSE
                """,
                (game_type,),
            )
            return cur.rowcount
    except Exception as e:
        logger.error(f"[world_engine] mark_changes_applied error: {e}")
        return 0


def apply_world_to_config(game_type: str, config: dict) -> dict:
    """
    Merge active bonuses and pending world changes into a game config dict.
    Returns the modified config (does NOT mark changes applied).
    """
    result = dict(config)

    bonuses = get_active_bonuses(game_type)
    if bonuses:
        result.setdefault("world_bonuses", [])
        result["world_bonuses"].extend(bonuses)

    changes = get_pending_world_changes(game_type)
    for change in changes:
        patch = change.get("config_patch") or {}
        for k, v in patch.items():
            if isinstance(v, list) and isinstance(result.get(k), list):
                result[k] = result[k] + v
            elif isinstance(v, dict) and isinstance(result.get(k), dict):
                result[k] = {**result[k], **v}
            else:
                result[k] = v

    return result
