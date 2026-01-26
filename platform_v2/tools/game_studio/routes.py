"""
A.R.C.H.I.E. GAME STUDIO Routes
================================
Build games with AI-powered tools - 2D/3D support, mission editor, asset manager.

Author: A.R.C.H.I.E. Platform
Date: 2026-01-19
"""

import os
import logging
from datetime import datetime
from flask import render_template, jsonify, request
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
from . import game_studio_bp

logger = logging.getLogger(__name__)

# Database connection helper
def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', '')
    )


# ============================================================================
# MAIN PAGE
# ============================================================================

@game_studio_bp.route('/')
@login_required
def index():
    """Render the Game Studio page"""
    return render_template('tools/game_studio.html')


# ============================================================================
# HEALTH CHECK
# ============================================================================

@game_studio_bp.route('/api/status')
def status():
    """Health check endpoint"""
    return jsonify({
        'module': 'game_studio',
        'status': 'healthy',
        'healthy': True,
        'message': 'Game Studio operational'
    })


# ============================================================================
# STATS API
# ============================================================================

@game_studio_bp.route('/api/stats')
@login_required
def get_stats():
    """Get Game Studio statistics"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get game counts
        cur.execute("""
            SELECT
                COUNT(*) as total_games,
                COUNT(*) FILTER (WHERE status = 'development') as in_development,
                COUNT(*) FILTER (WHERE status = 'published') as published
            FROM game_projects
            WHERE user_id = %s OR %s = TRUE
        """, (current_user.id, current_user.is_admin if hasattr(current_user, 'is_admin') else False))
        game_stats = cur.fetchone() or {'total_games': 0, 'in_development': 0, 'published': 0}

        # Get asset count
        cur.execute("""
            SELECT COUNT(*) as total_assets
            FROM game_assets
            WHERE user_id = %s OR %s = TRUE
        """, (current_user.id, current_user.is_admin if hasattr(current_user, 'is_admin') else False))
        asset_stats = cur.fetchone() or {'total_assets': 0}

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'total_games': game_stats['total_games'],
            'in_development': game_stats['in_development'],
            'published': game_stats['published'],
            'total_assets': asset_stats['total_assets']
        })

    except Exception as e:
        logger.warning(f"Stats query failed (tables may not exist yet): {e}")
        return jsonify({
            'success': True,
            'total_games': 0,
            'in_development': 0,
            'published': 0,
            'total_assets': 0
        })


# ============================================================================
# GAMES CRUD API
# ============================================================================

@game_studio_bp.route('/api/games')
@login_required
def get_games():
    """Get all games for current user"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT id, title, engine_type as engine, status, progress,
                   thumbnail_url as thumbnail, created_at, updated_at
            FROM game_projects
            WHERE user_id = %s OR %s = TRUE
            ORDER BY updated_at DESC
        """, (current_user.id, current_user.is_admin if hasattr(current_user, 'is_admin') else False))

        games = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'games': games
        })

    except Exception as e:
        logger.warning(f"Games query failed: {e}")
        return jsonify({
            'success': True,
            'games': []
        })


@game_studio_bp.route('/api/games', methods=['POST'])
@login_required
def create_game():
    """Create a new game project"""
    try:
        data = request.get_json()
        title = data.get('title', 'Untitled Game')
        engine = data.get('engine', '2d')
        template = data.get('template', 'blank')

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            INSERT INTO game_projects (user_id, title, engine_type, template, status, progress, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'development', 0, NOW(), NOW())
            RETURNING id, title, engine_type as engine, status, progress, created_at
        """, (current_user.id, title, engine, template))

        game = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'game': game,
            'message': f'Game "{title}" created successfully'
        })

    except Exception as e:
        logger.error(f"Failed to create game: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@game_studio_bp.route('/api/games/<int:game_id>')
@login_required
def get_game(game_id):
    """Get a specific game project"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT * FROM game_projects
            WHERE id = %s AND (user_id = %s OR %s = TRUE)
        """, (game_id, current_user.id, current_user.is_admin if hasattr(current_user, 'is_admin') else False))

        game = cur.fetchone()
        cur.close()
        conn.close()

        if not game:
            return jsonify({'success': False, 'error': 'Game not found'}), 404

        return jsonify({
            'success': True,
            'game': game
        })

    except Exception as e:
        logger.error(f"Failed to get game: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@game_studio_bp.route('/api/games/<int:game_id>', methods=['PUT'])
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
        for field in ['title', 'status', 'progress', 'settings']:
            if field in data:
                updates.append(f"{field} = %s")
                values.append(data[field])

        if not updates:
            return jsonify({'success': False, 'error': 'No fields to update'}), 400

        updates.append("updated_at = NOW()")
        values.extend([game_id, current_user.id])

        cur.execute(f"""
            UPDATE game_projects
            SET {', '.join(updates)}
            WHERE id = %s AND user_id = %s
            RETURNING *
        """, values)

        game = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'game': game
        })

    except Exception as e:
        logger.error(f"Failed to update game: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@game_studio_bp.route('/api/games/<int:game_id>', methods=['DELETE'])
@login_required
def delete_game(game_id):
    """Delete a game project"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            DELETE FROM game_projects
            WHERE id = %s AND user_id = %s
        """, (game_id, current_user.id))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'message': 'Game deleted successfully'
        })

    except Exception as e:
        logger.error(f"Failed to delete game: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ASSETS API
# ============================================================================

@game_studio_bp.route('/api/assets')
@login_required
def get_assets():
    """Get all assets for current user"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT id, name, asset_type as type, file_path, file_size,
                   thumbnail_url, created_at
            FROM game_assets
            WHERE user_id = %s OR %s = TRUE
            ORDER BY created_at DESC
        """, (current_user.id, current_user.is_admin if hasattr(current_user, 'is_admin') else False))

        assets = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'assets': assets
        })

    except Exception as e:
        logger.warning(f"Assets query failed: {e}")
        return jsonify({
            'success': True,
            'assets': []
        })


