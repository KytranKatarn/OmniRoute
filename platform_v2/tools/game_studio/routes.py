"""
A.R.C.H.I.E. GAME STUDIO Routes
================================
Build games with AI-powered tools - 2D/3D support, mission editor, asset manager.

Author: A.R.C.H.I.E. Platform
Date: 2026-01-19
"""

import os
from database import _get_db_password
import json
import logging
from datetime import datetime, timezone
from flask import render_template, jsonify, request
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
from . import game_studio_bp


from tools.department_hq.services.department_dispatcher import dispatch_json

logger = logging.getLogger(__name__)


# Database connection helper
def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


# ============================================================================
# MAIN PAGE
# ============================================================================


@game_studio_bp.route("/")
@login_required
def index():
    """Render the Game Studio page"""
    return render_template("tools/game_studio.html")


# ============================================================================
# HEALTH CHECK
# ============================================================================


@game_studio_bp.route("/api/status")
def status():
    """Health check endpoint"""
    return jsonify(
        {
            "module": "game_studio",
            "status": "healthy",
            "healthy": True,
            "message": "Game Studio operational",
        }
    )


# ============================================================================
# STATS API
# ============================================================================


@game_studio_bp.route("/api/stats")
@login_required
def get_stats():
    """Get Game Studio statistics"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get game counts
        cur.execute(
            """
            SELECT
                COUNT(*) as total_games,
                COUNT(*) FILTER (WHERE status = 'development') as in_development,
                COUNT(*) FILTER (WHERE status = 'published') as published
            FROM game_projects
            WHERE user_id = %s OR %s = TRUE
        """,
            (
                current_user.id,
                current_user.is_admin if hasattr(current_user, "is_admin") else False,
            ),
        )
        game_stats = cur.fetchone() or {
            "total_games": 0,
            "in_development": 0,
            "published": 0,
        }

        # Get asset count
        cur.execute(
            """
            SELECT COUNT(*) as total_assets
            FROM game_assets
            WHERE user_id = %s OR %s = TRUE
        """,
            (
                current_user.id,
                current_user.is_admin if hasattr(current_user, "is_admin") else False,
            ),
        )
        asset_stats = cur.fetchone() or {"total_assets": 0}

        return jsonify(
            {
                "success": True,
                "total_games": game_stats["total_games"],
                "in_development": game_stats["in_development"],
                "published": game_stats["published"],
                "total_assets": asset_stats["total_assets"],
            }
        )

    except Exception as e:
        logger.warning(f"Stats query failed (tables may not exist yet): {e}")
        return jsonify(
            {
                "success": True,
                "total_games": 0,
                "in_development": 0,
                "published": 0,
                "total_assets": 0,
            }
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# GAMES CRUD API
# ============================================================================


@game_studio_bp.route("/api/games")
@login_required
def get_games():
    """Get all games for current user"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, title, engine_type as engine, status, progress,
                   thumbnail_url as thumbnail, created_at, updated_at
            FROM game_projects
            WHERE user_id = %s OR %s = TRUE
            ORDER BY updated_at DESC
        """,
            (
                current_user.id,
                current_user.is_admin if hasattr(current_user, "is_admin") else False,
            ),
        )

        games = cur.fetchall()

        return jsonify({"success": True, "games": games})

    except Exception as e:
        logger.warning(f"Games query failed: {e}")
        return jsonify({"success": True, "games": []})
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@game_studio_bp.route("/api/games", methods=["POST"])
@login_required
def create_game():
    """Create a new game project"""
    try:
        data = request.get_json()
        title = data.get("title", "Untitled Game")
        engine = data.get("engine", "2d")
        template = data.get("template", "blank")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO game_projects (user_id, title, engine_type, template, status, progress, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'development', 0, NOW(), NOW())
            RETURNING id, title, engine_type as engine, status, progress, created_at
        """,
            (current_user.id, title, engine, template),
        )

        game = cur.fetchone()
        conn.commit()

        game_id = game["id"] if game else None

        # If template selected, create default scene with config
        if template == "top_down_shooter" and game_id:
            default_config = {
                "title": "Top-Down Shooter",
                "type": "top_down_shooter",
                "map": {"width": 1200, "height": 800, "backgroundColor": "#111"},
                "player": {
                    "x": 600,
                    "y": 400,
                    "speed": 200,
                    "health": 100,
                    "size": 20,
                    "color": "#4af",
                    "fireRate": 0.2,
                },
                "enemies": [
                    {"x": 200, "y": 200, "speed": 80, "health": 30, "size": 16, "color": "#f44", "ai": "chase"},
                    {"x": 1000, "y": 200, "speed": 80, "health": 30, "size": 16, "color": "#f44", "ai": "chase"},
                    {"x": 200, "y": 600, "speed": 60, "health": 40, "size": 18, "color": "#f84", "ai": "patrol"},
                    {"x": 1000, "y": 600, "speed": 60, "health": 40, "size": 18, "color": "#f84", "ai": "patrol"},
                    {"x": 600, "y": 100, "speed": 40, "health": 80, "size": 24, "color": "#f00", "ai": "circle"},
                ],
                "bullets": {"speed": 400, "size": 4, "color": "#ff0", "damage": 10},
                "walls": [
                    {"x": 0, "y": 0, "width": 1200, "height": 10, "color": "#555"},
                    {"x": 0, "y": 790, "width": 1200, "height": 10, "color": "#555"},
                    {"x": 0, "y": 0, "width": 10, "height": 800, "color": "#555"},
                    {"x": 1190, "y": 0, "width": 10, "height": 800, "color": "#555"},
                ],
                "ui": {"showScore": True, "showHealth": True, "showMinimap": False},
            }
            cur.execute(
                "INSERT INTO game_scenes (game_id, name, scene_order, scene_data, created_at) VALUES (%s, %s, 1, %s, NOW())",
                (game_id, "Main", json.dumps(default_config)),
            )
            conn.commit()

        elif template == "space_explorer" and game_id:
            default_config = {
                "title": "Space Explorer",
                "type": "space_explorer",
                "mode": "galaxy",
                "map": {"width": 1200, "height": 800, "backgroundColor": "#05050f"},
                "player": {
                    "x": 600,
                    "y": 400,
                    "speed": 250,
                    "health": 100,
                    "size": 14,
                    "color": "#4af",
                    "fuel": 100,
                    "maxFuel": 100,
                    "credits": 500,
                    "cargo": [],
                    "cargoMax": 20,
                },
                "stars": [
                    {
                        "id": "sol",
                        "name": "Sol",
                        "x": 500,
                        "y": 400,
                        "type": "yellow",
                        "color": "#ff0",
                        "planets": [
                            {
                                "name": "Mercury",
                                "orbitRadius": 40,
                                "size": 6,
                                "color": "#a86",
                                "type": "rocky",
                                "resources": {"minerals": 5},
                                "hazard": 0.3,
                            },
                            {
                                "name": "Venus",
                                "orbitRadius": 65,
                                "size": 9,
                                "color": "#da8",
                                "type": "volcanic",
                                "resources": {"minerals": 8},
                                "hazard": 0.6,
                            },
                            {
                                "name": "Earth",
                                "orbitRadius": 90,
                                "size": 10,
                                "color": "#48f",
                                "type": "terran",
                                "resources": {"minerals": 3, "bio": 8},
                                "hazard": 0.1,
                            },
                            {
                                "name": "Mars",
                                "orbitRadius": 120,
                                "size": 8,
                                "color": "#c64",
                                "type": "rocky",
                                "resources": {"minerals": 7, "bio": 1},
                                "hazard": 0.2,
                            },
                        ],
                    },
                    {
                        "id": "alpha",
                        "name": "Alpha Centauri",
                        "x": 300,
                        "y": 200,
                        "type": "yellow",
                        "color": "#ff4",
                        "planets": [
                            {
                                "name": "Proxima b",
                                "orbitRadius": 60,
                                "size": 11,
                                "color": "#4a8",
                                "type": "terran",
                                "resources": {"minerals": 4, "bio": 10},
                                "hazard": 0.15,
                            },
                        ],
                    },
                    {
                        "id": "vega",
                        "name": "Vega",
                        "x": 700,
                        "y": 150,
                        "type": "blue",
                        "color": "#8af",
                        "planets": [
                            {
                                "name": "Vega I",
                                "orbitRadius": 80,
                                "size": 12,
                                "color": "#aaf",
                                "type": "ice",
                                "resources": {"minerals": 10},
                                "hazard": 0.4,
                            },
                        ],
                    },
                    {
                        "id": "sirius",
                        "name": "Sirius",
                        "x": 200,
                        "y": 600,
                        "type": "blue",
                        "color": "#acf",
                        "planets": [
                            {
                                "name": "Sirius Prime",
                                "orbitRadius": 70,
                                "size": 14,
                                "color": "#68a",
                                "type": "gas_giant",
                                "resources": {},
                                "hazard": 0.8,
                            },
                        ],
                    },
                    {
                        "id": "ross",
                        "name": "Ross 128",
                        "x": 650,
                        "y": 550,
                        "type": "red",
                        "color": "#f84",
                        "planets": [
                            {
                                "name": "Ross b",
                                "orbitRadius": 50,
                                "size": 9,
                                "color": "#684",
                                "type": "terran",
                                "resources": {"minerals": 6, "bio": 5},
                                "hazard": 0.25,
                            },
                        ],
                    },
                    {
                        "id": "tau",
                        "name": "Tau Ceti",
                        "x": 400,
                        "y": 650,
                        "type": "yellow",
                        "color": "#fe8",
                        "planets": [
                            {
                                "name": "Tau e",
                                "orbitRadius": 60,
                                "size": 10,
                                "color": "#4a6",
                                "type": "terran",
                                "resources": {"minerals": 5, "bio": 7},
                                "hazard": 0.2,
                            },
                            {
                                "name": "Tau f",
                                "orbitRadius": 100,
                                "size": 8,
                                "color": "#886",
                                "type": "rocky",
                                "resources": {"minerals": 9},
                                "hazard": 0.35,
                            },
                        ],
                    },
                    {
                        "id": "wolf",
                        "name": "Wolf 359",
                        "x": 150,
                        "y": 350,
                        "type": "red",
                        "color": "#f66",
                        "planets": [
                            {
                                "name": "Wolf I",
                                "orbitRadius": 40,
                                "size": 7,
                                "color": "#864",
                                "type": "rocky",
                                "resources": {"minerals": 4},
                                "hazard": 0.5,
                            },
                        ],
                    },
                    {
                        "id": "luyten",
                        "name": "Luyten Star",
                        "x": 800,
                        "y": 300,
                        "type": "red",
                        "color": "#f86",
                        "planets": [
                            {
                                "name": "Luyten b",
                                "orbitRadius": 55,
                                "size": 11,
                                "color": "#486",
                                "type": "ocean",
                                "resources": {"bio": 12},
                                "hazard": 0.15,
                            },
                        ],
                    },
                    {
                        "id": "barnard",
                        "name": "Barnard Star",
                        "x": 350,
                        "y": 150,
                        "type": "red",
                        "color": "#f64",
                        "planets": [
                            {
                                "name": "Barnard b",
                                "orbitRadius": 70,
                                "size": 13,
                                "color": "#89a",
                                "type": "ice",
                                "resources": {"minerals": 8},
                                "hazard": 0.45,
                            },
                        ],
                    },
                    {
                        "id": "kapteyn",
                        "name": "Kapteyn Star",
                        "x": 550,
                        "y": 700,
                        "type": "red",
                        "color": "#e86",
                        "planets": [
                            {
                                "name": "Kapteyn b",
                                "orbitRadius": 45,
                                "size": 10,
                                "color": "#6a4",
                                "type": "terran",
                                "resources": {"minerals": 3, "bio": 6},
                                "hazard": 0.2,
                            },
                        ],
                    },
                    {
                        "id": "procyon",
                        "name": "Procyon",
                        "x": 750,
                        "y": 500,
                        "type": "yellow",
                        "color": "#ffa",
                        "planets": [
                            {
                                "name": "Procyon I",
                                "orbitRadius": 90,
                                "size": 15,
                                "color": "#ca8",
                                "type": "gas_giant",
                                "resources": {},
                                "hazard": 0.7,
                            },
                            {
                                "name": "Procyon II",
                                "orbitRadius": 50,
                                "size": 8,
                                "color": "#8a6",
                                "type": "rocky",
                                "resources": {"minerals": 6, "bio": 3},
                                "hazard": 0.3,
                            },
                        ],
                    },
                    {
                        "id": "epsilon",
                        "name": "Epsilon Eridani",
                        "x": 100,
                        "y": 500,
                        "type": "yellow",
                        "color": "#fc8",
                        "planets": [
                            {
                                "name": "Aegir",
                                "orbitRadius": 80,
                                "size": 14,
                                "color": "#68a",
                                "type": "gas_giant",
                                "resources": {},
                                "hazard": 0.6,
                            },
                            {
                                "name": "Ran b",
                                "orbitRadius": 45,
                                "size": 9,
                                "color": "#4a8",
                                "type": "terran",
                                "resources": {"minerals": 5, "bio": 8},
                                "hazard": 0.2,
                            },
                        ],
                    },
                ],
                "stations": [{"starId": "sol", "name": "Starbase Alpha", "services": ["refuel", "trade", "upgrade"]}],
                "fuelPerJump": 5,
                "encounters": {"pirateChance": 0.15},
                "ui": {"showMap": True, "showFuel": True},
            }
            cur.execute(
                "INSERT INTO game_scenes (game_id, name, scene_order, scene_data, created_at) VALUES (%s, %s, 1, %s, NOW())",
                (game_id, "Galaxy", json.dumps(default_config)),
            )
            conn.commit()

        elif template == "base_builder" and game_id:
            default_config = {
                "title": "Base Builder",
                "type": "base_builder",
                "map": {"width": 40, "height": 30, "cellSize": 32},
                "terrain": [],
                "buildings": [{"type": "shelter", "gridX": 20, "gridY": 15, "hp": 100}],
                "colonists": [
                    {"id": 1, "name": "Alex", "gridX": 21, "gridY": 15, "task": "idle", "health": 100},
                    {"id": 2, "name": "Sam", "gridX": 19, "gridY": 15, "task": "idle", "health": 100},
                    {"id": 3, "name": "Jordan", "gridX": 20, "gridY": 16, "task": "idle", "health": 100},
                ],
                "resources": {"wood": 50, "stone": 30, "metal": 10, "food": 20},
                "resourceNodes": [],
                "threats": {"raidInterval": 8, "raidSize": 3, "raidScaling": 1.2},
                "cycle": 0,
                "cycleLength": 60,
                "ui": {"showResources": True, "showMinimap": True},
            }
            cur.execute(
                "INSERT INTO game_scenes (game_id, name, scene_order, scene_data, created_at) VALUES (%s, %s, 1, %s, NOW())",
                (game_id, "Base Camp", json.dumps(default_config)),
            )
            conn.commit()

        return jsonify(
            {
                "success": True,
                "game": game,
                "message": f'Game "{title}" created successfully',
            }
        )

    except Exception as e:
        logger.error(f"Failed to create game: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@game_studio_bp.route("/api/games/<int:game_id>")
@login_required
def get_game(game_id):
    """Get a specific game project"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM game_projects
            WHERE id = %s AND (user_id = %s OR %s = TRUE)
        """,
            (
                game_id,
                current_user.id,
                current_user.is_admin if hasattr(current_user, "is_admin") else False,
            ),
        )

        game = cur.fetchone()

        if not game:
            return jsonify({"success": False, "error": "Game not found"}), 404

        return jsonify({"success": True, "game": game})

    except Exception as e:
        logger.error(f"Failed to get game: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@game_studio_bp.route("/api/games/<int:game_id>", methods=["PUT"])
@login_required
def update_game(game_id):
    """Update a game project"""
    try:
        data = request.get_json()
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build update query dynamically
        updates = []
        values = []
        for field in ["title", "status", "progress", "settings"]:
            if field in data:
                updates.append(f"{field} = %s")
                values.append(data[field])

        if not updates:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        updates.append("updated_at = NOW()")
        values.extend([game_id, current_user.id])

        cur.execute(
            f"""
            UPDATE game_projects
            SET {', '.join(updates)}
            WHERE id = %s AND user_id = %s
            RETURNING *
        """,
            values,
        )

        game = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "game": game})

    except Exception as e:
        logger.error(f"Failed to update game: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@game_studio_bp.route("/api/games/<int:game_id>", methods=["DELETE"])
@login_required
def delete_game(game_id):
    """Delete a game project"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM game_projects
            WHERE id = %s AND user_id = %s
        """,
            (game_id, current_user.id),
        )

        conn.commit()

        return jsonify({"success": True, "message": "Game deleted successfully"})

    except Exception as e:
        logger.error(f"Failed to delete game: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# ASSETS API
# ============================================================================


@game_studio_bp.route("/api/assets")
@login_required
def get_assets():
    """Get all assets for current user"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, name, asset_type as type, file_path, file_size,
                   thumbnail_url, created_at
            FROM game_assets
            WHERE user_id = %s OR %s = TRUE
            ORDER BY created_at DESC
        """,
            (
                current_user.id,
                current_user.is_admin if hasattr(current_user, "is_admin") else False,
            ),
        )

        assets = cur.fetchall()

        return jsonify({"success": True, "assets": assets})

    except Exception as e:
        logger.warning(f"Assets query failed: {e}")
        return jsonify({"success": True, "assets": []})
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@game_studio_bp.route("/api/assets/upload", methods=["POST"])
@login_required
def upload_assets():
    """Upload asset files"""
    try:
        if "files" not in request.files:
            return jsonify({"success": False, "error": "No files provided"}), 400

        files = request.files.getlist("files")
        uploaded = []

        # Create uploads directory if it doesn't exist
        upload_dir = "/mnt/archie_brain/uploads/game_assets"
        os.makedirs(upload_dir, exist_ok=True)

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        for file in files:
            if file.filename:
                # Determine asset type from extension
                ext = file.filename.rsplit(".", 1)[-1].lower()
                asset_type = get_asset_type(ext)

                # Save file
                filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
                filepath = os.path.join(upload_dir, filename)
                file.save(filepath)
                file_size = os.path.getsize(filepath)

                # Insert into database
                cur.execute(
                    """
                    INSERT INTO game_assets (user_id, name, asset_type, file_path, file_size, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    RETURNING id, name, asset_type as type
                """,
                    (current_user.id, file.filename, asset_type, filepath, file_size),
                )

                asset = cur.fetchone()
                uploaded.append(asset)

        conn.commit()

        return jsonify(
            {
                "success": True,
                "uploaded": uploaded,
                "message": f"{len(uploaded)} assets uploaded successfully",
            }
        )

    except Exception as e:
        logger.error(f"Failed to upload assets: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


def get_asset_type(extension):
    """Determine asset type from file extension"""
    types = {
        "png": "sprite",
        "jpg": "sprite",
        "jpeg": "sprite",
        "gif": "sprite",
        "svg": "sprite",
        "mp3": "sound",
        "wav": "sound",
        "ogg": "sound",
        "mid": "music",
        "midi": "music",
        "gltf": "model",
        "glb": "model",
        "fbx": "model",
        "obj": "model",
        "js": "script",
        "ts": "script",
        "py": "script",
    }
    return types.get(extension, "other")


# ============================================================================
# SCENES API
# ============================================================================


@game_studio_bp.route("/api/games/<int:game_id>/scenes")
@login_required
def get_scenes(game_id):
    """Get scenes for a game"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, name, scene_order, scene_data, created_at
            FROM game_scenes
            WHERE game_id = %s
            ORDER BY scene_order
        """,
            (game_id,),
        )

        scenes = cur.fetchall()

        return jsonify({"success": True, "scenes": scenes})

    except Exception as e:
        logger.warning(f"Scenes query failed: {e}")
        return jsonify({"success": True, "scenes": []})
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@game_studio_bp.route("/api/games/<int:game_id>/scenes", methods=["POST"])
@login_required
def create_scene(game_id):
    """Create a new scene"""
    try:
        data = request.get_json()
        name = data.get("name", "New Scene")
        scene_data = data.get("scene_data", {})
        if not isinstance(scene_data, str):
            scene_data = json.dumps(scene_data)

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get next scene order
        cur.execute(
            "SELECT COALESCE(MAX(scene_order), 0) + 1 as next_order FROM game_scenes WHERE game_id = %s",
            (game_id,),
        )
        next_order = cur.fetchone()["next_order"]

        cur.execute(
            """
            INSERT INTO game_scenes (game_id, name, scene_order, scene_data, created_at)
            VALUES (%s, %s, %s, %s, NOW())
            RETURNING id, name, scene_order
        """,
            (game_id, name, next_order, scene_data),
        )

        scene = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "scene": scene})

    except Exception as e:
        logger.error(f"Failed to create scene: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# AI ASSISTANT API
# ============================================================================


@game_studio_bp.route("/api/ai/chat", methods=["POST"])
@login_required
def ai_chat():
    """Chat with AI assistant for game development help"""
    conn = None
    try:
        data = request.get_json()
        message = data.get("message", "")
        game_id = data.get("game_id")

        if not message:
            return jsonify({"success": False, "error": "No message provided"}), 400

        system_prompt = (
            "You are a game development AI assistant. The user is building a game.\n"
            "When asked to modify the game, respond with a JSON object containing a 'config_patch' key.\n"
            "The config_patch should contain only the fields to change/add.\n"
            "For adding enemies, include the full enemy object in an 'enemies' array.\n"
        )
        context_config = data.get("context", {}).get("current_config", "{}")
        if context_config:
            system_prompt += "\nCurrent game config:\n" + str(context_config)[:3000]

        # Role detection — classify message intent and trigger build pipeline if needed
        DESIGN_KW = ["theme", "color", "look", "feel", "style", "aesthetic", "sprite", "visual", "art"]
        LEVEL_KW = ["level", "map", "place", "spawn", "position", "layout", "area", "zone", "terrain"]
        MECHANICS_KW = [
            "behavior",
            "speed",
            "health",
            "damage",
            "ability",
            "power",
            "rule",
            "logic",
            "code",
            "function",
            "movement",
        ]
        BUILD_KW = ["build me", "create a game", "make a game", "new game about", "generate a", "scaffold"]

        msg_lower = message.lower()

        if any(k in msg_lower for k in BUILD_KW):
            from game_builder_service import start_build

            result = start_build(current_user.id, message)
            return jsonify({"success": True, "response": "Building your game...", "build_session": result})

        if any(k in msg_lower for k in DESIGN_KW):
            system_prompt += "\nFocus on visual design, themes, and aesthetics."
        elif any(k in msg_lower for k in LEVEL_KW):
            system_prompt += "\nFocus on level layout, entity placement, and map design. Return config_patch JSON."
        elif any(k in msg_lower for k in MECHANICS_KW):
            system_prompt += '\nFocus on game mechanics. When appropriate, return behaviors JSON: {"behaviors": [{"name": "...", "code": "function(entity, engine, dt) {...}"}]}'

        result = dispatch_json(
            capability="creative",
            prompt=message,
            module_id="game_studio",
            system_prompt=system_prompt,
        )
        response_text = result.get("response", "") if isinstance(result, dict) else str(result)

        # Persist chat history
        if game_id:
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    "SELECT chat_history FROM game_projects WHERE id = %s AND user_id = %s",
                    (game_id, current_user.id),
                )
                row = cur.fetchone()
                history = row[0] if row and row[0] else []
                if isinstance(history, str):
                    history = json.loads(history)
                history.append(
                    {"role": "user", "message": message, "timestamp": datetime.now(timezone.utc).isoformat()}
                )
                history.append(
                    {"role": "ai", "message": response_text[:500], "timestamp": datetime.now(timezone.utc).isoformat()}
                )
                history = history[-50:]  # keep last 50
                cur.execute(
                    "UPDATE game_projects SET chat_history = %s WHERE id = %s",
                    (json.dumps(history), game_id),
                )
                conn.commit()
                cur.close()
            except Exception:
                pass

        return jsonify({"success": True, "response": response_text})

    except Exception as e:
        logger.error(f"AI chat failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@game_studio_bp.route("/api/chat/history/<int:game_id>", methods=["GET"])
@login_required
def get_chat_history(game_id):
    """Get chat history for a game"""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT chat_history FROM game_projects WHERE id = %s AND user_id = %s",
            (game_id, current_user.id),
        )
        row = cur.fetchone()
        history = row[0] if row and row[0] else []
        return jsonify({"success": True, "history": history})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ============================================================================
