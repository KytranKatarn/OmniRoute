"""
Obsidian Vault Routes
Flask blueprint for Obsidian vault integration

Provides:
- CRUD operations for notes
- Hybrid search (keyword + semantic)
- Wikilink graph and backlinks
- Real-time sync status
- /docs/ migration tools

Author: A.R.C.H.I.E. Platform
Date: 2026-01-08
"""

from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
from typing import Dict, List, Tuple
import os
import logging

# Setup logger
logger = logging.getLogger("archie_platform")

# Import RBAC
from rbac import require_permission, require_role, Permission, Role, has_permission

# Import vault components
from tools.consciousness.services.obsidian_vault_manager import ObsidianVaultManager
from tools.consciousness.services.knowledge_vault_indexer import (
    KnowledgeVaultIndexer,
    reindex_note,
    reindex_all_notes,
    delete_note_from_index,
    get_indexing_stats,
)
from tools.consciousness.services.obsidian_vault_watcher import get_watcher_status

# ============================================================================
# BLUEPRINT SETUP
# ============================================================================

obsidian_vault_bp = Blueprint(
    "obsidian_vault",
    __name__,
    url_prefix="/tools/obsidian-vault",
    template_folder="templates",
)


# ============================================================================
# UI ROUTES
# ============================================================================


