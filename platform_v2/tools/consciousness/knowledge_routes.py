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
from database import _get_db_password
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
        password=_get_db_password(),
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
        logger.debug("[BACKEND] search_knowledge called")

        data = request.get_json() or {}
        query = data.get("query", "")
        category = data.get("category")
        knowledge_type = data.get("knowledge_type")
        limit = min(data.get("limit", 50), 500)

        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Build query with filters
            sql = """
                SELECT id, title, content, knowledge_type, category, tags,
                       importance_score, source_type, created_at, updated_at
                FROM knowledge_base
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
            conn.rollback()
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
            conn.rollback()
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
        search = request.args.get("search")
        try:
            limit = min(int(request.args.get("limit", 50)), 500)
            offset = max(int(request.args.get("offset", 0)), 0)
        except (ValueError, TypeError):
            limit, offset = 50, 0

        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            query = """
                SELECT id, title, knowledge_type, category, tags, importance_score,
                       created_at, updated_at,
                       (embedding IS NOT NULL) as has_embedding
                FROM knowledge_base
                WHERE 1=1
            """
            params = []

            if category:
                query += " AND (category = %s OR category LIKE %s)"
                params.extend([category, category + "/%"])

            if knowledge_type and knowledge_type != "all":
                if knowledge_type == "knowledge_card":
                    # Match all knowledge_card_* subtypes
                    query += " AND knowledge_type LIKE 'knowledge_card%%'"
                else:
                    query += " AND knowledge_type = %s"
                    params.append(knowledge_type)

            if search:
                query += " AND (title ILIKE %s OR content ILIKE %s)"
                params.extend([f"%{search}%", f"%{search}%"])

            query += """
             ORDER BY
               CASE knowledge_type
                 WHEN 'mistake_learned'     THEN 1
                 WHEN 'vault_note'          THEN 2
                 WHEN 'code_snippet'        THEN 3
                 WHEN 'conversation_memory' THEN 99
                 WHEN 'github_file'         THEN 100
                 ELSE 4
               END,
               importance_score DESC NULLS LAST
             LIMIT %s OFFSET %s"""
            params.extend([limit, offset])

            cur.execute(query, params)
            raw_entries = cur.fetchall()
            entries = [dict(e) for e in raw_entries]

            # Get total count
            count_query = "SELECT COUNT(*) FROM knowledge_base WHERE 1=1"
            count_params = []
            if category:
                count_query += " AND (category = %s OR category LIKE %s)"
                count_params.extend([category, category + "/%"])
            if knowledge_type and knowledge_type != "all":
                if knowledge_type == "knowledge_card":
                    count_query += " AND knowledge_type LIKE 'knowledge_card%%'"
                else:
                    count_query += " AND knowledge_type = %s"
                    count_params.append(knowledge_type)
            if search:
                count_query += " AND (title ILIKE %s OR content ILIKE %s)"
                count_params.extend([f"%{search}%", f"%{search}%"])

            cur.execute(count_query, count_params)
            total = cur.fetchone()["count"]
            import json as _json
            from flask import Response as _Response

            payload = _json.dumps(
                {"success": True, "entries": entries, "total": total, "limit": limit, "offset": offset},
                default=str,
            )
            return _Response(payload, mimetype="application/json")
        except Exception as e:
            import json as _json
            from flask import Response as _Response

            return _Response(_json.dumps({"error": str(e)}), status=500, mimetype="application/json")
        finally:

            cur.close()

            conn.close()

    @bp.route("/knowledge/categories", methods=["GET"])
    @login_required
    @admin_required
    def get_categories():
        """Get all categories with counts, plus cross-table virtual categories."""
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
            categories = [dict(c) for c in cur.fetchall()]

            # Virtual cross-table categories (Dev HQ + Languages tabs)
            cur.execute("SELECT COUNT(*) FROM project_decisions")
            dec_count = cur.fetchone()["count"]
            cur.execute("SELECT COUNT(*) FROM translations")
            trans_count = cur.fetchone()["count"]

            virtual = [
                {
                    "category": "Dev HQ Decisions",
                    "count": dec_count,
                    "virtual": True,
                    "link_tab": "devhq",
                    "description": "ADRs & architectural decisions",
                },
                {
                    "category": "Languages / Translations",
                    "count": trans_count,
                    "virtual": True,
                    "link_tab": "languages",
                    "description": "8 languages, all UI strings",
                },
            ]
            return jsonify({"success": True, "categories": virtual + categories})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    # ==================================================================
    # TYPE STATS (for browser quick-filter chips)
    # ==================================================================

    @bp.route("/knowledge/type-stats", methods=["GET"])
    @login_required
    @admin_required
    def get_type_stats():
        """Return per-type counts for the browser quick-filter chips."""
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                SELECT
                    CASE
                        WHEN knowledge_type = 'github_file'        THEN 'github_file'
                        WHEN knowledge_type = 'conversation_memory' THEN 'conversation_memory'
                        WHEN knowledge_type = 'vault_note'         THEN 'vault_note'
                        WHEN knowledge_type LIKE 'knowledge_card%%' THEN 'knowledge_card'
                        WHEN knowledge_type = 'api_endpoint'       THEN 'api_endpoint'
                        WHEN knowledge_type = 'mistake_learned'    THEN 'mistake_learned'
                        WHEN knowledge_type = 'code_snippet'       THEN 'code_snippet'
                        WHEN knowledge_type = 'upgrade_suggestion' THEN 'upgrade_suggestion'
                        ELSE 'other'
                    END AS type_group,
                    COUNT(*) AS count
                FROM knowledge_base
                GROUP BY type_group
                ORDER BY count DESC
                """
            )
            rows = cur.fetchall()
            return jsonify({"success": True, "types": [dict(r) for r in rows]})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
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

        # Security: restrict to allowed base directories
        allowed_bases = ["/mnt/archie_brain/docs", "/mnt/archie_brain/ai_bridge", "/app"]
        abs_dir = os.path.abspath(directory_path)
        if not any(abs_dir.startswith(base) for base in allowed_bases):
            return jsonify({"success": False, "error": "Access denied"}), 403

        conn = _get_db()
        cur = conn.cursor()

        try:
            files_processed = 0
            errors = []

            if not os.path.exists(abs_dir):
                return jsonify({"success": False, "error": "Directory not found"}), 404

            for root, dirs, files in os.walk(abs_dir):
                for filename in files:
                    if filename.endswith((".md", ".txt", ".json", ".py", ".js", ".html", ".css")):
                        filepath = os.path.join(root, filename)
                        try:
                            cur.execute("SAVEPOINT file_ingest")
                            with open(filepath, "r", encoding="utf-8") as f:
                                content = f.read()

                            # Determine subcategory from path
                            rel_path = os.path.relpath(filepath, abs_dir)
                            subcategory = os.path.dirname(rel_path) or "root"

                            cur.execute(
                                """
                                INSERT INTO knowledge_base
                                (title, content, knowledge_type, source_type, tags, importance_score, metadata)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT DO NOTHING
                            """,
                                (
                                    filename,
                                    content[:5000],
                                    category,
                                    f"file:{rel_path}",
                                    [
                                        subcategory,
                                        os.path.splitext(filename)[1][1:],
                                    ],
                                    0.7,
                                    json.dumps(
                                        {
                                            "filename": filename,
                                            "file_path": rel_path,
                                            "size": len(content),
                                        }
                                    ),
                                ),
                            )

                            cur.execute("RELEASE SAVEPOINT file_ingest")
                            files_processed += 1
                        except Exception as e:
                            cur.execute("ROLLBACK TO SAVEPOINT file_ingest")
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

        # Security: restrict to allowed base directories
        allowed_bases = ["/mnt/archie_brain/docs", "/mnt/archie_brain/ai_bridge", "/app"]
        abs_dir = os.path.abspath(directory_path)
        if not any(abs_dir.startswith(base) for base in allowed_bases):
            return jsonify({"success": False, "error": "Access denied"}), 403

        conn = None
        cur = None
        try:
            # Get all files in directory recursively
            files_info = []

            for root, dirs, files in os.walk(abs_dir):
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
                    FROM knowledge_base
                    WHERE metadata->>'file_path' = %s
                """,
                    (file_info["path"],),
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
            if cur:
                cur.close()
            if conn:
                conn.close()

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

        Use Dev HQ Knowledge tab or MCP search_knowledge instead.

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
                    "knowledge_base_entries": kb_count,
                    "dashboard": "/dev-hq (Dev HQ > Knowledge tab)",
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

    @bp.route("/api/knowledge/quality-stats")
    @admin_required
    def knowledge_quality_stats():
        """Get quality score distribution for dashboard."""
        try:
            from services.quality_scoring_service import get_quality_stats

            stats = get_quality_stats()
            return jsonify({"success": True, **stats})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ==================================================================
    # UNIFIED KNOWLEDGE API (Phase 4: Integration Layer)
    # ==================================================================

    # ==================================================================
    # RAG ENDPOINT (Task #1131)
    # ==================================================================

    @bp.route("/api/knowledge/rag", methods=["GET"])
    @login_required
    @admin_required
    def rag_search():
        """
        RAG endpoint — return top KB entries as formatted context blocks.

        GET /api/knowledge/rag?q=<query>&limit=5

        Uses semantic (vector) search from ai_bridge.semantic_search for
        embedding similarity, falling back to keyword search when embeddings
        are unavailable.
        """
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify({"success": False, "error": "Query parameter 'q' is required"}), 400

        try:
            limit = min(int(request.args.get("limit", 5)), 20)
        except (ValueError, TypeError):
            limit = 5

        try:
            from ai_bridge.semantic_search import search as semantic_search
        except ImportError:
            # Fallback: do a simple ILIKE search if semantic_search unavailable
            return _rag_fallback_search(query, limit)

        try:
            results = semantic_search(query, limit=limit)

            # Build formatted context string
            context_parts = ["## Relevant Knowledge\n"]
            sources = []
            total_chars = 0

            for i, r in enumerate(results, 1):
                title = r.title or f"Entry {r.id}"
                content = r.content or ""
                # Truncate individual entries to keep context manageable
                if len(content) > 1500:
                    content = content[:1500] + "..."

                context_parts.append(f"### Entry {i}: {title}\n{content}\n")
                total_chars += len(content)

                sources.append(
                    {
                        "id": r.id,
                        "title": title,
                        "type": r.source_type or "unknown",
                        "relevance": round(r.score, 4) if r.score else 0.0,
                    }
                )

            context_text = "\n".join(context_parts) if len(context_parts) > 1 else ""

            # Rough token estimate (~4 chars per token)
            token_estimate = total_chars // 4

            return jsonify(
                {
                    "success": True,
                    "query": query,
                    "context": context_text,
                    "sources": sources,
                    "token_estimate": token_estimate,
                }
            )

        except Exception as e:
            logger.error(f"[RAG] Search failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    def _rag_fallback_search(query, limit):
        """Fallback RAG search using basic ILIKE when semantic_search is unavailable."""
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                SELECT id, title, content, knowledge_type, source_type,
                       importance_score
                FROM knowledge_base
                WHERE (content ILIKE %s OR title ILIKE %s)
                  AND embedding IS NOT NULL
                ORDER BY importance_score DESC, created_at DESC
                LIMIT %s
                """,
                (f"%{query}%", f"%{query}%", limit),
            )
            rows = cur.fetchall()

            context_parts = ["## Relevant Knowledge\n"]
            sources = []
            total_chars = 0

            for i, row in enumerate(rows, 1):
                title = row["title"] or f"Entry {row['id']}"
                content = (row["content"] or "")[:1500]
                context_parts.append(f"### Entry {i}: {title}\n{content}\n")
                total_chars += len(content)
                sources.append(
                    {
                        "id": row["id"],
                        "title": title,
                        "type": row["source_type"] or "unknown",
                        "relevance": float(row["importance_score"] or 0),
                    }
                )

            context_text = "\n".join(context_parts) if len(context_parts) > 1 else ""

            return jsonify(
                {
                    "success": True,
                    "query": query,
                    "context": context_text,
                    "sources": sources,
                    "token_estimate": total_chars // 4,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()
            conn.close()

    # ==================================================================
    # KNOWLEDGE GRAPH — Full Consciousness Coverage
    # Sources: knowledge_base (all types) + project_decisions (Dev HQ)
    #          + translations (Languages) + unified_projects (Dev HQ)
    # ==================================================================

    @bp.route("/api/knowledge/graph", methods=["GET"])
    @login_required
    @admin_required
    def knowledge_graph():
        """
        Return knowledge graph data for D3.js force-directed visualization.
        Covers all Consciousness module sources proportionally.

        GET /api/knowledge/graph?limit=500

        Node IDs are strings: 'kb-{id}', 'dec-{id}', 'trans-{id}', 'proj-{id}'
        """
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute("SELECT COUNT(*) FROM knowledge_base")
            total_kb = cur.fetchone()["count"]
            cur.execute("SELECT COUNT(*) FROM knowledge_relationships")
            total_rels = cur.fetchone()["count"]

            # ── knowledge_base: proportional by knowledge_type bucket ─
            # Budget ~370 nodes. Caps per bucket ensure every type appears.
            cur.execute(
                """
                WITH bucketed AS (
                    SELECT id, title, knowledge_type, category,
                           importance_score, source_type,
                           (embedding IS NOT NULL) AS has_embedding,
                           CASE
                             WHEN knowledge_type = 'mistake_learned'     THEN 'mistake_learned'
                             WHEN knowledge_type = 'vault_note'          THEN 'vault_note'
                             WHEN knowledge_type = 'code_snippet'        THEN 'code_snippet'
                             WHEN knowledge_type LIKE 'knowledge_card%%' THEN 'knowledge_card'
                             WHEN knowledge_type = 'conversation_memory' THEN 'conversation_memory'
                             WHEN source_type    = 'github_tree'         THEN 'github_tree'
                             ELSE 'other'
                           END AS bucket,
                           ROW_NUMBER() OVER (
                             PARTITION BY CASE
                               WHEN knowledge_type = 'mistake_learned'     THEN 'mistake_learned'
                               WHEN knowledge_type = 'vault_note'          THEN 'vault_note'
                               WHEN knowledge_type = 'code_snippet'        THEN 'code_snippet'
                               WHEN knowledge_type LIKE 'knowledge_card%%' THEN 'knowledge_card'
                               WHEN knowledge_type = 'conversation_memory' THEN 'conversation_memory'
                               WHEN source_type    = 'github_tree'         THEN 'github_tree'
                               ELSE 'other'
                             END
                             ORDER BY importance_score DESC NULLS LAST
                           ) AS rn
                    FROM knowledge_base
                    WHERE title IS NOT NULL AND title != ''
                )
                SELECT id, title, knowledge_type, category,
                       importance_score, has_embedding,
                       'knowledge_base' AS source_table
                FROM bucketed
                WHERE (bucket = 'mistake_learned'    AND rn <= 50)
                   OR (bucket = 'vault_note'         AND rn <= 50)
                   OR (bucket = 'code_snippet'       AND rn <= 30)
                   OR (bucket = 'knowledge_card'     AND rn <= 100)
                   OR (bucket = 'conversation_memory' AND rn <= 30)
                   OR (bucket = 'github_tree'        AND rn <= 40)
                   OR (bucket = 'other'              AND rn <= 70)
                LIMIT 370
                """
            )
            kb_entries = cur.fetchall()

            # ── project_decisions (Dev HQ) ────────────────────────────
            cur.execute(
                """
                SELECT id,
                       COALESCE(NULLIF(title, ''), LEFT(decision, 80)) AS title,
                       'decision'          AS knowledge_type,
                       'Dev HQ'            AS category,
                       0.88               AS importance_score,
                       (embedding IS NOT NULL) AS has_embedding,
                       'project_decisions' AS source_table
                FROM project_decisions
                WHERE (title IS NOT NULL AND title != '')
                   OR (decision IS NOT NULL AND decision != '')
                ORDER BY decided_at DESC NULLS LAST, created_at DESC
                LIMIT 50
                """
            )
            dec_entries = cur.fetchall()

            # ── translations (Languages tab — EN keys only) ───────────
            cur.execute(
                """
                SELECT id, key AS title,
                       'translation'  AS knowledge_type,
                       'Languages'    AS category,
                       0.75          AS importance_score,
                       (embedding IS NOT NULL) AS has_embedding,
                       'translations' AS source_table
                FROM translations
                WHERE language = 'en' AND text IS NOT NULL
                ORDER BY id DESC
                LIMIT 30
                """
            )
            trans_entries = cur.fetchall()

            # ── unified_projects (Dev HQ) ─────────────────────────────
            cur.execute(
                """
                SELECT id, name AS title,
                       'project'           AS knowledge_type,
                       'Dev HQ'            AS category,
                       GREATEST(0.1, LEAST(1.0, priority::float / 10.0)) AS importance_score,
                       (embedding IS NOT NULL) AS has_embedding,
                       'unified_projects'  AS source_table
                FROM unified_projects
                WHERE name IS NOT NULL AND status NOT IN ('cancelled')
                ORDER BY priority DESC NULLS LAST, created_at DESC
                LIMIT 20
                """
            )
            proj_entries = cur.fetchall()

            all_entries = list(kb_entries) + list(dec_entries) + list(trans_entries) + list(proj_entries)

            if not all_entries:
                return jsonify(
                    {
                        "success": True,
                        "nodes": [],
                        "edges": [],
                        "total_kb_entries": total_kb,
                        "total_relationships": total_rels,
                    }
                )

            # ── Build nodes with string node_key ─────────────────────
            _prefix = {
                "knowledge_base": "kb",
                "project_decisions": "dec",
                "translations": "trans",
                "unified_projects": "proj",
            }

            nodes = []
            node_map = {}
            kb_embed_ids, dec_embed_ids, trans_embed_ids, proj_embed_ids = [], [], [], []

            for e in all_entries:
                tbl = e["source_table"]
                nkey = f"{_prefix.get(tbl, 'x')}-{e['id']}"
                if nkey in node_map:
                    continue
                node_map[nkey] = True
                nodes.append(
                    {
                        "id": nkey,
                        "node_key": nkey,
                        "numeric_id": e["id"],
                        "source_table": tbl,
                        "title": (e["title"] or "")[:80],
                        "type": e["knowledge_type"] or "unknown",
                        "category": e["category"] or "uncategorized",
                        "importance": float(e["importance_score"] or 0),
                        "hasEmbedding": bool(e["has_embedding"]),
                        "isConnected": False,
                    }
                )
                if e["has_embedding"]:
                    if tbl == "knowledge_base":
                        kb_embed_ids.append(e["id"])
                    elif tbl == "project_decisions":
                        dec_embed_ids.append(e["id"])
                    elif tbl == "translations":
                        trans_embed_ids.append(e["id"])
                    elif tbl == "unified_projects":
                        proj_embed_ids.append(e["id"])

            # ── Explicit KB↔KB relationships → string keys ───────────
            kb_numeric_ids = [e["id"] for e in kb_entries]
            cur.execute(
                """
                SELECT from_id, to_id, relationship_type, strength
                FROM knowledge_relationships
                WHERE from_id = ANY(%s) AND to_id = ANY(%s)
                ORDER BY strength DESC
                """,
                (kb_numeric_ids, kb_numeric_ids),
            )
            rels = cur.fetchall()

            connected_keys = set()
            for r in rels:
                connected_keys.add(f"kb-{r['from_id']}")
                connected_keys.add(f"kb-{r['to_id']}")
            for n in nodes:
                if n["node_key"] in connected_keys:
                    n["isConnected"] = True

            edges = [
                {
                    "source": f"kb-{r['from_id']}",
                    "target": f"kb-{r['to_id']}",
                    "type": r["relationship_type"],
                    "strength": float(r["strength"] or 0.5),
                    "kind": "explicit",
                }
                for r in rels
            ]
            explicit_pairs = {(f"kb-{r['from_id']}", f"kb-{r['to_id']}") for r in rels}
            explicit_pairs |= {(f"kb-{r['to_id']}", f"kb-{r['from_id']}") for r in rels}

            # ── Semantic similarity — cross-table ─────────────────────
            # Table names are hardcoded constants, not user input — f-string safe.
            def _sim_query(tbl_a, ids_a, pfx_a, tbl_b, ids_b, pfx_b, cap):
                if not ids_a or not ids_b:
                    return []
                same = tbl_a == tbl_b
                join = "ON a.id < b.id" if same else "ON TRUE"
                cur.execute(
                    f"""
                    SELECT a.id AS a_id, b.id AS b_id,
                           1 - (a.embedding <=> b.embedding) AS similarity
                    FROM {tbl_a} a
                    JOIN {tbl_b} b {join}
                    WHERE a.id = ANY(%s) AND b.id = ANY(%s)
                      AND 1 - (a.embedding <=> b.embedding) > 0.65
                    ORDER BY similarity DESC
                    LIMIT %s
                    """,
                    (ids_a, ids_b, cap),
                )
                result = []
                for r in cur.fetchall():
                    a_key = f"{pfx_a}-{r['a_id']}"
                    b_key = f"{pfx_b}-{r['b_id']}"
                    if (a_key, b_key) not in explicit_pairs and (b_key, a_key) not in explicit_pairs:
                        result.append(
                            {
                                "source": a_key,
                                "target": b_key,
                                "type": "semantic_similarity",
                                "strength": float(r["similarity"]),
                                "kind": "semantic",
                            }
                        )
                return result

            sem_edges = []
            sem_edges += _sim_query("knowledge_base", kb_embed_ids, "kb", "knowledge_base", kb_embed_ids, "kb", 600)
            sem_edges += _sim_query(
                "knowledge_base", kb_embed_ids, "kb", "project_decisions", dec_embed_ids, "dec", 300
            )
            sem_edges += _sim_query("knowledge_base", kb_embed_ids, "kb", "translations", trans_embed_ids, "trans", 200)
            sem_edges += _sim_query(
                "knowledge_base", kb_embed_ids, "kb", "unified_projects", proj_embed_ids, "proj", 100
            )
            sem_edges += _sim_query(
                "project_decisions", dec_embed_ids, "dec", "project_decisions", dec_embed_ids, "dec", 100
            )
            sem_edges += _sim_query(
                "project_decisions", dec_embed_ids, "dec", "unified_projects", proj_embed_ids, "proj", 80
            )
            sem_edges = sem_edges[:1500]
            edges += sem_edges

            explicit_count = sum(1 for e in edges if e["kind"] == "explicit")
            semantic_count = sum(1 for e in edges if e["kind"] == "semantic")

            return jsonify(
                {
                    "success": True,
                    "nodes": nodes,
                    "edges": edges,
                    "node_count": len(nodes),
                    "edge_count": explicit_count,
                    "semantic_edge_count": semantic_count,
                    "total_kb_entries": total_kb,
                    "total_relationships": total_rels,
                }
            )
        except Exception as e:
            logger.error(f"[GRAPH] Failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()
            conn.close()

    @bp.route("/api/knowledge/links/<int:entry_id>", methods=["GET"])
    @login_required
    @admin_required
    def knowledge_links(entry_id):
        """Get all links (forward + backlinks) for a KB entry."""
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            # Forward links (this entry → others)
            cur.execute(
                """
                SELECT kr.to_id as linked_id, kr.relationship_type, kr.strength,
                       kb.title, kb.knowledge_type, kb.category
                FROM knowledge_relationships kr
                JOIN knowledge_base kb ON kb.id = kr.to_id
                WHERE kr.from_id = %s
                ORDER BY kr.strength DESC
                """,
                (entry_id,),
            )
            forward = cur.fetchall()

            # Backlinks (others → this entry)
            cur.execute(
                """
                SELECT kr.from_id as linked_id, kr.relationship_type, kr.strength,
                       kb.title, kb.knowledge_type, kb.category
                FROM knowledge_relationships kr
                JOIN knowledge_base kb ON kb.id = kr.from_id
                WHERE kr.to_id = %s
                ORDER BY kr.strength DESC
                """,
                (entry_id,),
            )
            backlinks = cur.fetchall()

            return jsonify(
                {
                    "success": True,
                    "entry_id": entry_id,
                    "forward_links": [
                        {
                            "id": r["linked_id"],
                            "title": r["title"][:100] if r["title"] else f"Entry {r['linked_id']}",
                            "type": r["relationship_type"],
                            "strength": float(r["strength"] or 0.5),
                            "knowledge_type": r["knowledge_type"],
                            "category": r["category"],
                        }
                        for r in forward
                    ],
                    "backlinks": [
                        {
                            "id": r["linked_id"],
                            "title": r["title"][:100] if r["title"] else f"Entry {r['linked_id']}",
                            "type": r["relationship_type"],
                            "strength": float(r["strength"] or 0.5),
                            "knowledge_type": r["knowledge_type"],
                            "category": r["category"],
                        }
                        for r in backlinks
                    ],
                    "total_links": len(forward),
                    "total_backlinks": len(backlinks),
                }
            )
        except Exception as e:
            logger.error(f"[LINKS] Failed for entry {entry_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()
            conn.close()

    @bp.route("/api/knowledge/links", methods=["POST"])
    @login_required
    @admin_required
    def create_knowledge_link():
        """Create a manual link between two KB entries."""
        data = request.get_json() or {}
        from_id = data.get("from_id")
        to_id = data.get("to_id")
        link_type = data.get("type", "related_to")

        if not from_id or not to_id:
            return jsonify({"success": False, "error": "from_id and to_id required"}), 400
        if from_id == to_id:
            return jsonify({"success": False, "error": "Cannot link entry to itself"}), 400

        conn = _get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO knowledge_relationships (from_id, to_id, relationship_type, strength, created_by)
                VALUES (%s, %s, %s, 0.8, 'manual')
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                (from_id, to_id, link_type),
            )
            result = cur.fetchone()
            conn.commit()
            if result:
                return jsonify({"success": True, "link_id": result[0]})
            else:
                return jsonify({"success": True, "message": "Link already exists"})
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()
            conn.close()

    @bp.route("/api/knowledge/backlinks-summary", methods=["GET"])
    @login_required
    @admin_required
    def knowledge_backlinks_summary():
        """Top KB entries by number of backlinks — most referenced knowledge."""
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                SELECT kb.id, kb.title, kb.knowledge_type, kb.category,
                       COUNT(kr.id) as backlink_count
                FROM knowledge_base kb
                JOIN knowledge_relationships kr ON kr.to_id = kb.id
                GROUP BY kb.id, kb.title, kb.knowledge_type, kb.category
                ORDER BY backlink_count DESC
                LIMIT 20
                """
            )
            entries = cur.fetchall()
            return jsonify(
                {
                    "success": True,
                    "entries": [
                        {
                            "id": e["id"],
                            "title": e["title"][:100] if e["title"] else f"Entry {e['id']}",
                            "knowledge_type": e["knowledge_type"],
                            "category": e["category"],
                            "backlink_count": e["backlink_count"],
                        }
                        for e in entries
                    ],
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()
            conn.close()

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