# EXPORT API
# ============================================================================


@game_studio_bp.route("/api/games/<int:game_id>/export", methods=["POST"])
@login_required
def export_game(game_id):
    """Export game to specified format"""
    try:
        data = request.get_json()
        export_format = data.get("format", "web")

        # Placeholder for export logic
        return jsonify(
            {
                "success": True,
                "message": f"Game export to {export_format} format initiated",
                "status": "pending",
                "download_url": None,  # Will be populated when export is complete
            }
        )

    except Exception as e:
        logger.error(f"Export failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# BUILD PIPELINE API
# ============================================================================


@game_studio_bp.route("/api/ai/build", methods=["POST"])
@login_required
def start_build():
    """Start an AI build pipeline session"""
    try:
        from game_builder_service import start_build as _start_build

        data = request.get_json()
        description = data.get("description", "")
        game_type = data.get("game_type", "")

        if not description:
            return jsonify({"success": False, "error": "No description provided"}), 400

        result = _start_build(current_user.id, description, game_type=game_type)
        return jsonify({"success": True, "session": result})

    except Exception as e:
        logger.error(f"Build start failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@game_studio_bp.route("/api/ai/build/<int:session_id>", methods=["GET"])
@login_required
def get_build_status(session_id):
    """Get status of a build pipeline session"""
    try:
        from game_builder_service import get_build_status as _get_build_status

        result = _get_build_status(session_id, current_user.id)
        if result is None:
            return jsonify({"success": False, "error": "Session not found"}), 404

        # Serialize datetimes
        for key in list(result.keys()):
            val = result[key]
            if hasattr(val, "isoformat"):
                result[key] = val.isoformat()

        return jsonify({"success": True, "session": result})

    except Exception as e:
        logger.error(f"Build status failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@game_studio_bp.route("/api/ai/build/<int:session_id>/approve", methods=["POST"])
@login_required
def approve_build_checkpoint(session_id):
    """Approve a build checkpoint and continue pipeline"""
    try:
        from game_builder_service import approve_checkpoint as _approve_checkpoint

        result = _approve_checkpoint(session_id, current_user.id)
        return jsonify({"success": True, "session": result})

    except Exception as e:
        logger.error(f"Build approve failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@game_studio_bp.route("/api/ai/build/<int:session_id>/apply", methods=["POST"])
@login_required
def apply_build_result(session_id):
    """Apply completed build result to create a game project"""
    try:
        from game_builder_service import apply_build_result as _apply_build_result

        result = _apply_build_result(session_id, current_user.id)
        return jsonify({"success": True, "game": result})

    except Exception as e:
        logger.error(f"Build apply failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# MULTIPLAYER — Profile, Session, World
# ============================================================================


@game_studio_bp.route("/api/profile", methods=["POST"])
@login_required
def create_player_profile():
    from world_state_service import create_profile

    data = request.get_json() or {}
    display_name = data.get("display_name", "").strip()
    result = create_profile(user_id=current_user.id, display_name=display_name or None)
    if "error" in result:
        return jsonify(result), 400
    return jsonify({"profile": result})


@game_studio_bp.route("/api/profile", methods=["GET"])
@login_required
def get_player_profile():
    from world_state_service import get_profile_by_user

    profile = get_profile_by_user(current_user.id)
    if not profile:
        return jsonify({"profile": None})
    for k, v in list(profile.items()):
        if hasattr(v, "isoformat"):
            profile[k] = v.isoformat()
    return jsonify({"profile": profile})


@game_studio_bp.route("/api/profile", methods=["PUT"])
@login_required
def update_player_profile():
    from world_state_service import get_profile_by_user
    from database import get_db_cursor

    data = request.get_json() or {}
    profile = get_profile_by_user(current_user.id)
    if not profile:
        return jsonify({"error": "No profile found"}), 404
    sets, params = [], []
    if "display_name" in data:
        sets.append("display_name = %s")
        params.append(data["display_name"][:50])
    if "avatar_config" in data:
        from psycopg2.extras import Json

        sets.append("avatar_config = %s")
        params.append(Json(data["avatar_config"]))
    if not sets:
        return jsonify({"error": "No fields to update"}), 400
    params.append(profile["id"])
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(f"UPDATE game_player_profiles SET {', '.join(sets)} WHERE id = %s", params)
    return jsonify({"success": True})


@game_studio_bp.route("/api/sessions", methods=["POST"])
@login_required
def create_game_session():
    from game_server import create_session
    from world_state_service import get_profile_by_user

    data = request.get_json() or {}
    profile = get_profile_by_user(current_user.id)
    if not profile:
        return jsonify({"error": "Create a profile first"}), 400
    game_id = data.get("game_id")
    game_type = data.get("game_type", "top_down_shooter")
    max_players = min(int(data.get("max_players", 4)), 8)
    result = create_session(game_id, profile["id"], game_type, {}, max_players)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@game_studio_bp.route("/api/sessions", methods=["GET"])
@login_required
def list_game_sessions():
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT s.room_code, s.game_type, s.status, s.max_players, s.current_players, s.created_at,
                   p.display_name as host_name
            FROM game_sessions s
            LEFT JOIN game_player_profiles p ON s.host_profile_id = p.id
            WHERE s.status IN ('lobby', 'playing')
            ORDER BY s.created_at DESC LIMIT 20
        """
        )
        sessions = []
        for r in cur.fetchall():
            d = dict(r)
            for k, v in list(d.items()):
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
            sessions.append(d)
    return jsonify({"sessions": sessions})


@game_studio_bp.route("/api/sessions/<room_code>", methods=["GET"])
@login_required
def get_game_session(room_code):
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM game_sessions WHERE room_code = %s", (room_code,))
        session = cur.fetchone()
        if not session:
            return jsonify({"error": "Session not found"}), 404
        d = dict(session)
        for k, v in list(d.items()):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        from game_server import _rooms

        players = []
        if room_code in _rooms:
            for sid, p in _rooms[room_code].get("players", {}).items():
                players.append(
                    {
                        "display_name": p.get("name", "?"),
                        "profile_id": p.get("profile_id"),
                        "is_host": p.get("profile_id") == session["host_profile_id"],
                    }
                )
        d["players"] = players
    return jsonify(d)


@game_studio_bp.route("/api/sessions/<room_code>/end", methods=["POST"])
@login_required
def end_game_session(room_code):
    from game_server import end_session
    from world_state_service import get_profile_by_user

    profile = get_profile_by_user(current_user.id)
    if not profile:
        return jsonify({"error": "No profile"}), 400
    result = end_session(room_code, profile["id"])
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@game_studio_bp.route("/api/world", methods=["GET"])
@login_required
def get_world_state():
    from world_state_service import get_world_resources, get_pending_events

    resources = get_world_resources()
    events = get_pending_events("all", limit=20)
    return jsonify({"resources": resources, "events": events})


# ===========================================================================
# WORLD — Effects, Map, Trade (Phase 5)
# ===========================================================================


@game_studio_bp.route("/api/world/effects", methods=["GET"])
@login_required
def get_world_effects():
    """Return active bonuses + pending world changes for a given game_type."""
    from world_engine import get_active_bonuses, get_pending_world_changes

    game_type = request.args.get("game_type", "top_down_shooter")
    bonuses = get_active_bonuses(game_type)
    changes = get_pending_world_changes(game_type)
    # Serialize datetimes
    for item in bonuses + changes:
        for k, v in list(item.items()):
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
    return jsonify({"bonuses": bonuses, "changes": changes})


@game_studio_bp.route("/api/world/map", methods=["GET"])
@login_required
def get_world_map():
    """Return aggregated cross-game activity for the world map canvas."""
    from database import get_db_cursor
    from datetime import datetime, timedelta

    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    result = {
        "shooter_battles": [],
        "explorer_routes": [],
        "builder_colonies": [],
        "recent_events": [],
    }
    try:
        with get_db_cursor() as (conn, cur):
            # Recent events from last hour (all game types)
            cur.execute(
                """
                SELECT id, event_type, source_game_type, data, created_at
                  FROM game_world_events
                 WHERE created_at >= %s
                 ORDER BY created_at DESC LIMIT 50
                """,
                (one_hour_ago,),
            )
            for r in cur.fetchall():
                d = dict(r)
                if d.get("created_at"):
                    d["created_at"] = d["created_at"].isoformat()
                result["recent_events"].append(d)
                src = d.get("source_game_type", "")
                data = d.get("data") or {}
                if src == "top_down_shooter":
                    result["shooter_battles"].append(
                        {
                            "x": data.get("x", 0),
                            "y": data.get("y", 0),
                            "age_s": (
                                (datetime.now(timezone.utc) - r["created_at"].replace(tzinfo=None)).total_seconds()
                                if r["created_at"]
                                else 999
                            ),
                        }
                    )
                elif src == "space_explorer":
                    result["explorer_routes"].append(
                        {
                            "from_star": data.get("from_star"),
                            "to_star": data.get("to_star"),
                        }
                    )
                elif src == "base_builder":
                    result["builder_colonies"].append(
                        {
                            "star": data.get("star"),
                            "colony": data.get("colony"),
                        }
                    )
    except Exception as e:
        logger.error(f"[world map] {e}")
    return jsonify(result)


@game_studio_bp.route("/api/world/trade", methods=["POST"])
@login_required
def execute_world_trade():
    """Execute a resource trade at current market rates."""
    from market_service import trade
    from world_state_service import get_profile_by_user

    data = request.get_json() or {}
    from_resource = data.get("from")
    to_resource = data.get("to")
    amount = data.get("amount")

    if not from_resource or not to_resource or amount is None:
        return jsonify({"success": False, "error": "Missing from/to/amount"}), 400
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "amount must be numeric"}), 400

    profile = get_profile_by_user(current_user.id)
    profile_id = profile["id"] if profile else None

    result = trade(from_resource, to_resource, amount, profile_id=profile_id)
    if not result.get("success"):
        return jsonify(result), 400
    return jsonify(result)
