"""Game server — Flask-SocketIO WebSocket handler for multiplayer.
Namespace: /game
"""

import logging
import secrets
import time
from flask_socketio import Namespace, emit, join_room, leave_room
from flask import request
from database import get_db_cursor
from psycopg2.extras import Json

logger = logging.getLogger(__name__)

# Server-side room state
# {room_code: {players: {sid: {profile_id, x, y, name, color, health}}, last_tick: float, host_sid: str}}
_rooms = {}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def generate_room_code():
    """Generate a 6-char room code avoiding I/O confusion."""
    return "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(6))


def create_session(game_id, host_profile_id, game_type, config, max_players=4):
    """Create a new game session in DB and init room state.

    Returns:
        dict with room_code and session_id
    """
    room_code = generate_room_code()
    # Ensure uniqueness (retry up to 5 times)
    for _ in range(5):
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT 1 FROM game_sessions WHERE room_code = %s", (room_code,))
            if not cur.fetchone():
                break
        room_code = generate_room_code()

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO game_sessions
               (game_id, room_code, host_profile_id, game_type, config, max_players,
                current_players, status, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, 0, 'lobby', NOW())
               RETURNING id""",
            (game_id, room_code, host_profile_id, game_type, Json(config), max_players),
        )
        session_id = cur.fetchone()[0]

    _rooms[room_code] = {
        "session_id": session_id,
        "game_id": game_id,
        "players": {},
        "host_sid": None,
        "last_tick": time.time(),
        "action_queue": [],
        "world_effects": [],
    }

    logger.info("Created session %s room_code=%s game_type=%s", session_id, room_code, game_type)
    return {"room_code": room_code, "session_id": session_id}


def end_session(room_code, profile_id):
    """End a game session, apply world effects, cleanup room state."""
    room = _rooms.get(room_code)
    if not room:
        return False

    # Verify caller is host
    host_entry = None
    for sid, p in room["players"].items():
        if p["profile_id"] == profile_id:
            host_entry = sid
            break
    if host_entry != room.get("host_sid") and room.get("host_sid") is not None:
        logger.warning("end_session called by non-host profile_id=%s room=%s", profile_id, room_code)

    # Apply world effects if any
    effects = room.get("world_effects", [])
    if effects:
        try:
            from tools.game_studio.world_state_service import apply_session_effects

            apply_session_effects(room_code, effects)
        except ImportError:
            logger.debug("world_state_service not available, skipping effects")
        except Exception as exc:
            logger.error("apply_session_effects failed: %s", exc)

    # Update DB
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("UPDATE game_sessions SET status='ended', ended_at=NOW() WHERE room_code=%s", (room_code,))

    # Notify players
    emit("game_ended", {"room_code": room_code}, room=room_code, namespace="/game")

    # Cleanup
    _rooms.pop(room_code, None)
    return True


# ---------------------------------------------------------------------------
# Namespace
# ---------------------------------------------------------------------------


class GameNamespace(Namespace):
    """Flask-SocketIO namespace for multiplayer game sessions."""

    # ------------------------------------------------------------------
    # Join / Leave
    # ------------------------------------------------------------------

    def on_join_session(self, data):
        room_code = data.get("room_code", "").upper()
        profile_id = data.get("profile_id")
        sid = request.sid

        if not room_code or not profile_id:
            emit("error", {"message": "room_code and profile_id required"})
            return

        # Validate session exists in DB and is open
        session_row = None
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, max_players, current_players, host_profile_id, config
                   FROM game_sessions
                   WHERE room_code = %s AND status IN ('lobby', 'playing')""",
                (room_code,),
            )
            session_row = cur.fetchone()

        if not session_row:
            emit("error", {"message": "Session not found or already ended"})
            return

        session_id, max_players, current_players, host_profile_id, session_config = session_row

        if current_players >= max_players:
            emit("error", {"message": "Session is full"})
            return

        # Load display name
        display_name = str(profile_id)
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT display_name FROM game_profiles WHERE id = %s", (profile_id,))
            row = cur.fetchone()
            if row:
                display_name = row[0]

        # Join SocketIO room
        join_room(room_code)

        # Init room state if needed
        if room_code not in _rooms:
            _rooms[room_code] = {
                "session_id": session_id,
                "players": {},
                "host_sid": None,
                "last_tick": time.time(),
                "action_queue": [],
                "world_effects": [],
            }

        room = _rooms[room_code]

        # Assign color based on player count
        colors = ["#4af", "#fa4", "#4fa", "#f4a", "#af4", "#a4f"]
        color = colors[len(room["players"]) % len(colors)]

        room["players"][sid] = {
            "profile_id": profile_id,
            "x": 400,
            "y": 400,
            "name": display_name,
            "color": color,
            "health": 100,
            "last_shot": 0.0,
        }

        # First player becomes host
        if room["host_sid"] is None:
            room["host_sid"] = sid

        # Update player count in DB
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE game_sessions SET current_players = current_players + 1 WHERE room_code = %s", (room_code,)
            )

        emit("player_joined", {"profile_id": profile_id, "name": display_name, "color": color}, room=room_code)
        logger.info("Player %s joined room %s as sid=%s", profile_id, room_code, sid)

    def on_leave_session(self, data):
        room_code = data.get("room_code", "").upper()
        profile_id = data.get("profile_id")
        sid = request.sid

        self._remove_player(sid, room_code, profile_id)

    def _remove_player(self, sid, room_code, profile_id=None):
        """Remove a player from room state and notify others."""
        room = _rooms.get(room_code)
        if not room:
            return

        player = room["players"].pop(sid, None)
        if not player:
            return

        actual_profile_id = player["profile_id"]
        leave_room(room_code)

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE game_sessions SET current_players = GREATEST(current_players - 1, 0) WHERE room_code = %s",
                (room_code,),
            )

        emit("player_left", {"profile_id": actual_profile_id}, room=room_code)

        # If host left and others remain, assign new host
        if room["host_sid"] == sid and room["players"]:
            new_host_sid = next(iter(room["players"]))
            room["host_sid"] = new_host_sid
            new_host_profile_id = room["players"][new_host_sid]["profile_id"]
            emit("host_changed", {"profile_id": new_host_profile_id}, room=room_code)
            logger.info("New host for room %s: sid=%s profile_id=%s", room_code, new_host_sid, new_host_profile_id)

        # If room is empty, cleanup
        if not room["players"]:
            _rooms.pop(room_code, None)
            logger.info("Room %s is empty, cleaned up", room_code)

    # ------------------------------------------------------------------
    # Player actions
    # ------------------------------------------------------------------

    def on_player_action(self, data):
        room_code = data.get("room_code", "").upper()
        action_type = data.get("action_type")
        action_data = data.get("action_data", {})
        sid = request.sid

        room = _rooms.get(room_code)
        if not room:
            return

        player = room["players"].get(sid)
        if not player:
            return

        if action_type == "move":
            player["x"] = float(action_data.get("x", player["x"]))
            player["y"] = float(action_data.get("y", player["y"]))
            if "health" in action_data:
                player["health"] = float(action_data["health"])

        elif action_type == "shoot":
            now = time.time()
            cooldown = 0.2  # seconds
            if now - player.get("last_shot", 0) >= cooldown:
                player["last_shot"] = now
                room["action_queue"].append(
                    {
                        "type": "shoot",
                        "profile_id": player["profile_id"],
                        "x": player["x"],
                        "y": player["y"],
                        "dx": action_data.get("dx", 0),
                        "dy": action_data.get("dy", 0),
                        "timestamp": now,
                    }
                )

        elif action_type in ("interact", "build", "navigate"):
            room["action_queue"].append(
                {
                    "type": action_type,
                    "profile_id": player["profile_id"],
                    "data": action_data,
                    "timestamp": time.time(),
                }
            )

        # Broadcast updated state to all players in room
        state = {
            "players": {
                p["profile_id"]: {
                    "x": p["x"],
                    "y": p["y"],
                    "name": p["name"],
                    "color": p["color"],
                    "health": p["health"],
                }
                for p in room["players"].values()
            }
        }
        emit("state_update", state, room=room_code)
        room["last_tick"] = time.time()

    # ------------------------------------------------------------------
    # Game lifecycle
    # ------------------------------------------------------------------

    def on_start_game(self, data):
        room_code = data.get("room_code", "").upper()
        sid = request.sid

        room = _rooms.get(room_code)
        if not room:
            emit("error", {"message": "Room not found"})
            return

        if room.get("host_sid") != sid:
            emit("error", {"message": "Only the host can start the game"})
            return

        # Load session config
        session_config = {}
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("UPDATE game_sessions SET status='playing' WHERE room_code=%s RETURNING config", (room_code,))
            row = cur.fetchone()
            if row:
                session_config = row[0] or {}

        emit("game_started", {"config": session_config}, room=room_code)
        logger.info("Game started in room %s by host sid=%s", room_code, sid)

    def on_disconnect(self):
        sid = request.sid
        # Find all rooms containing this sid and remove player
        rooms_to_leave = [(room_code, room) for room_code, room in list(_rooms.items()) if sid in room["players"]]
        for room_code, room in rooms_to_leave:
            player = room["players"].get(sid, {})
            self._remove_player(sid, room_code, player.get("profile_id"))
        if rooms_to_leave:
            logger.info("Disconnected sid=%s, removed from %d rooms", sid, len(rooms_to_leave))