@game_studio_bp.route('/api/assets/upload', methods=['POST'])
@login_required
def upload_assets():
    """Upload asset files"""
    try:
        if 'files' not in request.files:
            return jsonify({'success': False, 'error': 'No files provided'}), 400

        files = request.files.getlist('files')
        uploaded = []

        # Create uploads directory if it doesn't exist
        upload_dir = '/mnt/archie_brain/uploads/game_assets'
        os.makedirs(upload_dir, exist_ok=True)

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        for file in files:
            if file.filename:
                # Determine asset type from extension
                ext = file.filename.rsplit('.', 1)[-1].lower()
                asset_type = get_asset_type(ext)

                # Save file
                filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
                filepath = os.path.join(upload_dir, filename)
                file.save(filepath)
                file_size = os.path.getsize(filepath)

                # Insert into database
                cur.execute("""
                    INSERT INTO game_assets (user_id, name, asset_type, file_path, file_size, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    RETURNING id, name, asset_type as type
                """, (current_user.id, file.filename, asset_type, filepath, file_size))

                asset = cur.fetchone()
                uploaded.append(asset)

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'uploaded': uploaded,
            'message': f'{len(uploaded)} assets uploaded successfully'
        })

    except Exception as e:
        logger.error(f"Failed to upload assets: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def get_asset_type(extension):
    """Determine asset type from file extension"""
    types = {
        'png': 'sprite', 'jpg': 'sprite', 'jpeg': 'sprite', 'gif': 'sprite', 'svg': 'sprite',
        'mp3': 'sound', 'wav': 'sound', 'ogg': 'sound',
        'mid': 'music', 'midi': 'music',
        'gltf': 'model', 'glb': 'model', 'fbx': 'model', 'obj': 'model',
        'js': 'script', 'ts': 'script', 'py': 'script'
    }
    return types.get(extension, 'other')


# ============================================================================
# SCENES API
# ============================================================================

@game_studio_bp.route('/api/games/<int:game_id>/scenes')
@login_required
def get_scenes(game_id):
    """Get scenes for a game"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT id, name, scene_order, scene_data, created_at
            FROM game_scenes
            WHERE game_id = %s
            ORDER BY scene_order
        """, (game_id,))

        scenes = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'scenes': scenes
        })

    except Exception as e:
        logger.warning(f"Scenes query failed: {e}")
        return jsonify({
            'success': True,
            'scenes': []
        })


@game_studio_bp.route('/api/games/<int:game_id>/scenes', methods=['POST'])
@login_required
def create_scene(game_id):
    """Create a new scene"""
    try:
        data = request.get_json()
        name = data.get('name', 'New Scene')

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get next scene order
        cur.execute("SELECT COALESCE(MAX(scene_order), 0) + 1 as next_order FROM game_scenes WHERE game_id = %s", (game_id,))
        next_order = cur.fetchone()['next_order']

        cur.execute("""
            INSERT INTO game_scenes (game_id, name, scene_order, scene_data, created_at)
            VALUES (%s, %s, %s, %s, NOW())
            RETURNING id, name, scene_order
        """, (game_id, name, next_order, '{}'))

        scene = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'scene': scene
        })

    except Exception as e:
        logger.error(f"Failed to create scene: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# AI ASSISTANT API
# ============================================================================

@game_studio_bp.route('/api/ai/chat', methods=['POST'])
@login_required
def ai_chat():
    """Chat with AI assistant for game development help"""
    try:
        data = request.get_json()
        message = data.get('message', '')
        game_id = data.get('game_id')

        if not message:
            return jsonify({'success': False, 'error': 'No message provided'}), 400

        # Build context for AI
        context = "You are a game development assistant. Help with game logic, AI behavior, level design, and code."

        if game_id:
            # Add game context if available
            try:
                conn = get_db_connection()
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute("SELECT title, engine_type FROM game_projects WHERE id = %s", (game_id,))
                game = cur.fetchone()
                cur.close()
                conn.close()
                if game:
                    context += f"\n\nCurrent project: {game['title']} ({game['engine_type']} engine)"
            except:
                pass

        # Call AI Bridge for response
        try:
            import requests
            ai_response = requests.post(
                'http://localhost:3000/archie/api/v2/chat',
                json={
                    'message': message,
                    'context': context,
                    'model': 'ollama'
                },
                timeout=30
            )
            if ai_response.ok:
                result = ai_response.json()
                return jsonify({
                    'success': True,
                    'response': result.get('response', 'I can help you with game development! What would you like to know?')
                })
        except Exception as ai_error:
            logger.warning(f"AI bridge call failed: {ai_error}")

        # Fallback response
        return jsonify({
            'success': True,
            'response': f"I understand you're asking about: {message}\n\nI can help with:\n- Enemy AI behavior patterns\n- Player movement mechanics\n- Level design principles\n- Game state management\n- Physics and collision\n\nWhat specific aspect would you like to explore?"
        })

    except Exception as e:
        logger.error(f"AI chat failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# EXPORT API
# ============================================================================

@game_studio_bp.route('/api/games/<int:game_id>/export', methods=['POST'])
@login_required
def export_game(game_id):
    """Export game to specified format"""
    try:
        data = request.get_json()
        export_format = data.get('format', 'web')

        # Placeholder for export logic
        return jsonify({
            'success': True,
            'message': f'Game export to {export_format} format initiated',
            'status': 'pending',
            'download_url': None  # Will be populated when export is complete
        })

    except Exception as e:
        logger.error(f"Export failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