@obsidian_vault_bp.route("/")
@login_required
@require_permission(Permission.OBSIDIAN_READ)
def vault_dashboard():
    """Main vault dashboard"""
    try:
        vault_manager = ObsidianVaultManager()
        indexer = KnowledgeVaultIndexer()

        # Get filter parameters from URL
        category_filter = request.args.get("category", "")
        type_filter = request.args.get("type", "")

        # Get vault statistics
        vault_stats = vault_manager.get_vault_stats()
        indexing_stats = get_indexing_stats()
        watcher_status = get_watcher_status()

        # Get user permissions
        can_write = has_permission(Permission.OBSIDIAN_WRITE, current_user)
        can_delete = has_permission(Permission.OBSIDIAN_DELETE, current_user)
        can_admin = has_permission(Permission.OBSIDIAN_ADMIN, current_user)

        return render_template(
            "obsidian_vault.html",
            vault_stats=vault_stats,
            indexing_stats=indexing_stats,
            watcher_status=watcher_status,
            can_write=can_write,
            can_delete=can_delete,
            can_admin=can_admin,
            initial_category=category_filter,
            initial_type=type_filter,
        )

    except Exception as e:
        logger.error(f"Error loading vault dashboard: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@obsidian_vault_bp.route("/note/<int:note_id>")
@login_required
@require_permission(Permission.OBSIDIAN_READ)
def note_editor(note_id):
    """Note editor/viewer interface"""
    try:
        # Get note from database
        from database import get_db

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, title, content, category, tags, file_path,
                   frontmatter_metadata, created_at, updated_at
            FROM knowledge_base
            WHERE id = %s AND is_documentation = TRUE
        """,
            (note_id,),
        )

        result = cursor.fetchone()
        cursor.close()

        if not result:
            return jsonify({"error": "Note not found"}), 404

        note = {
            "id": result[0],
            "title": result[1],
            "content": result[2],
            "category": result[3],
            "tags": result[4],
            "file_path": result[5],
            "frontmatter": result[6],
            "created_at": result[7],
            "updated_at": result[8],
        }

        # Get backlinks
        indexer = KnowledgeVaultIndexer()
        backlinks = indexer.get_backlinks(note_id)

        # Check write permission
        can_write = has_permission(Permission.OBSIDIAN_WRITE, current_user)
        can_delete = has_permission(Permission.OBSIDIAN_DELETE, current_user)

        return render_template(
            "obsidian_note_editor.html",
            note=note,
            backlinks=backlinks,
            can_write=can_write,
            can_delete=can_delete,
        )

    except Exception as e:
        logger.error(f"Error loading note editor: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# CRUD API ROUTES
# ============================================================================


@obsidian_vault_bp.route("/api/notes", methods=["POST"])
@login_required
@require_permission(Permission.OBSIDIAN_WRITE)
def create_note():
    """Create a new note"""
    try:
        data = request.get_json()

        # Validate required fields
        if not data.get("title") or not data.get("content"):
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Missing required fields: title, content",
                    }
                ),
                400,
            )

        vault_manager = ObsidianVaultManager()

        # Create note
        success, message, file_path = vault_manager.create_note(
            title=data["title"],
            content=data["content"],
            category=data.get("category", "Core"),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
            author=(current_user.username if hasattr(current_user, "username") else "archie"),
        )

        if not success:
            return jsonify({"success": False, "message": message}), 400

        # Trigger indexing
        reindex_note(file_path)

        return (
            jsonify({"success": True, "message": message, "file_path": file_path}),
            201,
        )

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@obsidian_vault_bp.route("/api/notes/<int:note_id>", methods=["GET"])
@login_required
@require_permission(Permission.OBSIDIAN_READ)
def get_note(note_id):
    """Get note by ID"""
    try:
        from database import get_db

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, title, content, category, tags, file_path,
                   frontmatter_metadata, created_at, updated_at, last_synced_at
            FROM knowledge_base
            WHERE id = %s AND is_documentation = TRUE
        """,
            (note_id,),
        )

        result = cursor.fetchone()
        cursor.close()

        if not result:
            return jsonify({"success": False, "message": "Note not found"}), 404

        note = {
            "id": result[0],
            "title": result[1],
            "content": result[2],
            "category": result[3],
            "tags": result[4],
            "file_path": result[5],
            "frontmatter": result[6],
            "created_at": result[7].isoformat() if result[7] else None,
            "updated_at": result[8].isoformat() if result[8] else None,
            "last_synced_at": result[9].isoformat() if result[9] else None,
        }

        return jsonify({"success": True, "note": note}), 200

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@obsidian_vault_bp.route("/api/notes/<int:note_id>", methods=["PUT"])
@login_required
@require_permission(Permission.OBSIDIAN_WRITE)
def update_note(note_id):
    """Update existing note"""
    try:
        data = request.get_json()

        # Get note file path
        from database import get_db

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT file_path FROM knowledge_base WHERE id = %s AND is_documentation = TRUE",
            (note_id,),
        )

        result = cursor.fetchone()
        cursor.close()

        if not result:
            return jsonify({"success": False, "message": "Note not found"}), 404

        file_path = result[0]

        # Update note
        vault_manager = ObsidianVaultManager()
        success, message = vault_manager.update_note(
            file_path=file_path,
            content=data.get("content"),
            frontmatter_updates=data.get("frontmatter_updates"),
        )

        if not success:
            return jsonify({"success": False, "message": message}), 400

        # Trigger re-indexing
        reindex_note(file_path)

        return jsonify({"success": True, "message": message}), 200

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@obsidian_vault_bp.route("/api/notes/<int:note_id>", methods=["DELETE"])
@login_required
@require_permission(Permission.OBSIDIAN_DELETE)
def delete_note(note_id):
    """Delete a note"""
    try:
        # Get note file path
        from database import get_db

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT file_path FROM knowledge_base WHERE id = %s AND is_documentation = TRUE",
            (note_id,),
        )

        result = cursor.fetchone()
        cursor.close()

        if not result:
            return jsonify({"success": False, "message": "Note not found"}), 404

        file_path = result[0]

        # Delete file
        vault_manager = ObsidianVaultManager()
        success, message = vault_manager.delete_note(file_path)

        if not success:
            return jsonify({"success": False, "message": message}), 400

        # Remove from index
        delete_note_from_index(file_path)

        return jsonify({"success": True, "message": message}), 200

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@obsidian_vault_bp.route("/api/notes", methods=["GET"])
@login_required
@require_permission(Permission.OBSIDIAN_READ)
def list_notes():
    """List all notes with pagination - supports all knowledge types"""
    try:
        category = request.args.get("category")
        knowledge_type = request.args.get("type")  # vault_note, conversation_memory, github_file, mistake_learned, all
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))

        from database import get_db

        conn = get_db()
        cursor = conn.cursor()

        # Build query - support all knowledge types
        query = """
            SELECT id, title, category, tags, created_at, updated_at, knowledge_type
            FROM knowledge_base
            WHERE 1=1
        """
        params = []

        # Filter by knowledge type
        if knowledge_type and knowledge_type != "all":
            query += " AND knowledge_type = %s"
            params.append(knowledge_type)
        elif not knowledge_type:
            # Default to documentation only (backwards compatibility)
            query += " AND is_documentation = TRUE"

        if category:
            # Support hierarchical category filtering (e.g., "System" matches "System/Identity", "System/Architecture")
            query += " AND (category = %s OR category LIKE %s)"
            params.append(category)
            params.append(category + "/%")

        query += " ORDER BY updated_at DESC NULLS LAST LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cursor.execute(query, params)

        notes = []
        for row in cursor.fetchall():
            notes.append(
                {
                    "id": row[0],
                    "title": row[1] or "Untitled",
                    "category": row[2] or "uncategorized",
                    "tags": row[3] or [],
                    "created_at": row[4].isoformat() if row[4] else None,
                    "updated_at": row[5].isoformat() if row[5] else None,
                    "knowledge_type": row[6],
                }
            )

        # Get total count
        count_query = "SELECT COUNT(*) FROM knowledge_base WHERE 1=1"
        count_params = []

        if knowledge_type and knowledge_type != "all":
            count_query += " AND knowledge_type = %s"
            count_params.append(knowledge_type)
        elif not knowledge_type:
            count_query += " AND is_documentation = TRUE"

        if category:
            count_query += " AND category = %s"
            count_params.append(category)

        cursor.execute(count_query, count_params)
        total_count = cursor.fetchone()[0]

        cursor.close()

        return (
            jsonify(
                {
                    "success": True,
                    "notes": notes,
                    "total": total_count,
                    "limit": limit,
                    "offset": offset,
                    "knowledge_type": knowledge_type or "documentation",
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Error listing notes: {e}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# SEARCH API ROUTES
# ============================================================================


@obsidian_vault_bp.route("/api/search", methods=["POST"])
@login_required
@require_permission(Permission.OBSIDIAN_READ)
def search_vault():
    """Hybrid search (keyword + semantic)"""
    try:
        data = request.get_json()
        query = data.get("query", "")
        category = data.get("category")
        tags = data.get("tags")
        limit = data.get("limit", 10)

        if not query:
            return jsonify({"success": False, "message": "Query is required"}), 400

        # Use vault manager for keyword search
        vault_manager = ObsidianVaultManager()
        results = vault_manager.search_vault(query=query, category=category, tags=tags, limit=limit)

        return (
            jsonify(
                {
                    "success": True,
                    "results": results,
                    "query": query,
                    "count": len(results),
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@obsidian_vault_bp.route("/api/search/tags", methods=["GET"])
@login_required
@require_permission(Permission.OBSIDIAN_READ)
def list_tags():
    """List all tags with counts"""
    try:
        vault_manager = ObsidianVaultManager()
        stats = vault_manager.get_vault_stats()

        tags = [{"tag": tag, "count": count} for tag, count in stats.get("tags", {}).items()]

        # Sort by count descending
        tags.sort(key=lambda x: x["count"], reverse=True)

        return (
            jsonify({"success": True, "tags": tags, "total_unique_tags": len(tags)}),
            200,
        )

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@obsidian_vault_bp.route("/api/search/categories", methods=["GET"])
@login_required
@require_permission(Permission.OBSIDIAN_READ)
def list_categories():
    """List all categories with note counts"""
    try:
        vault_manager = ObsidianVaultManager()
        stats = vault_manager.get_vault_stats()

        categories = [{"category": cat, "count": count} for cat, count in stats.get("by_category", {}).items()]

        return (
            jsonify(
                {
                    "success": True,
                    "categories": categories,
                    "total_notes": stats.get("total_notes", 0),
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@obsidian_vault_bp.route("/api/knowledge-stats", methods=["GET"])
@login_required
@require_permission(Permission.OBSIDIAN_READ)
def knowledge_stats():
    """Get counts for all knowledge types"""
    try:
        from database import get_db

        conn = get_db()
        cursor = conn.cursor()

        # Get counts by knowledge type
        cursor.execute(
            """
            SELECT knowledge_type, COUNT(*) as count
            FROM knowledge_base
            GROUP BY knowledge_type
            ORDER BY count DESC
        """
        )

        type_stats = {}
        total = 0
        for row in cursor.fetchall():
            type_stats[row[0]] = row[1]
            total += row[1]

        # Get documentation count separately
        cursor.execute("SELECT COUNT(*) FROM knowledge_base WHERE is_documentation = TRUE")
        doc_count = cursor.fetchone()[0]

        cursor.close()

        return (
            jsonify(
                {
                    "success": True,
                    "stats": {
                        "by_type": type_stats,
                        "documentation_count": doc_count,
                        "total": total,
                    },
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Error getting knowledge stats: {e}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# LINK/GRAPH API ROUTES
# ============================================================================


@obsidian_vault_bp.route("/api/backlinks/<int:note_id>", methods=["GET"])
@login_required
@require_permission(Permission.OBSIDIAN_READ)
def get_backlinks(note_id):
    """Get all notes that link to this note"""
    try:
        indexer = KnowledgeVaultIndexer()
        backlinks = indexer.get_backlinks(note_id)

        return (
            jsonify(
                {
                    "success": True,
                    "note_id": note_id,
                    "backlinks": backlinks,
                    "count": len(backlinks),
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@obsidian_vault_bp.route("/api/graph", methods=["GET"])
@login_required
@require_permission(Permission.OBSIDIAN_READ)
def get_link_graph():
    """Get full link graph for D3.js visualization"""
    try:
        limit = int(request.args.get("limit", 100))

        indexer = KnowledgeVaultIndexer()
        graph = indexer.get_link_graph(limit=limit)

        return (
            jsonify(
                {
                    "success": True,
                    "graph": graph,
                    "node_count": len(graph["nodes"]),
                    "edge_count": len(graph["edges"]),
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================================================
# SYNC/WATCHER API ROUTES
# ============================================================================


@obsidian_vault_bp.route("/api/sync", methods=["POST"])
@login_required
@require_permission(Permission.OBSIDIAN_ADMIN)
def trigger_reindex():
    """Trigger manual full re-index (admin only)"""
    try:
        result = reindex_all_notes()

        return jsonify({"success": result.get("success", False), "stats": result}), (
            200 if result.get("success") else 500
        )

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@obsidian_vault_bp.route("/api/sync/status", methods=["GET"])
@login_required
@require_permission(Permission.OBSIDIAN_READ)
def sync_status():
    """Get file watcher and sync status"""
    try:
        watcher_status = get_watcher_status()
        indexing_stats = get_indexing_stats()

        return (
            jsonify({"success": True, "watcher": watcher_status, "indexing": indexing_stats}),
            200,
        )

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@obsidian_vault_bp.route("/api/sync/logs", methods=["GET"])
@login_required
@require_permission(Permission.OBSIDIAN_READ)
def sync_logs():
    """Get recent sync event logs"""
    try:
        limit = int(request.args.get("limit", 50))

        from database import get_db

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, event_type, file_path, status, error_message,
                   detected_at, processed_at
            FROM vault_sync_log
            ORDER BY detected_at DESC
            LIMIT %s
        """,
            (limit,),
        )

        logs = []
        for row in cursor.fetchall():
            logs.append(
                {
                    "id": row[0],
                    "event_type": row[1],
                    "file_path": row[2],
                    "status": row[3],
                    "error_message": row[4],
                    "detected_at": row[5].isoformat() if row[5] else None,
                    "processed_at": row[6].isoformat() if row[6] else None,
                }
            )

        cursor.close()

        return jsonify({"success": True, "logs": logs, "count": len(logs)}), 200

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# HEALTH CHECK
# ============================================================================


@obsidian_vault_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    try:
        vault_path = "/mnt/archie_brain/knowledge/"
        vault_exists = os.path.exists(vault_path)

        watcher_status = get_watcher_status()
        indexing_stats = get_indexing_stats()

        healthy = vault_exists and watcher_status.get("running", False)

        return (
            jsonify(
                {
                    "healthy": healthy,
                    "module_id": "obsidian_vault",
                    "vault_exists": vault_exists,
                    "watcher_running": watcher_status.get("running", False),
                    "notes_indexed": indexing_stats.get("total_notes", 0),
                    "status": "healthy" if healthy else "degraded",
                }
            ),
            200,
        )

    except Exception as e:
        return (
            jsonify(
                {
                    "healthy": False,
                    "module_id": "obsidian_vault",
                    "message": str(e),
                    "status": "error",
                }
            ),
            500,
        )
