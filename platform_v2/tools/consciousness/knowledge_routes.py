"""Knowledge Routes -- KB CRUD, search, ingestion

Extracted from routes.py as part of the Consciousness module refactor.
Handles:
- Knowledge CRUD (create, get, list, categories)
- Search (basic + unified)
- Unified knowledge API (stats, agent-context, check-mistakes)
- Document ingestion (text, directory, browse, view, all-docs)
"""

import json
import logging
import os
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)


def _get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", "archiepass"),
    )


def register_knowledge_routes(bp, admin_required):
    """Register all knowledge-related routes on the consciousness blueprint."""

    # ==================================================================
    # SEARCH
    # ==================================================================

    @bp.route("/search", methods=["POST"])
    @login_required
    @admin_required
    def search_knowledge():
        """Search across knowledge_base"""
        print("🔍 [BACKEND] search_knowledge called")

        data = request.get_json() or {}
        query = data.get("query", "")
        category = data.get("category")
        knowledge_type = data.get("knowledge_type")
        limit = data.get("limit", 50)

        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Build query with filters
            sql = """
                SELECT * FROM knowledge_base
                WHERE (content ILIKE %s OR title ILIKE %s)
            """
            params = [f"%{query}%", f"%{query}%"]

            if category:
                sql += " AND category = %s"
                params.append(category)

            if knowledge_type:
                sql += " AND knowledge_type = %s"
                params.append(knowledge_type)

            sql += " ORDER BY importance_score DESC, created_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(sql, params)
            results = cur.fetchall()
            return jsonify({"results": results, "count": len(results)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    # ==================================================================
    # INGESTION
    # ==================================================================

    @bp.route("/ingest-text", methods=["POST"])
    @login_required
    @admin_required
    def ingest_text():
        """Manually add text knowledge to consciousness"""
        data = request.get_json() or {}
        content = data.get("content")
        category = data.get("category", "manual")
        tags = data.get("tags", [])

        if not content:
            return jsonify({"error": "Content required"}), 400

        conn = _get_db()
        cur = conn.cursor()

        try:
            cur.execute(
                """
                INSERT INTO knowledge_base (
                    knowledge_type, content, category, tags,
                    importance_score, source_type, created_at
                ) VALUES (
                    'conversation_memory', %s, %s, %s,
                    0.7, 'manual_entry', NOW()
                )
            """,
                (content, category, tags),
            )

            conn.commit()
            return jsonify({"success": True, "message": "Knowledge added"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    # ==================================================================
    # KNOWLEDGE CRUD
    # ==================================================================

    @bp.route("/knowledge/create", methods=["POST"])
    @login_required
    @admin_required
    def create_knowledge():
        """Create a new knowledge entry with full details (title, content, category, etc.)"""
        data = request.get_json() or {}

        title = data.get("title")
        content = data.get("content")
        category = data.get("category", "uncategorized")
        tags = data.get("tags", [])
        knowledge_type = data.get("knowledge_type", "vault_note")
        importance_score = data.get("importance_score", 0.8)
        is_documentation = data.get("is_documentation", True)

        if not title or not content:
            return jsonify({"error": "Title and content are required"}), 400

        conn = _get_db()
        cur = conn.cursor()

        try:
            cur.execute(
                """
                INSERT INTO knowledge_base (
                    title, content, knowledge_type, category, tags,
                    importance_score, is_documentation, source_type, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, 'consciousness_ui', NOW()
                )
                RETURNING id
            """,
                (
                    title,
                    content,
                    knowledge_type,
                    category,
                    tags,
                    importance_score,
                    is_documentation,
                ),
            )

            new_id = cur.fetchone()[0]
            conn.commit()
            return jsonify({"success": True, "message": "Knowledge entry created", "id": new_id})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    @bp.route("/knowledge/<int:knowledge_id>", methods=["GET"])
    @login_required
    @admin_required
    def get_knowledge(knowledge_id):
        """Get a specific knowledge entry by ID"""
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute(
                """
                SELECT id, title, content, knowledge_type, category, tags,
                       importance_score, is_documentation, created_at, updated_at
                FROM knowledge_base
                WHERE id = %s
            """,
                (knowledge_id,),
            )

            entry = cur.fetchone()
            if entry:
                return jsonify({"success": True, "entry": dict(entry)})
            else:
                return jsonify({"error": "Entry not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    @bp.route("/knowledge/list", methods=["GET"])
    @login_required
    @admin_required
    def list_knowledge():
        """List knowledge entries with filtering and pagination"""
        category = request.args.get("category")
        knowledge_type = request.args.get("type")
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))

        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            query = """
                SELECT id, title, knowledge_type, category, tags, importance_score,
                       created_at, updated_at
                FROM knowledge_base
                WHERE 1=1
            """
            params = []

            if category:
                query += " AND (category = %s OR category LIKE %s)"
                params.extend([category, category + "/%"])

            if knowledge_type and knowledge_type != "all":
                query += " AND knowledge_type = %s"
                params.append(knowledge_type)

            query += " ORDER BY updated_at DESC NULLS LAST LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            cur.execute(query, params)
            entries = cur.fetchall()

            # Get total count
            count_query = "SELECT COUNT(*) FROM knowledge_base WHERE 1=1"
            count_params = []
            if category:
                count_query += " AND (category = %s OR category LIKE %s)"
                count_params.extend([category, category + "/%"])
            if knowledge_type and knowledge_type != "all":
                count_query += " AND knowledge_type = %s"
                count_params.append(knowledge_type)

            cur.execute(count_query, count_params)
            total = cur.fetchone()["count"]
            return jsonify(
                {
                    "success": True,
                    "entries": [dict(e) for e in entries],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    @bp.route("/knowledge/categories", methods=["GET"])
    @login_required
    @admin_required
    def get_categories():
        """Get all categories with counts"""
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute(
                """
                SELECT category, COUNT(*) as count
                FROM knowledge_base
                WHERE category IS NOT NULL AND category != ''
                GROUP BY category
                ORDER BY count DESC
            """
            )

            categories = cur.fetchall()
            return jsonify({"success": True, "categories": [dict(c) for c in categories]})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    # ==================================================================
    # DOCUMENT INGESTION
    # ==================================================================

    @bp.route("/ingest-directory", methods=["POST"])
    @login_required
    @admin_required
    def ingest_directory():
        """Ingest documents from a directory into knowledge base"""
        data = request.get_json() or {}
        directory_path = data.get("path", "/mnt/archie_brain/docs")
        category = data.get("category", "documentation")

        conn = _get_db()
        cur = conn.cursor()

        try:
            files_processed = 0
            errors = []

            if not os.path.exists(directory_path):
                return jsonify({"success": False, "error": "Directory not found"}), 404

            for root, dirs, files in os.walk(directory_path):
                for filename in files:
                    if filename.endswith((".md", ".txt", ".json", ".py", ".js", ".html", ".css")):
                        filepath = os.path.join(root, filename)
                        try:
                            with open(filepath, "r", encoding="utf-8") as f:
                                content = f.read()

                            # Determine subcategory from path
                            rel_path = os.path.relpath(filepath, directory_path)
                            subcategory = os.path.dirname(rel_path) or "root"

                            # Insert into long_term_memory
                            cur.execute(
                                """
                                INSERT INTO long_term_memory
                                (content, category, tags, source_type, importance_score, metadata)
                                VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                                (
                                    content[:5000],  # Limit content size
                                    category,
                                    [
                                        subcategory,
                                        os.path.splitext(filename)[1][1:],
                                    ],  # tags
                                    f"file:{rel_path}",
                                    0.7,  # importance
                                    json.dumps(
                                        {
                                            "filename": filename,
                                            "file_path": rel_path,
                                            "size": len(content),
                                        }
                                    ),
                                ),
                            )

                            files_processed += 1
                        except Exception as e:
                            conn.rollback()
                            errors.append(f"{filename}: {str(e)}")

            conn.commit()
            return jsonify({"success": True, "files_processed": files_processed, "errors": errors})
        except Exception as e:
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    @bp.route("/browse-files", methods=["POST"])
    @login_required
    @admin_required
    def browse_files():
        """Browse files in docs directory and show ingestion status"""
        import psycopg2.extras

        data = request.get_json() or {}
        directory_path = data.get("path", "/mnt/archie_brain/docs")

        try:
            # Get all files in directory recursively
            files_info = []

            for root, dirs, files in os.walk(directory_path):
                for file in files:
                    if file.startswith("."):
                        continue

                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, directory_path)

                    # Get file stats
                    stats = os.stat(full_path)
                    file_size = stats.st_size
                    modified_time = datetime.fromtimestamp(stats.st_mtime)

                    # Determine file type
                    ext = os.path.splitext(file)[1].lower()
                    file_type = "text"
                    if ext in [".md", ".markdown"]:
                        file_type = "markdown"
                    elif ext in [".py", ".js", ".java", ".cpp", ".c", ".h"]:
                        file_type = "code"
                    elif ext in [".json", ".yaml", ".yml", ".xml"]:
                        file_type = "config"
                    elif ext in [".txt", ".log"]:
                        file_type = "text"

                    files_info.append(
                        {
                            "name": file,
                            "path": rel_path,
                            "full_path": full_path,
                            "size": file_size,
                            "modified": modified_time.isoformat(),
                            "type": file_type,
                            "extension": ext,
                        }
                    )

            # Check which files have been ingested
            conn = _get_db()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            for file_info in files_info:
                cur.execute(
                    """
                    SELECT COUNT(*) as count, MAX(created_at) as last_ingested
                    FROM long_term_memory
                    WHERE metadata->>'file_path' = %s
                """,
                    (file_info["full_path"],),
                )

                result = cur.fetchone()
                file_info["ingested"] = result["count"] > 0
                file_info["ingestion_count"] = result["count"]

                if result["last_ingested"]:
                    file_info["last_ingested"] = result["last_ingested"].isoformat()

                    # Check if file was modified after last ingestion
                    file_modified = datetime.fromisoformat(file_info["modified"])
                    last_ingested = result["last_ingested"]

                    # Remove timezone info for comparison (compare as naive datetimes)
                    if last_ingested.tzinfo is not None:
                        last_ingested = last_ingested.replace(tzinfo=None)
                    if file_modified.tzinfo is not None:
                        file_modified = file_modified.replace(tzinfo=None)

                    file_info["needs_update"] = file_modified > last_ingested
                else:
                    file_info["needs_update"] = False
            # Sort by name
            files_info.sort(key=lambda x: x["name"])

            return jsonify(
                {
                    "success": True,
                    "files": files_info,
                    "total_files": len(files_info),
                    "directory": directory_path,
                }
            )
        except Exception as e:
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            try:
                cur.close()
                conn.close()
            except NameError:
                pass

    @bp.route("/view-file", methods=["POST"])
    @login_required
    @admin_required
    def view_file():
        """View contents of a specific file"""
        data = request.get_json() or {}
        file_path = data.get("path")

        if not file_path:
            return jsonify({"success": False, "error": "File path required"}), 400

        # Security check - ensure path is within allowed directory
        allowed_base = "/mnt/archie_brain/docs"
        abs_path = os.path.abspath(file_path)

        if not abs_path.startswith(allowed_base):
            return jsonify({"success": False, "error": "Access denied"}), 403

        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(50000)  # Limit to 50KB

            # Get file stats
            stats = os.stat(abs_path)

            return jsonify(
                {
                    "success": True,
                    "content": content,
                    "size": stats.st_size,
                    "path": abs_path,
                    "truncated": stats.st_size > 50000,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/ingest-all-docs", methods=["POST"])
    @login_required
    @admin_required
    def ingest_all_docs():
        """DEPRECATED: Docs now live in knowledge_base table via docs_migration.py.

        Use Mission Control's Knowledge Base tab or run:
          docker exec archie_platform python3 /app/tools/blueprint/docs_migration.py

        This endpoint returns a deprecation notice and points to the knowledge_base table.
        """
        try:
            conn = _get_db()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM knowledge_base WHERE source_type = 'docs_migration'")
            kb_count = cur.fetchone()[0]
            return jsonify(
                {
                    "success": True,
                    "deprecated": True,
                    "message": "This endpoint is deprecated. Docs are now stored in the knowledge_base table.",
                    "migration_command": "docker exec archie_platform python3 /app/tools/blueprint/docs_migration.py",
                    "knowledge_base_entries": kb_count,
                    "dashboard": "/tools/blueprint (Mission Control > Knowledge Base tab)",
                }
            )
        except Exception as e:
            return (
                jsonify(
                    {
                        "success": False,
                        "deprecated": True,
                        "message": "This endpoint is deprecated. Use docs_migration.py instead.",
                        "error": str(e),
                    }
                ),
                500,
            )
        finally:

            cur.close()

            conn.close()

    # ==================================================================
    # UNIFIED KNOWLEDGE API (Phase 4: Integration Layer)
    # ==================================================================

    @bp.route("/unified/search", methods=["POST"])
    @login_required
    @admin_required
    def unified_search():
        """
        Unified search across all knowledge types.
        Uses the UnifiedKnowledgeService for comprehensive search.
        """
        try:
            from services.unified_knowledge import get_unified_knowledge_service

            data = request.get_json() or {}
            query = data.get("query", "")
            knowledge_types = data.get("types")
            categories = data.get("categories")
            limit = data.get("limit", 10)

            service = get_unified_knowledge_service()
            result = service.search(
                query=query,
                knowledge_types=knowledge_types,
                categories=categories,
                limit=limit,
            )

            return jsonify(result)

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/unified/stats", methods=["GET"])
    @login_required
    @admin_required
    def unified_stats():
        """
        Get comprehensive statistics across all knowledge types.
        """
        try:
            from services.unified_knowledge import get_unified_knowledge_service

            service = get_unified_knowledge_service()
            stats = service.get_statistics()

            return jsonify({"success": True, "stats": stats})

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/unified/agent-context", methods=["POST"])
    @login_required
    @admin_required
    def unified_agent_context():
        """
        Get context for an AI agent before executing a task.
        Returns mistakes to avoid, relevant knowledge, and suggestions.
        """
        try:
            from services.unified_knowledge import get_unified_knowledge_service

            data = request.get_json() or {}
            task_description = data.get("task", "")
            agent_type = data.get("agent_type", "general")

            if not task_description:
                return (
                    jsonify({"success": False, "error": "Task description required"}),
                    400,
                )

            service = get_unified_knowledge_service()
            context = service.get_agent_context(task_description, agent_type)

            return jsonify({"success": True, "context": context})

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/unified/check-mistakes", methods=["POST"])
    @login_required
    @admin_required
    def unified_check_mistakes():
        """
        Check for similar mistakes before executing an operation.
        Part of the Mistake Learning Loop.
        """
        try:
            from services.unified_knowledge import get_unified_knowledge_service

            data = request.get_json() or {}
            context = data.get("context", "")

            if not context:
                return jsonify({"success": False, "error": "Context required"}), 400

            service = get_unified_knowledge_service()
            mistakes = service.check_for_similar_mistakes(context)

            return jsonify(
                {
                    "success": True,
                    "mistakes": mistakes,
                    "count": len(mistakes),
                    "has_warnings": len(mistakes) > 0,
                }
            )

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
