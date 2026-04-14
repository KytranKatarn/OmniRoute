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
            limit = min(int(request.args.get("limit", 50)), 200)
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
                query += " AND knowledge_type = %s"
                params.append(knowledge_type)

            if search:
                query += " AND (title ILIKE %s OR content ILIKE %s)"
                params.extend([f"%{search}%", f"%{search}%"])

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
            if search:
                count_query += " AND (title ILIKE %s OR content ILIKE %s)"
                count_params.extend([f"%{search}%", f"%{search}%"])

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
    # KNOWLEDGE GRAPH (Task #1133)
    # ==================================================================

    @bp.route("/api/knowledge/graph", methods=["GET"])
    @login_required
    @admin_required
    def knowledge_graph():
        """
        Return knowledge graph data for D3.js force-directed visualization.

        GET /api/knowledge/graph?limit=100

        Returns { nodes: [...], edges: [...] } where:
        - nodes = top KB entries by importance (id, title, type, importance)
        - edges = relationships between those nodes (source, target, type, strength)
        """
        try:
            limit = min(int(request.args.get("limit", 100)), 500)
        except (ValueError, TypeError):
            limit = 100

        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Get top entries by importance
            cur.execute(
                """
                SELECT id, title, knowledge_type, category, importance_score,
                       (embedding IS NOT NULL) as has_embedding
                FROM knowledge_base
                WHERE title IS NOT NULL AND title != ''
                ORDER BY importance_score DESC, updated_at DESC NULLS LAST
                LIMIT %s
                """,
                (limit,),
            )
            entries = cur.fetchall()
            node_ids = [e["id"] for e in entries]

            if not node_ids:
                return jsonify({"success": True, "nodes": [], "edges": []})

            # Get relationships between these entries
            cur.execute(
                """
                SELECT from_id, to_id, relationship_type, strength
                FROM knowledge_relationships
                WHERE from_id = ANY(%s) AND to_id = ANY(%s)
                ORDER BY strength DESC
                """,
                (node_ids, node_ids),
            )
            rels = cur.fetchall()

            # Build response
            nodes = [
                {
                    "id": e["id"],
                    "title": e["title"][:80] if e["title"] else f"Entry {e['id']}",
                    "type": e["knowledge_type"] or "unknown",
                    "category": e["category"] or "uncategorized",
                    "importance": float(e["importance_score"] or 0),
                    "hasEmbedding": bool(e["has_embedding"]),
                }
                for e in entries
            ]

            edges = [
                {
                    "source": r["from_id"],
                    "target": r["to_id"],
                    "type": r["relationship_type"],
                    "strength": float(r["strength"] or 0.5),
                }
                for r in rels
            ]

            return jsonify(
                {
                    "success": True,
                    "nodes": nodes,
                    "edges": edges,
                    "node_count": len(nodes),
                    "edge_count": len(edges),
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
