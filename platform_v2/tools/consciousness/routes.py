"""
Consciousness Module Routes - ADMIN-ONLY

This module handles:
- Memory Management (conversation memories from knowledge_base)
- Team Awareness (agent directory, performance tracking)
- Analytics (knowledge growth metrics)

All routes require admin authentication.

Data protection
---------------
The ``knowledge_base`` table this module owns is backed up by the 4-tier
pipeline at ``/mnt/archie_brain/scripts/backup/``:
- Daily: ``component_db.sh`` (pg_dump -Fc) → primary + USB + GDrive
- Weekly: ``component_kb_export.sh`` (data-only -t knowledge_base) → primary + GDrive
Restoring knowledge_base requires a postgres with the pgvector extension
(use ``pgvector/pgvector:pg16`` image or install the extension first) —
the ``embedding`` column is of type ``vector``. See
``scripts/backup/README.md`` for the full recovery runbook and RTO table.
"""

from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date
import decimal
import base64
import json
import logging
import os
from database import _get_db_password
import sys


logger = logging.getLogger(__name__)


def _safe_dict(row):
    """Convert a psycopg2 RealDictRow to a plain dict with JSON-serializable types.

    Converts:
    - decimal.Decimal → float
    - datetime / date → ISO 8601 string
    - bytes → None (not serializable anyway)
    """
    if row is None:
        return None
    result = {}
    for k, v in row.items():
        if isinstance(v, decimal.Decimal):
            result[k] = float(v)
        elif isinstance(v, (datetime, date)):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


def _safe_list(rows):
    """Apply _safe_dict to a list of rows."""
    return [_safe_dict(r) for r in rows]


# Add platform root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from rbac import Permission, has_permission
from logging_config import audit_log
from services import agent_service

from . import consciousness_bp

# ============================================================================
# AUTHENTICATION DECORATOR
# ============================================================================


def admin_required(f):
    """Decorator to require admin access"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not has_permission(Permission.ADMIN_ACCESS, current_user):
            audit_log(
                "ADMIN_ACCESS_DENIED",
                {
                    "route": request.endpoint,
                    "user_id": (current_user.id if current_user.is_authenticated else None),
                },
                success=False,
            )
            flash("Admin access required", "error")
            return redirect(url_for("dashboard"))

        audit_log("ADMIN_ACCESS", {"route": request.endpoint, "user_id": current_user.id})
        return f(*args, **kwargs)

    return decorated_function


# ============================================================================
# DATABASE CONNECTION
# ============================================================================


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


# ============================================================================
# MAIN DASHBOARD
# ============================================================================


@consciousness_bp.route("/")
@login_required
@admin_required
def index():
    """Consciousness dashboard - memory, analytics, team"""
    return render_template("consciousness_dashboard.html")


# Dashboard summary moved to dashboard_routes.py


# ============================================================================
# MEMORY MANAGEMENT ROUTES
# ============================================================================


@consciousness_bp.route("/memory")
@login_required
@admin_required
def memory():
    """View A.R.C.H.I.E.'s memory tables"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get table sizes
        cur.execute(
            """
            SELECT
                'knowledge_base' as table_name,
                COUNT(*) as row_count,
                pg_size_pretty(pg_total_relation_size('knowledge_base')) as total_size
            FROM knowledge_base
            UNION ALL
            SELECT
                'long_term_memory',
                COUNT(*),
                pg_size_pretty(pg_total_relation_size('long_term_memory'))
            FROM long_term_memory
        """
        )
        table_stats = cur.fetchall()
        return render_template("consciousness_memory.html", table_stats=table_stats)
    except Exception as e:
        flash(f"Error loading memory: {str(e)}", "error")
        return redirect(url_for("consciousness.index"))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/memories/<view_type>", methods=["GET"])
@login_required
@admin_required
def get_memories(view_type):
    """Get memories by view type (recent, important, accessed, types)"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Different queries based on view type
        if view_type == "recent":
            cur.execute(
                """
                SELECT * FROM knowledge_base
                WHERE knowledge_type = 'conversation_memory'
                ORDER BY created_at DESC
                LIMIT 50
            """
            )
        elif view_type == "important":
            cur.execute(
                """
                SELECT * FROM knowledge_base
                WHERE knowledge_type = 'conversation_memory'
                ORDER BY importance_score DESC, created_at DESC
                LIMIT 50
            """
            )
        elif view_type == "accessed":
            cur.execute(
                """
                SELECT * FROM knowledge_base
                WHERE knowledge_type = 'conversation_memory'
                  AND last_accessed IS NOT NULL
                ORDER BY last_accessed DESC
                LIMIT 50
            """
            )
        elif view_type == "types":
            cur.execute(
                """
                SELECT
                    knowledge_type,
                    COUNT(*) as count,
                    ROUND(AVG(importance_score)::numeric, 2) as avg_importance
                FROM knowledge_base
                GROUP BY knowledge_type
                ORDER BY count DESC
            """
            )
        else:
            return jsonify({"error": f"Unknown view_type: {view_type}. Valid: recent, important, accessed, types"}), 400

        memories = cur.fetchall()
        return jsonify({"memories": _safe_list(memories), "view_type": view_type})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# emotional-state route moved to team_routes.py
@consciousness_bp.route("/backup", methods=["POST"])
@login_required
@admin_required
def backup_consciousness():
    """Backup A.R.C.H.I.E.'s consciousness"""
    try:
        import subprocess

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = "/var/backups/archie_brain"
        backup_file = f"{backup_dir}/archie_consciousness_{timestamp}.sql"

        # Create backup directory if it doesn't exist
        os.makedirs(backup_dir, exist_ok=True)

        db_host = os.environ.get("DB_HOST", "archie_database")
        db_port = os.environ.get("DB_PORT", "5432")
        db_name = os.environ.get("DB_NAME", "archie")
        db_user = os.environ.get("DB_USER", "archie")

        # Direct pg_dump over the network (runs inside the platform container)
        result = subprocess.run(
            [
                "pg_dump",
                "-h",
                db_host,
                "-p",
                db_port,
                "-U",
                db_user,
                "-d",
                db_name,
                "-t",
                "knowledge_base",
                "-t",
                "long_term_memory",
                "-f",
                backup_file,
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PGPASSWORD": _get_db_password(),
            },
            timeout=120,
        )

        if result.returncode == 0:
            return jsonify(
                {
                    "success": True,
                    "message": f"Consciousness backed up to {backup_file}",
                }
            )
        else:
            return jsonify({"success": False, "error": result.stderr}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Backup timed out (120s)"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/stats", methods=["GET"])
@login_required
@admin_required
def get_stats():
    """Get comprehensive knowledge statistics - ALL database fields for complete business awareness"""
    import psycopg2.extras

    conn = None

    cur = None

    conn = None

    cur = None

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # TOTAL KNOWLEDGE - All sources combined
        cur.execute("SELECT COUNT(*) as total FROM long_term_memory")
        long_term_memories = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) as total FROM improvement_proposals")
        improvement_proposals_count = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) as total FROM improvement_conversations")
        improvement_conversations_count = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) as total FROM archie_codebase_knowledge")
        codebase_knowledge_count = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) as total FROM ai_conversations")
        ai_conversations_count = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) as total FROM archie_core_identity")
        core_identity_count = cur.fetchone()["total"]

        # Learning Resources from external GitHub repos
        cur.execute("SELECT COUNT(*) as total FROM knowledge_base")
        knowledge_base_count = cur.fetchone()["total"]

        # Claude Code Sessions (conversation checkpoints from pre-compact hook)
        cur.execute(
            """
            SELECT COUNT(*) as total
            FROM knowledge_base
            WHERE source_type = 'claude_code_hook'
        """
        )
        claude_code_sessions_count = cur.fetchone()["total"]

        # Conversation memories breakdown by source
        cur.execute(
            """
            SELECT source_type, COUNT(*) as count
            FROM knowledge_base
            WHERE knowledge_type = 'conversation_memory'
            GROUP BY source_type
            ORDER BY count DESC
        """
        )
        conversation_sources = cur.fetchall()

        # Learning resources breakdown by repo type
        cur.execute(
            """
            SELECT repo_type, COUNT(*) as count,
                   COUNT(*) FILTER (WHERE is_code = true) as code_files,
                   COUNT(*) FILTER (WHERE is_documentation = true) as docs
            FROM knowledge_base
            GROUP BY repo_type
            ORDER BY count DESC
        """
        )
        learning_resources_breakdown = cur.fetchall()

        # Calculate TOTAL knowledge across all sources
        total_knowledge = (
            long_term_memories
            + improvement_proposals_count
            + improvement_conversations_count
            + codebase_knowledge_count
            + ai_conversations_count
            + core_identity_count
            + knowledge_base_count
        )

        # Memory Type breakdown (NEW - tracks what kind of knowledge)
        cur.execute(
            """
            SELECT memory_type, COUNT(*) as count
            FROM long_term_memory
            WHERE memory_type IS NOT NULL
            GROUP BY memory_type
            ORDER BY count DESC
        """
        )
        memory_types = cur.fetchall()

        # Category breakdown (code_snippet, solution, website, knowledge)
        cur.execute(
            """
            SELECT category, COUNT(*) as count
            FROM long_term_memory
            WHERE category IS NOT NULL
            GROUP BY category
            ORDER BY count DESC
        """
        )
        categories = cur.fetchall()

        # ALL Tags analysis (not limited) - Multi-color categorization
        cur.execute(
            """
            SELECT unnest(tags) as tag, COUNT(*) as count
            FROM long_term_memory
            WHERE tags IS NOT NULL AND array_length(tags, 1) > 0
            GROUP BY tag
            ORDER BY count DESC
        """
        )
        all_tags = cur.fetchall()

        # NEW TAGS DETECTION - Tags that appeared recently
        cur.execute(
            """
            WITH tag_first_appearance AS (
                SELECT
                    unnest(tags) as tag,
                    MIN(created_at) as first_seen,
                    COUNT(*) as usage_count
                FROM long_term_memory
                WHERE tags IS NOT NULL AND array_length(tags, 1) > 0
                GROUP BY unnest(tags)
            )
            SELECT
                tag,
                first_seen,
                usage_count,
                CASE
                    WHEN first_seen >= NOW() - INTERVAL '7 days' THEN 'new_7d'
                    WHEN first_seen >= NOW() - INTERVAL '30 days' THEN 'new_30d'
                    ELSE 'established'
                END as tag_age
            FROM tag_first_appearance
            ORDER BY first_seen DESC
        """
        )
        tag_timeline = cur.fetchall()

        # Extract only new tags (last 30 days)
        new_tags = [dict(t) for t in tag_timeline if t["tag_age"] in ["new_7d", "new_30d"]]

        # Importance distribution
        cur.execute(
            """
            SELECT
                CASE
                    WHEN importance_score >= 0.8 THEN 'Critical'
                    WHEN importance_score >= 0.6 THEN 'High'
                    WHEN importance_score >= 0.4 THEN 'Medium'
                    ELSE 'Low'
                END as level,
                COUNT(*) as count
            FROM long_term_memory
            GROUP BY level
            ORDER BY MIN(importance_score) DESC
        """
        )
        importance_dist = cur.fetchall()

        # Learning timeline (last 30 days)
        cur.execute(
            """
            SELECT DATE(created_at) as date, COUNT(*) as count
            FROM long_term_memory
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY DATE(created_at)
            ORDER BY date ASC
        """
        )
        learning_timeline = cur.fetchall()

        # Source distribution (conversation vs ai_response)
        cur.execute(
            """
            SELECT
                COALESCE(metadata->>'source', 'unknown') as source,
                COUNT(*) as count
            FROM long_term_memory
            WHERE metadata IS NOT NULL
            GROUP BY metadata->>'source'
            ORDER BY count DESC
        """
        )
        sources = cur.fetchall()

        # Metadata field usage analysis (NEW - tracks all metadata keys)
        cur.execute(
            """
            SELECT DISTINCT jsonb_object_keys(metadata) as field, COUNT(*) as count
            FROM long_term_memory
            WHERE metadata IS NOT NULL
            GROUP BY field
            ORDER BY count DESC
        """
        )
        metadata_fields = cur.fetchall()

        # Access patterns (NEW - most accessed knowledge)
        cur.execute(
            """
            SELECT category, memory_type, AVG(access_count) as avg_access,
                   MAX(access_count) as max_access
            FROM long_term_memory
            WHERE access_count > 0
            GROUP BY category, memory_type
            ORDER BY avg_access DESC
        """
        )
        access_patterns = cur.fetchall()

        # Knowledge growth rate (NEW - memories added per week)
        cur.execute(
            """
            SELECT
                DATE_TRUNC('week', created_at) as week,
                COUNT(*) as count
            FROM long_term_memory
            WHERE created_at >= NOW() - INTERVAL '90 days'
            GROUP BY week
            ORDER BY week DESC
        """
        )
        growth_rate = cur.fetchall()

        # User interactions (NEW - if user_id is tracked)
        cur.execute(
            """
            SELECT user_id, COUNT(*) as memory_count,
                   AVG(importance_score) as avg_importance
            FROM long_term_memory
            WHERE user_id IS NOT NULL
            GROUP BY user_id
            ORDER BY memory_count DESC
        """
        )
        user_interactions = cur.fetchall()

        # Recent memories
        cur.execute(
            """
            SELECT id, content, category, memory_type, tags,
                   importance_score, created_at, access_count
            FROM long_term_memory
            ORDER BY created_at DESC
            LIMIT 10
        """
        )
        recent = cur.fetchall()

        # Recently indexed learning resources
        cur.execute(
            """
            SELECT repo_type, file_name, file_path, file_extension,
                   indexed_at, is_code, is_documentation,
                   LENGTH(content) as file_size,
                   title, category, knowledge_type
            FROM knowledge_base
            ORDER BY indexed_at DESC
            LIMIT 15
        """
        )
        recent_learning_resources = cur.fetchall()

        # Repository Health Dashboard
        cur.execute(
            """
            SELECT repo_name, repo_type, status, indexed,
                   indexed_files, cloned_at, updated_at,
                   last_pull, last_push, local_path
            FROM github_repositories
            ORDER BY
                CASE
                    WHEN status = 'cloned' AND indexed = true THEN 1
                    WHEN status = 'cloned' AND indexed = false THEN 2
                    ELSE 3
                END,
                repo_type
        """
        )
        repository_health = cur.fetchall()
        # Convert to JSON-serializable format
        for item in learning_timeline:
            if item["date"]:
                item["date"] = item["date"].isoformat()

        for item in growth_rate:
            if item["week"]:
                item["week"] = item["week"].isoformat()

        for item in tag_timeline:
            if item["first_seen"]:
                item["first_seen"] = item["first_seen"].isoformat()

        for item in recent:
            item["id"] = str(item["id"])
            if item["created_at"]:
                item["created_at"] = item["created_at"].isoformat()

        for item in recent_learning_resources:
            if item["indexed_at"]:
                item["indexed_at"] = item["indexed_at"].isoformat()

        for item in repository_health:
            if item["cloned_at"]:
                item["cloned_at"] = item["cloned_at"].isoformat()
            if item["updated_at"]:
                item["updated_at"] = item["updated_at"].isoformat()
            if item["last_pull"]:
                item["last_pull"] = item["last_pull"].isoformat()
            if item["last_push"]:
                item["last_push"] = item["last_push"].isoformat()

        result = {
            "success": True,
            "stats": {
                "total_knowledge": total_knowledge,
                "knowledge_sources": {
                    "long_term_memories": long_term_memories,
                    "improvement_proposals": improvement_proposals_count,
                    "improvement_conversations": improvement_conversations_count,
                    "codebase_knowledge": codebase_knowledge_count,
                    "ai_conversations": ai_conversations_count,
                    "core_identity": core_identity_count,
                    "learning_resources": knowledge_base_count,
                    "learning_resources_breakdown": [dict(r) for r in learning_resources_breakdown],
                    "claude_code_sessions": claude_code_sessions_count,
                    "conversation_sources": [dict(c) for c in conversation_sources],
                },
                "total_memories": long_term_memories,  # Keep for backwards compatibility
                "memory_types": [dict(m) for m in memory_types],
                "categories": [dict(c) for c in categories],
                "all_tags": [dict(t) for t in all_tags],
                "tag_timeline": [dict(t) for t in tag_timeline],
                "new_tags": new_tags,
                "new_tags_count_7d": len([t for t in new_tags if t["tag_age"] == "new_7d"]),
                "new_tags_count_30d": len([t for t in new_tags if t["tag_age"] == "new_30d"]),
                "importance_distribution": [dict(i) for i in importance_dist],
                "learning_timeline": [dict(l) for l in learning_timeline],
                "sources": [dict(s) for s in sources],
                "metadata_fields": [dict(m) for m in metadata_fields],
                "access_patterns": [dict(a) for a in access_patterns],
                "growth_rate": [dict(g) for g in growth_rate],
                "user_interactions": [dict(u) for u in user_interactions],
                "recent_memories": [dict(r) for r in recent],
                "recent_learning_resources": [dict(r) for r in recent_learning_resources],
                "repository_health": [dict(r) for r in repository_health],
            },
        }

        return jsonify(result)
    except Exception as e:

        logger.error("Error in get_consciousness_stats: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/charts-data", methods=["GET"])
@login_required
@admin_required
def get_charts_data():
    """Provide chart-ready data from ALL knowledge sources for the Charts tab"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Combined knowledge growth (30 days, all sources, daily)
        cur.execute(
            """
            SELECT d.date::date as date,
                COALESCE(kb.cnt, 0) as knowledge_base,
                COALESCE(ltm.cnt, 0) as memories,
                COALESCE(tri.cnt, 0) as triage,
                COALESCE(bp.cnt, 0) as blueprints
            FROM generate_series(NOW() - INTERVAL '30 days', NOW(), '1 day') d(date)
            LEFT JOIN (SELECT DATE(created_at) dt, COUNT(*) cnt FROM knowledge_base GROUP BY dt) kb ON d.date::date = kb.dt
            LEFT JOIN (SELECT DATE(created_at) dt, COUNT(*) cnt FROM long_term_memory GROUP BY dt) ltm ON d.date::date = ltm.dt
            LEFT JOIN (SELECT DATE(created_at) dt, COUNT(*) cnt FROM triage_extractions GROUP BY dt) tri ON d.date::date = tri.dt
            LEFT JOIN (SELECT DATE(created_at) dt, COUNT(*) cnt FROM blueprint_tasks GROUP BY dt) bp ON d.date::date = bp.dt
            ORDER BY d.date
        """
        )
        combined_growth = []
        for r in cur.fetchall():
            row = dict(r)
            row["date"] = str(row["date"])
            row["total"] = row["knowledge_base"] + row["memories"] + row["triage"] + row["blueprints"]
            combined_growth.append(row)

        # 2. Knowledge type breakdown (from knowledge_base — richest source)
        cur.execute(
            """
            SELECT knowledge_type, COUNT(*) as count
            FROM knowledge_base GROUP BY knowledge_type ORDER BY count DESC
        """
        )
        kb_type_breakdown = [{"type": r["knowledge_type"], "count": r["count"]} for r in cur.fetchall()]

        # 3. LTM category breakdown
        cur.execute(
            """
            SELECT category, COUNT(*) as count
            FROM long_term_memory WHERE category IS NOT NULL
            GROUP BY category ORDER BY count DESC LIMIT 10
        """
        )
        ltm_categories = [dict(r) for r in cur.fetchall()]

        # 4. Importance distribution (from long_term_memory)
        cur.execute(
            """
            SELECT CASE WHEN importance_score >= 0.8 THEN 'Critical'
                        WHEN importance_score >= 0.6 THEN 'High'
                        WHEN importance_score >= 0.4 THEN 'Medium'
                        ELSE 'Low' END as level, COUNT(*) as count
            FROM long_term_memory GROUP BY level ORDER BY MIN(importance_score) DESC
        """
        )
        importance = [dict(r) for r in cur.fetchall()]

        # 5. Embedding coverage by knowledge type
        cur.execute(
            """
            SELECT knowledge_type,
                COUNT(*) as total,
                SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) as embedded
            FROM knowledge_base GROUP BY knowledge_type ORDER BY total DESC
        """
        )
        embedding_coverage = [
            {
                "type": r["knowledge_type"],
                "total": r["total"],
                "embedded": r["embedded"],
            }
            for r in cur.fetchall()
        ]
        return jsonify(
            {
                "success": True,
                "combined_growth": combined_growth,
                "kb_type_breakdown": kb_type_breakdown,
                "ltm_categories": ltm_categories,
                "importance": importance,
                "embedding_coverage": embedding_coverage,
            }
        )
    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# search_knowledge() moved to knowledge_routes.py


@consciousness_bp.route("/memory/<int:memory_id>", methods=["DELETE"])
@login_required
@admin_required
def delete_memory(memory_id):
    """Delete a memory from knowledge_base"""
    conn = None
    cur = None
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("DELETE FROM knowledge_base WHERE id = %s", (memory_id,))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/memory/<int:memory_id>", methods=["PUT"])
@login_required
@admin_required
def update_memory(memory_id):
    """Update a memory — only updates fields that are provided"""
    data = request.get_json() or {}

    conn = None

    cur = None

    conn = None

    cur = None

    try:
        conn = get_db()
        cur = conn.cursor()

        # Build dynamic UPDATE — only set fields that were provided
        updates = []
        params = []
        if "content" in data:
            updates.append("content = %s")
            params.append(data["content"])
        if "category" in data:
            updates.append("category = %s")
            params.append(data["category"])
        if "tags" in data:
            updates.append("tags = %s")
            params.append(data["tags"])
        if "importance_score" in data:
            updates.append("importance_score = %s")
            params.append(data["importance_score"])

        if not updates:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        updates.append("updated_at = NOW()")
        params.append(memory_id)

        cur.execute(
            f"UPDATE knowledge_base SET {', '.join(updates)} WHERE id = %s",
            params,
        )
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# ingest_text(), create_knowledge(), get_knowledge(), list_knowledge(),
# get_categories() moved to knowledge_routes.py


# Team routes (directory, agents, performance, leaderboard, awareness, emotions)
# moved to team_routes.py
# Analytics, sessions, learning-patterns, experiences, work-context
# moved to insights_routes.py
# ============================================================================
# COMPREHENSIVE BRAIN STATE - EVERYTHING AT ONCE
# ============================================================================


@consciousness_bp.route("/brain-state", methods=["GET"])
@login_required
@admin_required
def get_complete_brain_state():
    """Get ARCHIE's complete brain state - all consciousness data"""

    conn = None

    cur = None

    conn = None

    cur = None

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Overall statistics
        cur.execute(
            """
            SELECT
                COUNT(*) as total_knowledge_entries,
                COUNT(DISTINCT knowledge_type) as unique_types,
                COUNT(DISTINCT category) as unique_categories,
                SUM(access_count) as total_accesses,
                AVG(importance_score) as avg_importance,
                MIN(created_at) as first_memory,
                MAX(created_at) as latest_memory,
                pg_size_pretty(pg_total_relation_size('knowledge_base')) as database_size
            FROM knowledge_base
        """
        )

        overall_stats = cur.fetchone()

        # Knowledge by type
        cur.execute(
            """
            SELECT
                knowledge_type,
                COUNT(*) as count,
                ROUND(AVG(importance_score)::numeric, 2) as avg_importance,
                SUM(access_count) as total_accesses
            FROM knowledge_base
            GROUP BY knowledge_type
            ORDER BY count DESC
        """
        )

        knowledge_by_type = cur.fetchall()

        # Conversation sessions summary
        cur.execute(
            """
            SELECT
                COUNT(*) as total_sessions,
                COUNT(DISTINCT phase) as unique_phases,
                COUNT(DISTINCT primary_topic) as unique_topics,
                COUNT(DISTINCT git_branch) as unique_branches,
                SUM(LENGTH(full_transcript)) as total_transcript_chars,
                MAX(compact_triggered_at) as last_session
            FROM conversation_sessions
        """
        )

        sessions_summary = cur.fetchone()

        # Recent activity (last 24 hours)
        cur.execute(
            """
            SELECT
                COUNT(*) as entries_added_24h,
                COUNT(DISTINCT knowledge_type) as types_added_24h
            FROM knowledge_base
            WHERE created_at > NOW() - INTERVAL '24 hours'
        """
        )

        recent_activity = cur.fetchone()

        # Most important memories
        cur.execute(
            """
            SELECT
                id,
                knowledge_type,
                title,
                category,
                tags,
                importance_score,
                access_count,
                created_at
            FROM knowledge_base
            ORDER BY importance_score DESC, access_count DESC
            LIMIT 10
        """
        )

        top_memories = cur.fetchall()

        # Emotional state
        cur.execute(
            """
            SELECT id, timestamp, current_mood as mood, mood_intensity as energy,
                   stress_level as confidence, trigger_event as notes
            FROM agent_emotional_state
            ORDER BY timestamp DESC LIMIT 1
        """
        )

        current_emotion = cur.fetchone()
        return jsonify(
            {
                "overall_stats": _safe_dict(overall_stats),
                "knowledge_by_type": _safe_list(knowledge_by_type),
                "sessions_summary": _safe_dict(sessions_summary),
                "recent_activity": _safe_dict(recent_activity),
                "top_memories": _safe_list(top_memories),
                "current_emotion": _safe_dict(current_emotion) or {"mood": "neutral", "energy": 0.5, "confidence": 0.5},
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# ingest_directory(), browse_files(), view_file(), ingest_all_docs()
# moved to knowledge_routes.py

# unified_search(), unified_stats(), unified_agent_context(), unified_check_mistakes()
# moved to knowledge_routes.py


@consciousness_bp.route("/unified/record-mistake", methods=["POST"])
@login_required
@admin_required
def unified_record_mistake():
    """
    Record a new mistake to the knowledge base.
    Part of the Mistake Learning Loop.
    """
    try:
        from services.unified_knowledge import get_unified_knowledge_service

        data = request.get_json() or {}
        error_type = data.get("error_type", "Unknown")
        error_message = data.get("error_message", "")
        solution = data.get("solution", "")
        context = data.get("context", {})
        tags = data.get("tags")

        if not error_message:
            return jsonify({"success": False, "error": "Error message required"}), 400

        service = get_unified_knowledge_service()
        entry_id = service.record_mistake(
            error_type=error_type,
            error_message=error_message,
            solution=solution,
            context=context,
            tags=tags,
        )

        if entry_id:
            return jsonify(
                {
                    "success": True,
                    "entry_id": entry_id,
                    "message": f"Mistake recorded as entry #{entry_id}",
                }
            )
        else:
            return jsonify({"success": False, "error": "Failed to record mistake"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/unified/recent", methods=["GET"])
@login_required
@admin_required
def unified_recent_activity():
    """
    Get recent knowledge activity.
    """
    try:
        from services.unified_knowledge import get_unified_knowledge_service

        hours = request.args.get("hours", 24, type=int)
        limit = request.args.get("limit", 20, type=int)

        service = get_unified_knowledge_service()
        activity = service.get_recent_activity(hours, limit)

        return jsonify(
            {
                "success": True,
                "activity": activity,
                "count": len(activity),
                "hours": hours,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# KNOWLEDGE GRAPH & BACKLINKS
# ============================================================================
# NOTE: Knowledge graph is served by knowledge_routes.py at
# GET /api/knowledge/graph — this stub was removed (returned empty data).
# ============================================================================


@consciousness_bp.route("/brain-map/data", methods=["GET"])
@login_required
@admin_required
def get_brain_map_data():
    """Hierarchical brain map data: knowledge types → categories with inter-type similarity."""
    conn = None
    cur = None
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get regions: knowledge_type → categories with counts and importance
        cur.execute(
            """
            SELECT knowledge_type,
                   COALESCE(category, 'uncategorized') as category,
                   COUNT(*) as count,
                   ROUND(AVG(importance_score)::numeric, 3) as avg_importance
            FROM knowledge_base
            WHERE knowledge_type IS NOT NULL
            GROUP BY knowledge_type, COALESCE(category, 'uncategorized')
            ORDER BY knowledge_type, count DESC
        """
        )
        rows = cur.fetchall()

        # Build region hierarchy — consolidate knowledge_card_* subtypes
        region_map = {}
        for r in rows:
            kt = r["knowledge_type"]
            # Group all knowledge_card_* variants into one region
            if kt.startswith("knowledge_card"):
                kt = "knowledge_card"
            if kt not in region_map:
                region_map[kt] = {
                    "type": kt,
                    "categories": [],
                    "total_count": 0,
                    "importance_sum": 0,
                    "importance_n": 0,
                }
            region_map[kt]["categories"].append(
                {
                    "name": r["category"],
                    "count": r["count"],
                    "avg_importance": float(r["avg_importance"] or 0),
                }
            )
            region_map[kt]["total_count"] += r["count"]
            region_map[kt]["importance_sum"] += float(r["avg_importance"] or 0) * r["count"]
            region_map[kt]["importance_n"] += r["count"]

        # Growth last 7 days per type (with same grouping)
        cur.execute(
            """
            SELECT CASE WHEN knowledge_type LIKE 'knowledge_card%%' THEN 'knowledge_card'
                        ELSE knowledge_type END as grouped_type,
                   COUNT(*) as growth
            FROM knowledge_base
            WHERE created_at >= NOW() - INTERVAL '7 days'
              AND knowledge_type IS NOT NULL
            GROUP BY grouped_type
        """
        )
        growth_map = {r["grouped_type"]: r["growth"] for r in cur.fetchall()}

        # Pretty labels
        label_map = {
            "vault_note": "Vault Notes",
            "mistake_learned": "Mistakes Learned",
            "code_snippet": "Code Snippets",
            "github_file": "GitHub Files",
            "conversation_memory": "Conversations",
            "improvement": "Improvements",
            "technical_docs": "Technical Docs",
            "learning_data": "Learning Data",
            "project_context": "Project Context",
            "decision": "Decisions",
            "knowledge_card": "Knowledge Cards",
            "upgrade_suggestion": "Upgrade Suggestions",
            "api_endpoint": "API Endpoints",
            "system_info": "System Info",
        }

        regions = []
        for kt, rm in region_map.items():
            avg_imp = round(rm["importance_sum"] / rm["importance_n"], 3) if rm["importance_n"] else 0
            regions.append(
                {
                    "type": kt,
                    "label": label_map.get(kt, kt.replace("_", " ").title()),
                    "count": rm["total_count"],
                    "categories": rm["categories"][:15],  # Top 15 categories
                    "avg_importance": avg_imp,
                    "growth_7d": growth_map.get(kt, 0),
                }
            )
        regions.sort(key=lambda x: x["count"], reverse=True)

        # Inter-type connections via pgvector cosine similarity
        # Sample one representative entry per type and compute pairwise similarity
        connections = []
        type_list = [r["type"] for r in regions if r["count"] > 0]
        if len(type_list) >= 2:
            # Get one well-embedded representative per type
            placeholders = ",".join(["%s"] * len(type_list))
            cur.execute(
                f"""
                SELECT DISTINCT ON (knowledge_type) id, knowledge_type
                FROM knowledge_base
                WHERE knowledge_type IN ({placeholders})
                  AND embedding IS NOT NULL
                  AND importance_score IS NOT NULL
                ORDER BY knowledge_type, importance_score DESC
            """,
                type_list,
            )
            reps = cur.fetchall()

            if len(reps) >= 2:
                rep_ids = {r["knowledge_type"]: r["id"] for r in reps}
                # Compute pairwise cosine similarity
                pairs = []
                type_keys = list(rep_ids.keys())
                for i in range(len(type_keys)):
                    for j in range(i + 1, len(type_keys)):
                        pairs.append(
                            (
                                type_keys[i],
                                type_keys[j],
                                rep_ids[type_keys[i]],
                                rep_ids[type_keys[j]],
                            )
                        )

                for src_type, tgt_type, src_id, tgt_id in pairs:
                    cur.execute(
                        """
                        SELECT 1 - (a.embedding <=> b.embedding) as similarity
                        FROM knowledge_base a, knowledge_base b
                        WHERE a.id = %s AND b.id = %s
                    """,
                        (src_id, tgt_id),
                    )
                    row = cur.fetchone()
                    if row and row["similarity"] is not None:
                        sim = round(float(row["similarity"]), 3)
                        if sim > 0.5:  # Only strong connections
                            connections.append(
                                {
                                    "source": src_type,
                                    "target": tgt_type,
                                    "strength": sim,
                                }
                            )

        connections.sort(key=lambda x: x["strength"], reverse=True)
        connections = connections[:15]  # Top 15 only to reduce visual clutter

        # Overall stats
        cur.execute(
            """
            SELECT COUNT(*) as total,
                   COUNT(CASE WHEN embedding IS NOT NULL THEN 1 END) as embedded,
                   COUNT(CASE WHEN created_at >= NOW() - INTERVAL '7 days' THEN 1 END) as growth_7d
            FROM knowledge_base
        """
        )
        stats_row = cur.fetchone()
        stats = {
            "total": stats_row["total"],
            "embedded": stats_row["embedded"],
            "types": len(regions),
            "growth_7d": stats_row["growth_7d"],
        }

        return jsonify(
            {
                "success": True,
                "regions": regions,
                "connections": connections,
                "stats": stats,
            }
        )

    except Exception as e:
        logger.error(f"Brain map data error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/brain-map/drill-down", methods=["GET"])
@login_required
@admin_required
def get_brain_map_drill_down():
    """Drill down into a brain region — returns individual knowledge entries."""
    knowledge_type = request.args.get("type")
    category = request.args.get("category")
    limit = request.args.get("limit", 50, type=int)

    if not knowledge_type:
        return jsonify({"success": False, "error": "type parameter required"}), 400

    conn = None

    cur = None

    conn = None

    cur = None

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Handle grouped knowledge_card type
        if knowledge_type == "knowledge_card":
            type_condition = "knowledge_type LIKE 'knowledge_card%%'"
            params = []
        else:
            type_condition = "knowledge_type = %s"
            params = [knowledge_type]

        query = (
            """
            SELECT id, title, importance_score, created_at,
                   CASE WHEN embedding IS NOT NULL THEN true ELSE false END as has_embedding,
                   tags, category
            FROM knowledge_base
            WHERE """
            + type_condition
        )

        if category:
            query += " AND COALESCE(category, 'uncategorized') = %s"
            params.append(category)

        query += " ORDER BY importance_score DESC NULLS LAST, created_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        entries = cur.fetchall()

        # Serialize
        result = []
        for e in entries:
            result.append(
                {
                    "id": e["id"],
                    "title": e["title"],
                    "importance": (float(e["importance_score"]) if e["importance_score"] else 0),
                    "created_at": (e["created_at"].isoformat() if e["created_at"] else None),
                    "has_embedding": e["has_embedding"],
                    "tags": e["tags"],
                    "category": e["category"],
                }
            )

        return jsonify(
            {
                "success": True,
                "entries": result,
                "count": len(result),
                "type": knowledge_type,
                "category": category,
            }
        )

    except Exception as e:
        logger.error(f"Brain map drill-down error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/knowledge/<int:knowledge_id>/backlinks", methods=["GET"])
@login_required
@admin_required
def get_knowledge_backlinks(knowledge_id):
    """
    Get all knowledge entries that link to this entry.
    Essential for understanding how knowledge is interconnected.
    """
    # TODO: Task #1806 — Knowledge Graph with wikilink/backlink relationships
    return jsonify(
        {
            "success": True,
            "knowledge_id": knowledge_id,
            "backlinks": [],
            "count": 0,
        }
    )


# team-awareness route moved to team_routes.py


# ============================================================================
# ACTIVITY FEED ENDPOINTS - Phase 28
# ============================================================================


@consciousness_bp.route("/activity-feed")
@login_required
@admin_required
def get_activity_feed():
    """
    Get real-time activity feed for the Consciousness dashboard.
    Aggregates events from multiple sources:
    - Knowledge base additions
    - Claude Code conversation ingests
    - Agent executions
    - Learning events (mistakes learned)
    - Improvement proposals
    """
    conn = None
    cur = None
    conn = None
    cur = None
    try:
        # Get time window from query params (default 1 hour)
        hours = request.args.get("hours", 1, type=int)
        limit = request.args.get("limit", 50, type=int)
        event_type = request.args.get("type")  # Filter by event type

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        activities = []

        # 1. Recent knowledge base additions
        if not event_type or event_type == "knowledge":
            cur.execute(
                """
                SELECT
                    id,
                    'knowledge' as event_type,
                    title,
                    knowledge_type as subtype,
                    category,
                    importance_score,
                    source_type,
                    created_at,
                    CASE
                        WHEN knowledge_type = 'mistake_learned' THEN 'Learned from mistake'
                        WHEN knowledge_type = 'vault_note' THEN 'Vault note indexed'
                        WHEN knowledge_type = 'code_snippet' THEN 'Code snippet saved'
                        WHEN knowledge_type = 'github_file' THEN 'GitHub file indexed'
                        WHEN knowledge_type = 'conversation_memory' THEN 'Conversation memory created'
                        ELSE 'Knowledge added'
                    END as description
                FROM knowledge_base
                WHERE created_at >= NOW() - (%s * INTERVAL '1 hour')
                AND source_type != 'archie_v1'
                ORDER BY created_at DESC
                LIMIT %s
            """,
                (hours, limit),
            )
            knowledge_events = cur.fetchall()
            for event in knowledge_events:
                event["created_at"] = event["created_at"].isoformat() if event["created_at"] else None
                activities.append(dict(event))

        # 2. Recent agent executions (currently 0 rows — wrapped for resilience)
        if not event_type or event_type == "execution":
            try:
                cur.execute(
                    """
                    SELECT
                        ae.id,
                        'execution' as event_type,
                        a.name as agent_name,
                        ae.task_description as subtype,
                        ae.status,
                        ae.duration_seconds,
                        ae.tokens_used as token_count,
                        ae.cost,
                        ae.started_at as created_at,
                        CASE
                            WHEN ae.status = 'completed' THEN 'Task completed successfully'
                            WHEN ae.status = 'failed' THEN 'Task failed'
                            ELSE 'Task ' || ae.status
                        END as description
                    FROM agent_executions ae
                    JOIN agents a ON ae.agent_id = a.id
                    WHERE ae.started_at >= NOW() - (%s * INTERVAL '1 hour')
                    ORDER BY ae.started_at DESC
                    LIMIT %s
                """,
                    (hours, limit),
                )
                execution_events = cur.fetchall()
                for event in execution_events:
                    event["created_at"] = event["created_at"].isoformat() if event["created_at"] else None
                    activities.append(dict(event))
            except Exception:
                conn.rollback()

        # 3. Recent improvement proposals (currently 0 rows — wrapped for resilience)
        if not event_type or event_type == "improvement":
            try:
                cur.execute(
                    """
                    SELECT
                        id,
                        'improvement' as event_type,
                        title,
                        status as subtype,
                        priority,
                        complexity,
                        proposed_at as created_at,
                        CASE
                            WHEN status = 'proposed' THEN 'New improvement proposed'
                            WHEN status = 'approved' THEN 'Improvement approved'
                            WHEN status = 'in_progress' THEN 'Improvement in progress'
                            WHEN status = 'completed' THEN 'Improvement completed'
                            WHEN status = 'rejected' THEN 'Improvement rejected'
                            ELSE 'Improvement ' || status
                        END as description
                    FROM improvement_proposals
                    WHERE proposed_at >= NOW() - (%s * INTERVAL '1 hour')
                    ORDER BY proposed_at DESC
                    LIMIT %s
                """,
                    (hours, limit),
                )
                improvement_events = cur.fetchall()
                for event in improvement_events:
                    event["created_at"] = event["created_at"].isoformat() if event["created_at"] else None
                    activities.append(dict(event))
            except Exception:
                conn.rollback()

        # 4. Recent conversation sessions (Claude Code ingests)
        if not event_type or event_type == "session":
            cur.execute(
                """
                SELECT
                    id,
                    'session' as event_type,
                    session_name as title,
                    primary_topic as subtype,
                    phase,
                    productivity_score,
                    learning_value,
                    started_at as created_at,
                    'Claude Code session: ' || COALESCE(session_name, 'Unnamed') as description
                FROM conversation_sessions
                WHERE started_at >= NOW() - (%s * INTERVAL '1 hour')
                ORDER BY started_at DESC
                LIMIT %s
            """,
                (hours, limit),
            )
            session_events = cur.fetchall()
            for event in session_events:
                event["created_at"] = event["created_at"].isoformat() if event["created_at"] else None
                activities.append(dict(event))

        # 5. Recent emotional state changes (if tracked)
        if not event_type or event_type == "emotional":
            cur.execute(
                """
                SELECT
                    id,
                    'emotional' as event_type,
                    current_mood as subtype,
                    mood_intensity,
                    mood_intensity as energy,
                    stress_level as confidence,
                    timestamp as created_at,
                    'Mood: ' || current_mood || ' (Energy: ' || ROUND(mood_intensity::numeric, 2) || ')' as description
                FROM agent_emotional_state
                WHERE timestamp >= NOW() - (%s * INTERVAL '1 hour')
                ORDER BY timestamp DESC
                LIMIT %s
            """,
                (hours, limit),
            )
            emotional_events = cur.fetchall()
            for event in emotional_events:
                event["created_at"] = event["created_at"].isoformat() if event["created_at"] else None
                activities.append(dict(event))

        # 6. LLM alerts (currently 0 rows — wrapped for resilience)
        if not event_type or event_type == "llm_alert":
            try:
                cur.execute(
                    """
                    SELECT
                        id,
                        'llm_alert' as event_type,
                        alert_type as subtype,
                        severity,
                        message as description,
                        acknowledged,
                        created_at
                    FROM llm_alerts
                    WHERE created_at >= NOW() - (%s * INTERVAL '1 hour')
                    ORDER BY created_at DESC
                    LIMIT %s
                """,
                    (hours, limit),
                )
                llm_events = cur.fetchall()
                for event in llm_events:
                    event["created_at"] = event["created_at"].isoformat() if event["created_at"] else None
                    activities.append(dict(event))
            except Exception:
                conn.rollback()

        # 7. Project activity (currently 0 rows — wrapped for resilience)
        if not event_type or event_type == "project":
            try:
                cur.execute(
                    """
                    SELECT
                        id,
                        'project' as event_type,
                        activity_type as subtype,
                        description,
                        entity_type,
                        created_at
                    FROM project_activity
                    WHERE created_at >= NOW() - (%s * INTERVAL '1 hour')
                    ORDER BY created_at DESC
                    LIMIT %s
                """,
                    (hours, limit),
                )
                project_events = cur.fetchall()
                for event in project_events:
                    event["created_at"] = event["created_at"].isoformat() if event["created_at"] else None
                    activities.append(dict(event))
            except Exception:
                conn.rollback()

        # 8. Work sessions (currently 0 rows — wrapped for resilience)
        if not event_type or event_type == "work_session":
            try:
                cur.execute(
                    """
                    SELECT
                        id,
                        'work_session' as event_type,
                        session_type as subtype,
                        focus_description as description,
                        status,
                        started_at as created_at
                    FROM work_sessions
                    WHERE started_at >= NOW() - (%s * INTERVAL '1 hour')
                    ORDER BY started_at DESC
                    LIMIT %s
                """,
                    (hours, limit),
                )
                work_events = cur.fetchall()
                for event in work_events:
                    event["created_at"] = event["created_at"].isoformat() if event["created_at"] else None
                    activities.append(dict(event))
            except Exception:
                conn.rollback()

        # Sort all activities by created_at descending
        activities.sort(key=lambda x: x.get("created_at") or "", reverse=True)

        # Limit total results
        activities = activities[:limit]

        # Get summary counts by type
        type_counts = {}
        for activity in activities:
            t = activity.get("event_type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        return jsonify(
            {
                "success": True,
                "feed": activities,
                "count": len(activities),
                "type_counts": type_counts,
                "time_window_hours": hours,
            }
        )

    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/activity-stats")
@login_required
@admin_required
def get_activity_stats():
    """Get activity statistics for the dashboard"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get counts for different time windows
        cur.execute(
            """
            SELECT
                -- Last hour
                (SELECT COUNT(*) FROM knowledge_base WHERE created_at >= NOW() - INTERVAL '1 hour') as knowledge_1h,
                (SELECT COUNT(*) FROM agent_executions WHERE started_at >= NOW() - INTERVAL '1 hour') as executions_1h,
                (SELECT COUNT(*) FROM improvement_proposals WHERE proposed_at >= NOW() - INTERVAL '1 hour') as improvements_1h,

                -- Last 24 hours
                (SELECT COUNT(*) FROM knowledge_base WHERE created_at >= NOW() - INTERVAL '24 hours') as knowledge_24h,
                (SELECT COUNT(*) FROM agent_executions WHERE started_at >= NOW() - INTERVAL '24 hours') as executions_24h,
                (SELECT COUNT(*) FROM improvement_proposals WHERE proposed_at >= NOW() - INTERVAL '24 hours') as improvements_24h,

                -- Last 7 days
                (SELECT COUNT(*) FROM knowledge_base WHERE created_at >= NOW() - INTERVAL '7 days') as knowledge_7d,
                (SELECT COUNT(*) FROM agent_executions WHERE started_at >= NOW() - INTERVAL '7 days') as executions_7d,
                (SELECT COUNT(*) FROM improvement_proposals WHERE proposed_at >= NOW() - INTERVAL '7 days') as improvements_7d,

                -- Totals
                (SELECT COUNT(*) FROM knowledge_base) as knowledge_total,
                (SELECT COUNT(*) FROM agents WHERE status = 'active') as agents_active,
                (SELECT COUNT(*) FROM improvement_proposals) as improvements_total
        """
        )
        stats = cur.fetchone()

        # Get current emotional state
        cur.execute(
            """
            SELECT current_mood as mood, mood_intensity as energy,
                   stress_level as confidence, timestamp
            FROM agent_emotional_state
            ORDER BY timestamp DESC
            LIMIT 1
        """
        )
        emotional = cur.fetchone()

        # LLM health monitoring RETIRED (#4535, 2026-06-28): the llm_connections
        # table is frozen (writer ai_bridge/llm_monitor.py was never scheduled), so
        # the old counts were ~4 months stale. Return a deprecated marker instead of
        # querying the dead table. Live model state: Ollama lifecycle telemetry (#1898)
        # + Token Economy. Shape preserved (online/offline/degraded/total) for callers.
        llm_health = {
            "online": 0,
            "offline": 0,
            "degraded": 0,
            "total": 0,
            "deprecated": True,
            "note": "llm_connections monitoring retired #4535",
        }

        # Knowledge type breakdown
        cur.execute(
            """
            SELECT knowledge_type, COUNT(*) as count
            FROM knowledge_base GROUP BY knowledge_type ORDER BY count DESC
        """
        )
        kb_breakdown = [dict(r) for r in cur.fetchall()]

        # Embedding coverage (use actual embedding column, not has_embedding flag)
        cur.execute(
            """
            SELECT COUNT(*) as total,
                   COALESCE(SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END), 0) as with_embeddings
            FROM knowledge_base
        """
        )
        embed_row = cur.fetchone()

        # GitHub summary
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM github_repositories) as github_repos,
                (SELECT COUNT(*) FROM knowledge_base WHERE knowledge_type = 'github_file') as github_files,
                (SELECT COALESCE(SUM(CASE WHEN is_code THEN 1 ELSE 0 END), 0) FROM knowledge_base WHERE knowledge_type = 'github_file') as github_code,
                (SELECT COALESCE(SUM(CASE WHEN is_documentation THEN 1 ELSE 0 END), 0) FROM knowledge_base WHERE knowledge_type = 'github_file') as github_docs
        """
        )
        github_row = cur.fetchone()

        # Conversations & memories
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM ai_conversations) as conversations,
                (SELECT COUNT(*) FROM long_term_memory) as memories,
                (SELECT COUNT(*) FROM conversation_sessions) as claude_sessions,
                (SELECT COUNT(*) FROM improvement_conversations) as improvement_conversations,
                (SELECT COUNT(*) FROM knowledge_base WHERE source_type = 'conversation_log') as ingested_logs
        """
        )
        conv_row = cur.fetchone()

        # Knowledge growth (7 days) from knowledge_base
        cur.execute(
            """
            SELECT DATE(created_at) as date, COUNT(*) as count
            FROM knowledge_base
            WHERE created_at >= NOW() - INTERVAL '7 days'
            GROUP BY DATE(created_at) ORDER BY date
        """
        )
        kb_growth = [{"date": str(r["date"]), "count": r["count"]} for r in cur.fetchall()]

        # Combined knowledge growth (7 days, all sources) for Overview stacked chart
        cur.execute(
            """
            SELECT d.date::date as date,
                COALESCE(kb.cnt, 0) as knowledge_base,
                COALESCE(ltm.cnt, 0) as memories,
                COALESCE(tri.cnt, 0) as triage,
                COALESCE(bp.cnt, 0) as blueprints
            FROM generate_series(NOW() - INTERVAL '7 days', NOW(), '1 day') d(date)
            LEFT JOIN (SELECT DATE(created_at) dt, COUNT(*) cnt FROM knowledge_base WHERE created_at >= NOW() - INTERVAL '7 days' GROUP BY dt) kb ON d.date::date = kb.dt
            LEFT JOIN (SELECT DATE(created_at) dt, COUNT(*) cnt FROM long_term_memory WHERE created_at >= NOW() - INTERVAL '7 days' GROUP BY dt) ltm ON d.date::date = ltm.dt
            LEFT JOIN (SELECT DATE(created_at) dt, COUNT(*) cnt FROM triage_extractions WHERE created_at >= NOW() - INTERVAL '7 days' GROUP BY dt) tri ON d.date::date = tri.dt
            LEFT JOIN (SELECT DATE(created_at) dt, COUNT(*) cnt FROM blueprint_tasks WHERE created_at >= NOW() - INTERVAL '7 days' GROUP BY dt) bp ON d.date::date = bp.dt
            ORDER BY d.date
        """
        )
        combined_growth_7d = []
        for r in cur.fetchall():
            row = dict(r)
            row["date"] = str(row["date"])
            row["total"] = row["knowledge_base"] + row["memories"] + row["triage"] + row["blueprints"]
            combined_growth_7d.append(row)

        # Full knowledge footprint — all knowledge-bearing tables
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM long_term_memory) as ltm,
                (SELECT COUNT(*) FROM archie_codebase_knowledge) as codebase_knowledge,
                (SELECT COUNT(*) FROM triage_extractions) as triage,
                (SELECT COUNT(*) FROM blueprint_tasks) as blueprint_tasks,
                (SELECT COUNT(*) FROM blueprint_phases) as blueprint_phases,
                (SELECT COUNT(*) FROM emotional_memory) as emotional_memories,
                (SELECT COUNT(*) FROM project_decisions) as decisions,
                (SELECT COUNT(*) FROM roadmap_items) as roadmap_items,
                (SELECT COUNT(*) FROM archie_personality) as personality_traits,
                (SELECT COUNT(*) FROM archie_core_identity) as core_identity,
                (SELECT COUNT(*) FROM archie_scripts) as scripts,
                (SELECT COUNT(*) FROM archie_complexity_patterns) as complexity_patterns
        """
        )
        fp = dict(cur.fetchone())

        # Count platform modules from filesystem
        import os

        tools_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        try:
            module_count = len(
                [
                    d
                    for d in os.listdir(tools_dir)
                    if os.path.isdir(os.path.join(tools_dir, d)) and not d.startswith("_") and not d.startswith(".")
                ]
            )
        except Exception:
            module_count = 0

        kb_total = embed_row["total"] if embed_row else 0
        footprint_total = (
            kb_total
            + fp["ltm"]
            + fp["codebase_knowledge"]
            + fp["triage"]
            + fp["blueprint_tasks"]
            + fp["blueprint_phases"]
            + fp["emotional_memories"]
            + fp["decisions"]
            + fp["roadmap_items"]
            + conv_row["conversations"]
            + conv_row["claude_sessions"]
            + conv_row["improvement_conversations"]
        )

        footprint_sources = []
        source_map = [
            ("Knowledge Base", kb_total),
            ("Triage Insights", fp["triage"]),
            ("Blueprints", fp["blueprint_tasks"] + fp["blueprint_phases"]),
            ("Long-term Memories", fp["ltm"]),
            (
                "Conversations",
                conv_row["conversations"] + conv_row["claude_sessions"] + conv_row["improvement_conversations"],
            ),
            ("Codebase Knowledge", fp["codebase_knowledge"]),
            ("Emotional Memories", fp["emotional_memories"]),
            ("Decisions & Roadmap", fp["decisions"] + fp["roadmap_items"]),
        ]
        for name, count in source_map:
            if count > 0:
                footprint_sources.append({"name": name, "count": count})

        self_knowledge_total = (
            module_count
            + fp["codebase_knowledge"]
            + fp["personality_traits"]
            + fp["core_identity"]
            + fp["scripts"]
            + fp["complexity_patterns"]
        )

        # Search status metrics
        text_searchable = kb_total + fp["ltm"]
        semantic_searchable = embed_row["with_embeddings"] if embed_row else 0
        kb_unembedded = kb_total - semantic_searchable

        search_status = {
            "text_searchable": text_searchable,
            "semantic_searchable": semantic_searchable,
            "kb_total": kb_total,
            "kb_embedded": semantic_searchable,
            "kb_unembedded": kb_unembedded,
            "not_searchable": footprint_total - text_searchable,
        }

        overview = {
            "kb_total": kb_total,
            "kb_breakdown": [{"type": r["knowledge_type"], "count": r["count"]} for r in kb_breakdown],
            "embeddings_done": embed_row["with_embeddings"] if embed_row else 0,
            "footprint_total": footprint_total,
            "footprint_sources": footprint_sources,
            "github_repos": github_row["github_repos"] if github_row else 0,
            "github_files": github_row["github_files"] if github_row else 0,
            "github_code": github_row["github_code"] if github_row else 0,
            "github_docs": github_row["github_docs"] if github_row else 0,
            "conversations": conv_row["conversations"] if conv_row else 0,
            "memories": conv_row["memories"] if conv_row else 0,
            "claude_sessions": conv_row["claude_sessions"] if conv_row else 0,
            "improvement_conversations": (conv_row["improvement_conversations"] if conv_row else 0),
            "ingested_logs": conv_row["ingested_logs"] if conv_row else 0,
            "search_status": search_status,
            "kb_growth_7d": kb_growth,
            "combined_growth_7d": combined_growth_7d,
            "self_knowledge": {
                "total": self_knowledge_total,
                "modules": module_count,
                "codebase_entries": fp["codebase_knowledge"],
                "personality_traits": fp["personality_traits"],
                "core_identity": fp["core_identity"],
                "scripts": fp["scripts"],
                "complexity_patterns": fp["complexity_patterns"],
            },
        }
        return jsonify(
            {
                "success": True,
                "stats": dict(stats) if stats else {},
                "emotional_state": (
                    dict(emotional) if emotional else {"mood": "neutral", "energy": 0.8, "confidence": 0.8}
                ),
                "llm_health": dict(llm_health) if llm_health else {},
                "overview": overview,
            }
        )

    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# ============================================================================
# PHASE 9: LONG-TERM MEMORY API
# ============================================================================

# Import memory service
try:
    from .memory_service import (
        semantic_search,
        text_search,
        get_memory_content,
        create_collection,
        get_collections,
        add_to_collection,
        get_collection_items,
        create_association,
        get_related_memories,
        find_similar_memories,
        record_memory,
        reinforce_memory,
        apply_decay,
        get_memory_stats,
        store_embedding,
        log_memory_access,
    )

    MEMORY_SERVICE_AVAILABLE = True
except ImportError as e:
    MEMORY_SERVICE_AVAILABLE = False
    logger.warning("Memory service not available: %s", e)


@consciousness_bp.route("/api/memory/search", methods=["POST"])
@login_required
@admin_required
def memory_search():
    """Semantic search across all memories"""
    if not MEMORY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Memory service not available"}), 500

    data = request.get_json() or {}
    query = data.get("query", "")
    source_types = data.get("source_types")
    limit = data.get("limit", 10)
    min_similarity = data.get("min_similarity", 0.5)
    use_semantic = data.get("semantic", True)

    if not query:
        return jsonify({"success": False, "error": "Query is required"}), 400

    try:
        if use_semantic:
            results = semantic_search(query, source_types, limit, min_similarity)
        else:
            results = text_search(query, source_types, limit)

        return jsonify(
            {
                "success": True,
                "query": query,
                "results": results,
                "count": len(results),
                "search_type": "semantic" if use_semantic else "text",
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/memory/<memory_type>/<int:memory_id>")
@login_required
@admin_required
def get_memory(memory_type, memory_id):
    """Get a specific memory by type and ID"""
    VALID_MEMORY_TYPES = {
        "knowledge_base",
        "conversation_memory",
        "vault_note",
        "code_snippet",
        "improvement",
        "mistake_learned",
    }
    if memory_type not in VALID_MEMORY_TYPES:
        return jsonify({"success": False, "error": "Invalid memory type"}), 400

    if not MEMORY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Memory service not available"}), 500

    try:
        content = get_memory_content(memory_type, memory_id)
        if not content:
            return jsonify({"success": False, "error": "Memory not found"}), 404

        log_memory_access(memory_type, memory_id, "read", "user", current_user.id)
        reinforce_memory(memory_type, memory_id, 0.02)
        related = get_related_memories(memory_type, memory_id, limit=5)

        return jsonify({"success": True, "memory": content, "related": related})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/memory/record", methods=["POST"])
@login_required
@admin_required
def api_record_memory():
    """Record a new memory"""
    if not MEMORY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Memory service not available"}), 500

    data = request.get_json() or {}
    content = data.get("content", "")
    memory_type = data.get("memory_type", "observation")
    category = data.get("category")
    importance = data.get("importance", 0.5)
    tags = data.get("tags", [])
    agent_id = data.get("agent_id")
    source_module = data.get("source_module", "consciousness")

    if not content:
        return jsonify({"success": False, "error": "Content is required"}), 400

    try:
        memory_id = record_memory(
            content=content,
            memory_type=memory_type,
            category=category,
            importance=importance,
            tags=tags,
            user_id=current_user.id if not agent_id else None,
            agent_id=agent_id,
            source_module=source_module,
        )

        if memory_id:
            return jsonify(
                {
                    "success": True,
                    "memory_id": memory_id,
                    "source": "agent_memory" if agent_id else "long_term_memory",
                }
            )
        return jsonify({"success": False, "error": "Failed to record"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/save-conversation", methods=["POST"])
@login_required
@admin_required
def save_conversation():
    """
    Save current conversation to consciousness (manual trigger from ARCHIE Chat)
    Stores in knowledge_base with type='conversation_memory' and generates embedding
    """
    data = request.get_json() or {}
    conversation_id = data.get("conversation_id")
    messages = data.get("messages", [])
    source = data.get("source", "archie_chat_manual")

    if not messages or len(messages) == 0:
        return jsonify({"success": False, "error": "No messages provided"}), 400

    conn = None

    cur = None

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Extract title from first user message
        title = "Conversation"
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")[:100]
                title = content.split("\n")[0][:80] if content else "Conversation"
                break

        # Format conversation for storage
        formatted_content = []
        for msg in messages:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")
            formatted_content.append(f"**{role}:** {content}")
        full_content = "\n\n".join(formatted_content)

        # Extract tags from content
        tags = ["conversation", "archie_chat"]
        if source:
            tags.append(source.replace("_", "-"))

        # Store in knowledge_base
        cur.execute(
            """
            INSERT INTO knowledge_base (
                knowledge_type, title, content, category, tags,
                importance_score, source_type, metadata, created_at
            ) VALUES (
                'conversation_memory', %s, %s, 'conversation', %s,
                0.85, %s, %s, NOW()
            )
            RETURNING id
        """,
            (
                title,
                full_content,
                tags,
                source,
                json.dumps(
                    {
                        "conversation_id": conversation_id,
                        "message_count": len(messages),
                        "saved_by": current_user.username,
                        "saved_at": datetime.now().isoformat(),
                    }
                ),
            ),
        )

        memory_id = cur.fetchone()["id"]
        conn.commit()

        # Try to generate embedding for semantic search
        try:

            store_embedding("knowledge_base", memory_id, full_content)
            # Mark as having embedding
            cur.execute(
                """
                UPDATE knowledge_base SET has_embedding = TRUE, embedding_generated_at = NOW()
                WHERE id = %s
            """,
                (memory_id,),
            )
            conn.commit()
        except Exception as embed_err:
            logger.debug("Embedding generation failed (non-critical): %s", embed_err)

        return jsonify(
            {
                "success": True,
                "memory_id": memory_id,
                "title": title,
                "message_count": len(messages),
            }
        )

    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        if conn:
            conn.close()


# GitHub routes (auth, indexing, repositories, search, dependencies)
# moved to github_routes.py
@consciousness_bp.route("/api/chat-volume", methods=["GET"])
@login_required
@admin_required
def get_chat_volume():
    """Get chat conversation volume per day for last 30 days"""
    conn = None
    cur = None
    try:
        days = request.args.get("days", 30, type=int)
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT DATE(created_at) as date, COUNT(*) as count
            FROM ai_conversations
            WHERE created_at >= NOW() - (%s * INTERVAL '1 day')
            GROUP BY DATE(created_at)
            ORDER BY date ASC
        """,
            (days,),
        )
        volume = cur.fetchall()
        return jsonify({"success": True, "volume": [dict(v) for v in volume]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/collections")
@login_required
@admin_required
def list_collections():
    """List memory collections"""
    if not MEMORY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Memory service not available"}), 500

    try:
        collections = get_collections(user_id=current_user.id)
        return jsonify({"success": True, "collections": collections, "count": len(collections)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/collections", methods=["POST"])
@login_required
@admin_required
def api_create_collection():
    """Create a new memory collection"""
    if not MEMORY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Memory service not available"}), 500

    data = request.get_json() or {}
    name = data.get("name", "")

    if not name:
        return jsonify({"success": False, "error": "Name is required"}), 400

    try:
        collection_id = create_collection(
            name=name,
            description=data.get("description"),
            user_id=current_user.id,
            collection_type=data.get("type", "manual"),
            icon=data.get("icon"),
            color=data.get("color"),
        )
        if collection_id:
            return jsonify({"success": True, "collection_id": collection_id})
        return jsonify({"success": False, "error": "Failed"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/collections/<int:collection_id>")
@login_required
@admin_required
def get_collection(collection_id):
    """Get collection with items"""
    if not MEMORY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Memory service not available"}), 500

    try:
        items = get_collection_items(collection_id)
        return jsonify({"success": True, "items": items, "count": len(items)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/collections/<int:collection_id>/add", methods=["POST"])
@login_required
@admin_required
def add_to_collection_api(collection_id):
    """Add a memory to a collection"""
    if not MEMORY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Memory service not available"}), 500

    data = request.get_json() or {}
    memory_type = data.get("memory_type")
    memory_id = data.get("memory_id")

    if not memory_type or not memory_id:
        return (
            jsonify({"success": False, "error": "memory_type and memory_id required"}),
            400,
        )

    try:
        success = add_to_collection(collection_id, memory_type, memory_id, data.get("notes"), current_user.id)
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/memory/<memory_type>/<int:memory_id>/related")
@login_required
@admin_required
def get_related(memory_type, memory_id):
    """Get related memories"""
    if not MEMORY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Memory service not available"}), 500

    try:
        related = get_related_memories(memory_type, memory_id, request.args.get("limit", 10, type=int))
        return jsonify({"success": True, "related": related})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/memory/stats")
@login_required
@admin_required
def memory_stats():
    """Get memory system statistics"""
    if not MEMORY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Memory service not available"}), 500

    try:
        stats = get_memory_stats()
        return jsonify({"success": True, "stats": stats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/memory/decay", methods=["POST"])
@login_required
@admin_required
def run_decay():
    """Manually trigger memory decay"""
    if not MEMORY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Memory service not available"}), 500

    try:
        count = apply_decay()
        return jsonify({"success": True, "memories_decayed": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/memory/<memory_type>/<int:memory_id>/reinforce", methods=["POST"])
@login_required
@admin_required
def reinforce_api(memory_type, memory_id):
    """Reinforce a memory (boost importance)"""
    if not MEMORY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Memory service not available"}), 500

    data = request.get_json() or {}
    try:
        new_score = reinforce_memory(memory_type, memory_id, data.get("boost", 0.05))
        if new_score:
            return jsonify({"success": True, "new_importance": new_score})
        return jsonify({"success": False}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# PHASE 8: MEMORY MAINTENANCE & PREFERENCES
# =============================================================================


@consciousness_bp.route("/api/memory/maintenance", methods=["POST"])
@login_required
@admin_required
def run_memory_maintenance():
    """Run full memory maintenance (decay + cleanup)"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Run the maintenance function
        cur.execute("SELECT * FROM run_memory_maintenance()")
        results = [dict(r) for r in cur.fetchall()]

        conn.commit()
        return jsonify(
            {
                "success": True,
                "results": results,
                "message": "Memory maintenance completed",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/memory/preferences", methods=["GET"])
@login_required
def get_preferences():
    """Get user memory preferences"""
    conn = None
    cur = None
    conn = None
    cur = None
    try:
        user_id = current_user.id if hasattr(current_user, "id") else 1
        category = request.args.get("category")
        min_confidence = float(request.args.get("min_confidence", 0.5))

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            "SELECT * FROM get_user_preferences(%s, %s, %s)",
            (user_id, category, min_confidence),
        )
        preferences = [dict(p) for p in cur.fetchall()]
        return jsonify({"success": True, "data": preferences, "count": len(preferences)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/memory/preferences", methods=["POST"])
@login_required
def learn_preference():
    """Learn a new preference"""
    conn = None
    cur = None
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        user_id = current_user.id if hasattr(current_user, "id") else 1
        category = data.get("category")
        key = data.get("key") or data.get("preference_key")
        value = data.get("value") or data.get("preference_value")
        confidence = float(data.get("confidence", 0.6))
        context = data.get("context")

        if not category or not key or not value:
            return (
                jsonify({"success": False, "error": "category, key, and value required"}),
                400,
            )

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT learn_preference(%s, %s, %s, %s, %s, %s)",
            (
                user_id,
                category,
                key,
                value,
                confidence,
                json.dumps(context) if context else None,
            ),
        )
        pref_id = cur.fetchone()[0]

        conn.commit()
        return jsonify(
            {
                "success": True,
                "preference_id": pref_id,
                "message": f"Preference learned: {category}/{key}",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/memory/system-stats", methods=["GET"])
@login_required
def get_memory_system_stats():
    """Get comprehensive memory system statistics"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get stats from view
        cur.execute("SELECT * FROM v_memory_system_stats")
        stats = cur.fetchone()

        # Get scheduled tasks status
        cur.execute(
            """
            SELECT task_name, task_type, is_enabled, last_run_at, last_run_status
            FROM memory_scheduled_tasks
            ORDER BY task_name
        """
        )
        tasks = [dict(t) for t in cur.fetchall()]

        # Get memory type breakdown
        cur.execute(
            """
            SELECT memory_type, COUNT(*) as count, AVG(importance_score)::DECIMAL(3,2) as avg_importance
            FROM long_term_memory
            GROUP BY memory_type
            ORDER BY count DESC
        """
        )
        by_type = [dict(t) for t in cur.fetchall()]

        # Get recent extractions
        cur.execute(
            """
            SELECT source_type, memories_created, preferences_learned, processed_at, status
            FROM memory_extraction_log
            ORDER BY processed_at DESC
            LIMIT 10
        """
        )
        recent_extractions = [dict(e) for e in cur.fetchall()]
        return jsonify(
            {
                "success": True,
                "data": {
                    "overview": dict(stats) if stats else {},
                    "scheduled_tasks": tasks,
                    "by_type": by_type,
                    "recent_extractions": recent_extractions,
                },
            }
        )
    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/memory/extract", methods=["POST"])
@login_required
@admin_required
def extract_memories():
    """Extract memories from text content"""
    conn = None
    cur = None
    try:
        data = request.get_json()
        if not data or not data.get("content"):
            return jsonify({"success": False, "error": "content required"}), 400

        content = data["content"]
        user_id = data.get("user_id", current_user.id if hasattr(current_user, "id") else 1)
        source_type = data.get("source_type", "manual")
        importance = float(data.get("importance", 0.7))

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT extract_memories_from_text(%s, %s, %s, %s)",
            (content, user_id, source_type, importance),
        )
        memory_id = cur.fetchone()[0]

        conn.commit()
        return jsonify(
            {
                "success": True,
                "memory_id": memory_id,
                "message": "Memory extracted and stored",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# ============================================================================
# SCHEDULER ENDPOINTS
# ============================================================================


@consciousness_bp.route("/scheduler/status", methods=["GET"])
@login_required
def scheduler_status():
    """Get consciousness scheduler status and recent task runs"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from consciousness_scheduler import get_scheduler_status

        status = get_scheduler_status()

        # Add Flask scheduler info if available
        from flask import current_app

        scheduler = current_app.config.get("CONSCIOUSNESS_SCHEDULER")
        if scheduler:
            jobs = []
            for job in scheduler.get_jobs():
                jobs.append(
                    {
                        "id": job.id,
                        "name": job.name,
                        "next_run": (job.next_run_time.isoformat() if job.next_run_time else None),
                        "trigger": str(job.trigger),
                    }
                )
            status["scheduled_jobs"] = jobs
            status["scheduler_running"] = scheduler.running
        else:
            # Path C: scheduler runs in sidecar container — read heartbeat.
            from services import scheduler_health

            hs = scheduler_health.read_status()
            status["scheduler_running"] = hs["scheduler_running"]
            status["scheduled_jobs"] = hs["jobs"]

        return jsonify(status)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/scheduler/run-now", methods=["POST"])
@login_required
@admin_required
def run_scheduler_task_now():
    """Manually trigger a scheduled task (admin only)"""
    try:
        data = request.get_json() or {}
        task_name = data.get("task_name")

        if not task_name:
            return jsonify({"success": False, "error": "task_name required"}), 400

        valid_tasks = [
            "hourly_conversation_consolidation",
            "improvement_detection",
            "daily_self_reflection",
            "weekly_memory_consolidation",
        ]

        if task_name not in valid_tasks:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Invalid task. Valid tasks: {valid_tasks}",
                    }
                ),
                400,
            )

        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from consciousness_scheduler import run_task_now

        result = run_task_now(task_name)

        return jsonify({"success": True, "task_name": task_name, "result": result})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/user-time", methods=["GET"])
@login_required
def get_user_time():
    """Get cumulative time stats for users"""
    conn = None
    cur = None
    conn = None
    cur = None
    try:
        user_id = request.args.get("user_id")
        if user_id:
            user_id = int(user_id)
        else:
            user_id = current_user.id if hasattr(current_user, "id") else None

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if user_id:
            # Get specific user stats
            cur.execute(
                """
                SELECT * FROM v_user_cumulative_time WHERE user_id = %s
            """,
                (user_id,),
            )
            user_stats = cur.fetchone()

            # Get recent sessions
            cur.execute(
                """
                SELECT session_date, total_minutes, message_count
                FROM user_session_time
                WHERE user_id = %s
                ORDER BY session_date DESC
                LIMIT 30
            """,
                (user_id,),
            )
            recent_sessions = cur.fetchall()
        else:
            # Get all users stats (admin view)
            cur.execute(
                """
                SELECT v.*, u.username
                FROM v_user_cumulative_time v
                JOIN users u ON v.user_id = u.id
                ORDER BY lifetime_minutes DESC
            """
            )
            user_stats = cur.fetchall()
            recent_sessions = []
        return jsonify(
            {
                "success": True,
                "user_stats": (
                    user_stats if isinstance(user_stats, list) else dict(user_stats) if user_stats else None
                ),
                "recent_sessions": [dict(s) for s in recent_sessions],
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# ============================================================================
# PHASE 62: BRIDGE ANALYTICS, AGENT SKILLS, SELF-IMPROVEMENT
# ============================================================================


@consciousness_bp.route("/bridge-analytics", methods=["GET"])
@login_required
@admin_required
def get_bridge_analytics():
    """Get bridge interaction analytics for dashboard"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Overall stats from task_execution_log (real dispatch data)
        cur.execute(
            """
            SELECT
                COUNT(*) as total_calls,
                COUNT(*) FILTER (WHERE success = TRUE) as successful_calls,
                COUNT(*) FILTER (WHERE request_metadata->>'escalation' IS NOT NULL) as claude_escalations,
                COALESCE(SUM(tokens_used), 0) as total_tokens,
                COALESCE(SUM(cost), 0)::numeric::float as total_cost,
                ROUND(AVG(duration_ms)::numeric, 0)::float as avg_execution_ms
            FROM task_execution_log
            WHERE created_at > NOW() - INTERVAL '30 days'
        """
        )
        stats = cur.fetchone() or {}

        # Escalation patterns - what's being escalated to cloud
        cur.execute(
            """
            SELECT
                COALESCE(task_type, 'unknown') as intent_type,
                COALESCE(module_source, 'unknown') as module_name,
                COUNT(*) as escalation_count,
                ROUND(AVG(duration_ms)::numeric, 0)::float as avg_time_ms,
                COALESCE(SUM(cost), 0)::numeric::float as total_cost
            FROM task_execution_log
            WHERE request_metadata->>'escalation' IS NOT NULL
              AND created_at > NOW() - INTERVAL '30 days'
            GROUP BY task_type, module_source
            ORDER BY escalation_count DESC
            LIMIT 10
        """
        )
        escalation_patterns = cur.fetchall()

        # Recent bridge calls
        cur.execute(
            """
            SELECT
                id,
                module_source as module_name,
                task_type as intent_type,
                model_used,
                tokens_used,
                duration_ms as execution_time_ms,
                success,
                (request_metadata->>'escalation' IS NOT NULL) as escalated_to_claude,
                LEFT(task_description, 100) as prompt_preview,
                TO_CHAR(created_at, 'YYYY-MM-DD"T"HH24:MI:SS') as created_at
            FROM task_execution_log
            ORDER BY created_at DESC
            LIMIT 20
        """
        )
        recent_calls = cur.fetchall()

        # Daily trend (last 7 days)
        cur.execute(
            """
            SELECT
                TO_CHAR(DATE(created_at), 'YYYY-MM-DD') as date,
                COUNT(*) as calls,
                COUNT(*) FILTER (WHERE request_metadata->>'escalation' IS NOT NULL) as escalations
            FROM task_execution_log
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY DATE(created_at)
            ORDER BY date
        """
        )
        daily_trend = cur.fetchall()
        return jsonify(
            {
                "success": True,
                "stats": dict(stats) if stats else {},
                "escalation_patterns": [dict(p) for p in escalation_patterns],
                "recent_calls": [dict(c) for c in recent_calls],
                "daily_trend": [dict(d) for d in daily_trend],
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/agent-skills", methods=["GET"])
@login_required
@admin_required
def get_agent_skills():
    """Get agent skills and learning data for dashboard"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Aggregate stats
        cur.execute(
            """
            SELECT
                COUNT(DISTINCT agent_id) as agents_with_skills,
                COUNT(*) as total_skills_learned,
                COUNT(*) FILTER (WHERE confidence >= 0.8) as mastered_skills,
                ROUND(AVG(confidence)::numeric, 2) as avg_confidence
            FROM agent_learning_log
        """
        )
        stats = cur.fetchone() or {}

        # Agent skill summary using the view
        cur.execute(
            """
            SELECT * FROM v_agent_skills
            ORDER BY total_skills_learned DESC, avg_confidence DESC
        """
        )
        agent_summary = cur.fetchall()

        # All skills with agent info
        cur.execute(
            """
            SELECT
                al.id,
                al.agent_id,
                a.name as agent_name,
                a.title as agent_role,
                al.skill_name,
                al.skill_category,
                al.confidence,
                al.successful_uses,
                al.failed_uses,
                al.learned_from,
                al.last_used_at,
                al.created_at
            FROM agent_learning_log al
            JOIN agents a ON al.agent_id = a.id
            ORDER BY al.confidence DESC, al.successful_uses DESC
            LIMIT 50
        """
        )
        skills = cur.fetchall()

        # Skills by category
        cur.execute(
            """
            SELECT
                COALESCE(skill_category, 'uncategorized') as category,
                COUNT(*) as skill_count,
                COUNT(DISTINCT agent_id) as agents_count,
                ROUND(AVG(confidence)::numeric, 2) as avg_confidence
            FROM agent_learning_log
            GROUP BY skill_category
            ORDER BY skill_count DESC
        """
        )
        by_category = cur.fetchall()
        return jsonify(
            {
                "success": True,
                "stats": dict(stats) if stats else {},
                "agent_summary": [dict(a) for a in agent_summary],
                "skills": [dict(s) for s in skills],
                "by_category": [dict(c) for c in by_category],
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/improvements-proposals", methods=["GET"])
@login_required
@admin_required
def get_improvement_proposals():
    """Get improvement proposals for approval workflow"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get proposals from improvement_proposals table
        # Note: Table uses 'proposed' status instead of 'pending'
        cur.execute(
            """
            SELECT
                ip.id,
                ip.title,
                ip.description,
                ip.category as proposal_type,
                ip.priority,
                ip.status,
                ip.proposed_by,
                ip.proposed_at as created_at,
                ip.approved_by,
                ip.approved_at,
                ip.risk_level,
                ip.complexity,
                ip.code_changes,
                ip.notes,
                ip.metadata,
                u.username as created_by_name,
                COALESCE(array_length(string_to_array(COALESCE(ip.code_changes, ''), E'\\n'), 1), 0) / 20 as files_affected
            FROM improvement_proposals ip
            LEFT JOIN users u ON ip.proposed_by = u.id
            ORDER BY
                CASE
                    WHEN ip.status = 'proposed' THEN 0
                    WHEN ip.status = 'pending' THEN 0
                    ELSE 1
                END,
                ip.proposed_at DESC
            LIMIT 50
        """
        )
        proposals = cur.fetchall()

        # Stats - handle both 'proposed' and 'pending' statuses
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status IN ('pending', 'proposed')) as pending,
                COUNT(*) FILTER (WHERE status = 'approved') as approved,
                COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
                COUNT(*) FILTER (WHERE status = 'testing') as testing,
                COUNT(*) FILTER (WHERE status = 'deployed') as deployed,
                COUNT(*) FILTER (WHERE status = 'implemented') as implemented
            FROM improvement_proposals
        """
        )
        stats = cur.fetchone() or {}
        # Map 'proposed' status to 'pending' for frontend consistency
        formatted_proposals = []
        for p in proposals:
            proposal = dict(p)
            if proposal.get("status") == "proposed":
                proposal["status"] = "pending"
            formatted_proposals.append(proposal)

        return jsonify(
            {
                "success": True,
                "proposals": formatted_proposals,
                "stats": dict(stats) if stats else {},
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/improvements/<int:proposal_id>/approve", methods=["POST"])
@login_required
@admin_required
def approve_proposal(proposal_id):
    """Approve an improvement proposal"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        note = (request.get_json() or {}).get("note", "Approved by admin")

        # Update proposal status (using actual table columns)
        cur.execute(
            """
            UPDATE improvement_proposals
            SET status = 'approved',
                approved_by = %s,
                approved_at = NOW(),
                reviewed_at = NOW(),
                notes = COALESCE(notes, '') || E'\\n[APPROVED] ' || %s,
                metadata = COALESCE(metadata, '{}'::jsonb) ||
                    jsonb_build_object('approval_note', %s, 'approved_by_user_id', %s)
            WHERE id = %s
            RETURNING *
        """,
            (current_user.id, note, note, current_user.id, proposal_id),
        )

        proposal = cur.fetchone()
        conn.commit()
        if proposal:
            audit_log(
                "PROPOSAL_APPROVED",
                {"proposal_id": proposal_id, "user_id": current_user.id},
            )
            return jsonify({"success": True, "proposal": dict(proposal)})
        else:
            return jsonify({"success": False, "error": "Proposal not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/improvements/<int:proposal_id>/reject", methods=["POST"])
@login_required
@admin_required
def reject_proposal(proposal_id):
    """Reject an improvement proposal"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        reason = (request.get_json() or {}).get("reason", "Rejected by admin")

        # Update proposal status (using actual table columns - no rejection_reason column)
        cur.execute(
            """
            UPDATE improvement_proposals
            SET status = 'rejected',
                reviewed_at = NOW(),
                notes = COALESCE(notes, '') || E'\\n[REJECTED] ' || %s,
                metadata = COALESCE(metadata, '{}'::jsonb) ||
                    jsonb_build_object('rejection_reason', %s, 'rejected_by_user_id', %s, 'rejected_at', NOW())
            WHERE id = %s
            RETURNING *
        """,
            (reason, reason, current_user.id, proposal_id),
        )

        proposal = cur.fetchone()
        conn.commit()
        if proposal:
            audit_log(
                "PROPOSAL_REJECTED",
                {
                    "proposal_id": proposal_id,
                    "user_id": current_user.id,
                    "reason": reason,
                },
            )
            return jsonify({"success": True, "proposal": dict(proposal)})
        else:
            return jsonify({"success": False, "error": "Proposal not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/improvements/<int:proposal_id>/test", methods=["POST"])
@login_required
@admin_required
def test_proposal_in_sandbox(proposal_id):
    """Queue a proposal for sandbox testing"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Update proposal status to testing (no testing_started_at column, use metadata)
        cur.execute(
            """
            UPDATE improvement_proposals
            SET status = 'testing',
                metadata = COALESCE(metadata, '{}'::jsonb) ||
                    jsonb_build_object('tested_by', %s, 'testing_started_at', NOW())
            WHERE id = %s
            RETURNING *
        """,
            (current_user.id, proposal_id),
        )

        proposal = cur.fetchone()
        conn.commit()
        if proposal:
            audit_log(
                "PROPOSAL_TESTING",
                {"proposal_id": proposal_id, "user_id": current_user.id},
            )
            # TODO: Trigger actual sandbox test here
            return jsonify(
                {
                    "success": True,
                    "proposal": dict(proposal),
                    "message": "Proposal queued for sandbox testing",
                }
            )
        else:
            return jsonify({"success": False, "error": "Proposal not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# ============================================================================
# PER-AGENT MEMORY MANAGEMENT (Phase 67: C.R.E.E.D.-Compliant)
# ============================================================================


@consciousness_bp.route("/api/agent-memory", methods=["GET"])
@login_required
@admin_required
def list_agent_memories():
    """
    List memories for a specific agent or all agents.
    Supports filtering by agent_id, memory_type, and includes soft-deleted option.
    """
    agent_id = request.args.get("agent_id", type=int)
    memory_type = request.args.get("memory_type")
    include_deleted = request.args.get("include_deleted", "false").lower() == "true"
    limit = min(request.args.get("limit", 50, type=int), 200)
    offset = request.args.get("offset", 0, type=int)

    conn = None

    cur = None

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build query with filters
        where_clauses = []
        params = []

        if agent_id:
            where_clauses.append("am.agent_id = %s")
            params.append(agent_id)

        if memory_type:
            where_clauses.append("am.memory_type = %s")
            params.append(memory_type)

        if not include_deleted:
            where_clauses.append("am.is_deleted = FALSE")

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        cur.execute(
            f"""
            SELECT am.*, a.name as agent_name, a.title as agent_role,
                   u.username as deleted_by_username
            FROM agent_memory am
            LEFT JOIN agents a ON am.agent_id = a.id
            LEFT JOIN users u ON am.deleted_by = u.id
            {where_sql}
            ORDER BY am.created_at DESC
            LIMIT %s OFFSET %s
        """,
            params + [limit, offset],
        )

        memories = cur.fetchall()

        # Get total count
        cur.execute(
            f"""
            SELECT COUNT(*) as total
            FROM agent_memory am
            {where_sql}
        """,
            params,
        )
        total = cur.fetchone()["total"]
        return jsonify(
            {
                "success": True,
                "memories": [dict(m) for m in memories],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/agent-memory/<int:memory_id>", methods=["GET"])
@login_required
@admin_required
def get_agent_memory(memory_id):
    """Get a specific agent memory by ID"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT am.*, a.name as agent_name, a.title as agent_role,
                   u.username as deleted_by_username
            FROM agent_memory am
            LEFT JOIN agents a ON am.agent_id = a.id
            LEFT JOIN users u ON am.deleted_by = u.id
            WHERE am.id = %s
        """,
            (memory_id,),
        )

        memory = cur.fetchone()

        # Update access tracking
        if memory and not memory.get("is_deleted"):
            cur.execute(
                """
                UPDATE agent_memory
                SET last_accessed = NOW(), access_count = access_count + 1
                WHERE id = %s
            """,
                (memory_id,),
            )
            conn.commit()
        if memory:
            return jsonify({"success": True, "memory": dict(memory)})
        else:
            return jsonify({"success": False, "error": "Memory not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/agent-memory/<int:memory_id>", methods=["PUT"])
@login_required
@admin_required
def update_agent_memory(memory_id):
    """Update an agent memory"""
    data = request.get_json() or {}

    conn = None

    cur = None

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build update query dynamically
        update_fields = []
        params = []

        if "content" in data:
            update_fields.append("content = %s")
            params.append(data["content"])

        if "importance_score" in data:
            update_fields.append("importance_score = %s")
            params.append(data["importance_score"])

        if "emotional_valence" in data:
            update_fields.append("emotional_valence = %s")
            params.append(data["emotional_valence"])

        if "context" in data:
            update_fields.append("context = %s")
            params.append(json.dumps(data["context"]))

        if not update_fields:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        params.append(memory_id)

        cur.execute(
            f"""
            UPDATE agent_memory
            SET {', '.join(update_fields)}
            WHERE id = %s AND is_deleted = FALSE
            RETURNING *
        """,
            params,
        )

        memory = cur.fetchone()
        conn.commit()

        # Log the update
        if memory:
            audit_log(
                "AGENT_MEMORY_UPDATED",
                {
                    "memory_id": memory_id,
                    "agent_id": memory.get("agent_id"),
                    "updated_by": current_user.id,
                },
            )
        if memory:
            return jsonify({"success": True, "memory": dict(memory)})
        else:
            return (
                jsonify({"success": False, "error": "Memory not found or deleted"}),
                404,
            )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/agent-memory/<int:memory_id>/soft-delete", methods=["POST"])
@login_required
@admin_required
def soft_delete_agent_memory(memory_id):
    """
    Soft-delete an agent memory (C.R.E.E.D.-compliant).
    Memory is marked as deleted but remains in database for audit trail.
    """
    data = request.get_json() or {}
    reason = data.get("reason", "Admin deletion")

    conn = None

    cur = None

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Soft-delete with C.R.E.E.D. tracking
        cur.execute(
            """
            UPDATE agent_memory
            SET is_deleted = TRUE,
                deleted_at = NOW(),
                deleted_by = %s,
                deletion_reason = %s
            WHERE id = %s AND is_deleted = FALSE
            RETURNING id, agent_id, memory_type, content
        """,
            (current_user.id, reason, memory_id),
        )

        deleted = cur.fetchone()
        conn.commit()

        if deleted:
            # Log deletion for C.R.E.E.D. audit
            audit_log(
                "AGENT_MEMORY_SOFT_DELETED",
                {
                    "memory_id": memory_id,
                    "agent_id": deleted.get("agent_id"),
                    "memory_type": deleted.get("memory_type"),
                    "deleted_by": current_user.id,
                    "reason": reason,
                },
            )
            return jsonify(
                {
                    "success": True,
                    "message": "Memory soft-deleted (C.R.E.E.D.-compliant)",
                    "memory_id": memory_id,
                    "deleted_at": datetime.now().isoformat(),
                    "can_restore": True,
                }
            )
        else:
            return (
                jsonify({"success": False, "error": "Memory not found or already deleted"}),
                404,
            )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/agent-memory/<int:memory_id>/restore", methods=["POST"])
@login_required
@admin_required
def restore_agent_memory(memory_id):
    """
    Restore a soft-deleted agent memory (C.R.E.E.D.-compliant).
    Only admin can restore memories.
    """
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Restore soft-deleted memory
        cur.execute(
            """
            UPDATE agent_memory
            SET is_deleted = FALSE,
                deleted_at = NULL,
                deleted_by = NULL,
                deletion_reason = NULL
            WHERE id = %s AND is_deleted = TRUE
            RETURNING id, agent_id, memory_type
        """,
            (memory_id,),
        )

        restored = cur.fetchone()
        conn.commit()

        if restored:
            # Log restoration for C.R.E.E.D. audit
            audit_log(
                "AGENT_MEMORY_RESTORED",
                {
                    "memory_id": memory_id,
                    "agent_id": restored.get("agent_id"),
                    "restored_by": current_user.id,
                },
            )
            return jsonify(
                {
                    "success": True,
                    "message": "Memory restored successfully",
                    "memory_id": memory_id,
                }
            )
        else:
            return (
                jsonify({"success": False, "error": "Memory not found or not deleted"}),
                404,
            )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/agent-memory/<int:memory_id>/reinforce", methods=["POST"])
@login_required
@admin_required
def reinforce_agent_memory(memory_id):
    """
    Reinforce an agent memory (increase importance and decay immunity).
    Used when a memory proves useful.
    """
    data = request.get_json() or {}
    importance_boost = min(data.get("importance_boost", 0.1), 0.3)  # Max 0.3 boost

    conn = None

    cur = None

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE agent_memory
            SET reinforcement_count = reinforcement_count + 1,
                importance_score = LEAST(importance_score + %s, 1.0),
                decay_immunity = TRUE,
                last_accessed = NOW()
            WHERE id = %s AND is_deleted = FALSE
            RETURNING *
        """,
            (importance_boost, memory_id),
        )

        memory = cur.fetchone()
        conn.commit()

        if memory:
            audit_log(
                "AGENT_MEMORY_REINFORCED",
                {
                    "memory_id": memory_id,
                    "agent_id": memory.get("agent_id"),
                    "new_importance": float(memory.get("importance_score", 0)),
                    "reinforcement_count": memory.get("reinforcement_count"),
                },
            )
        if memory:
            return jsonify(
                {
                    "success": True,
                    "memory": dict(memory),
                    "message": f"Memory reinforced (count: {memory.get('reinforcement_count')})",
                }
            )
        else:
            return (
                jsonify({"success": False, "error": "Memory not found or deleted"}),
                404,
            )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/agent-memory/stats", methods=["GET"])
@login_required
@admin_required
def agent_memory_stats():
    """Get statistics for agent memories"""
    agent_id = request.args.get("agent_id", type=int)

    conn = None

    cur = None

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if agent_id:
            # Stats for specific agent
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE is_deleted = FALSE) as total_memories,
                    COUNT(*) FILTER (WHERE is_deleted = TRUE) as deleted_memories,
                    COUNT(DISTINCT memory_type) as memory_types,
                    ROUND(AVG(importance_score) FILTER (WHERE is_deleted = FALSE)::numeric, 2) as avg_importance,
                    SUM(access_count) FILTER (WHERE is_deleted = FALSE) as total_accesses,
                    MAX(created_at) as latest_memory,
                    COUNT(*) FILTER (WHERE decay_immunity = TRUE AND is_deleted = FALSE) as immune_memories
                FROM agent_memory
                WHERE agent_id = %s
            """,
                (agent_id,),
            )
        else:
            # Global stats
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE is_deleted = FALSE) as total_memories,
                    COUNT(*) FILTER (WHERE is_deleted = TRUE) as deleted_memories,
                    COUNT(DISTINCT agent_id) as agents_with_memories,
                    COUNT(DISTINCT memory_type) as memory_types,
                    ROUND(AVG(importance_score) FILTER (WHERE is_deleted = FALSE)::numeric, 2) as avg_importance,
                    SUM(access_count) FILTER (WHERE is_deleted = FALSE) as total_accesses
                FROM agent_memory
            """
            )

        stats = cur.fetchone()

        # Get memory type breakdown
        where_clause = "WHERE agent_id = %s" if agent_id else ""
        params = [agent_id] if agent_id else []

        cur.execute(
            f"""
            SELECT memory_type, COUNT(*) as count,
                   ROUND(AVG(importance_score)::numeric, 2) as avg_importance
            FROM agent_memory
            {where_clause}
            GROUP BY memory_type
            ORDER BY count DESC
        """,
            params,
        )

        by_type = cur.fetchall()
        return jsonify(
            {
                "success": True,
                "stats": dict(stats) if stats else {},
                "by_type": [dict(t) for t in by_type],
                "agent_id": agent_id,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# ============================================================================
# CONVERSATION LOG INGESTION (Phase 81)
# ============================================================================


@consciousness_bp.route("/api/logs/status", methods=["GET"])
@login_required
@admin_required
def log_ingestion_status():
    """
    Get status of conversation log ingestion.

    Returns:
        - snapshots: Count of snapshot JSON files
        - transcripts: Count of transcript MD files
        - sessions: Count of unique sessions
        - ingested: Count of already ingested entries
    """
    try:
        from .log_ingestor import get_ingestion_status

        status = get_ingestion_status()
        return jsonify(status)
    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/logs/ingest", methods=["POST"])
@login_required
@admin_required
def log_ingestion_batch():
    """
    Batch ingest conversation logs into knowledge_base.

    Request body:
        - limit: Max files to process (default 50, max 500)
        - dry_run: If true, don't actually insert (default false)

    Returns:
        - processed: Number of files processed
        - created: Number of new knowledge entries
        - skipped: Number of already-ingested files
        - errors: List of errors encountered
    """
    try:
        data = request.get_json() or {}
        limit = min(data.get("limit", 50), 500)  # Cap at 500
        dry_run = data.get("dry_run", False)

        from .log_ingestor import batch_ingest_logs

        result = batch_ingest_logs(limit=limit, dry_run=dry_run)

        audit_log(
            "LOG_INGESTION",
            {
                "user_id": current_user.id,
                "limit": limit,
                "dry_run": dry_run,
                "processed": result.get("processed", 0),
                "created": result.get("created", 0),
            },
            success=result.get("success", False),
        )

        return jsonify(result)
    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# AI-TO-AI COLLABORATION (Phase 83 - Dual AI Chat)
# ============================================================================


@consciousness_bp.route("/api/collab/start", methods=["POST"])
@login_required
def start_collaboration():
    """
    Start a new AI-to-AI collaboration session.

    Request body:
        - topic: The question/topic for ARCHIE and Claude to discuss
        - max_turns: Maximum conversation turns (default 10, max 20)

    Returns:
        - session_id: UUID of the new session
        - status: Initial session status
    """
    try:
        import threading
        import asyncio
        from .collaboration_engine import get_collaboration_engine

        data = request.get_json() or {}
        topic = data.get("topic", "")
        max_turns = min(int(data.get("max_turns", 10)), 20)

        if not topic:
            return jsonify({"success": False, "error": "Topic required"}), 400

        engine = get_collaboration_engine()
        system_hint = data.get("system_hint", "")
        session = engine.start_session(topic, max_turns, user_id=current_user.id, system_hint=system_hint)

        # Run collaboration in background
        def run_async():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(engine.run_collaboration(session.id))
            finally:
                loop.close()

        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()

        audit_log(
            "COLLAB_START",
            {
                "user_id": current_user.id,
                "session_id": session.id,
                "topic": topic[:100],
                "max_turns": max_turns,
            },
            success=True,
        )

        return jsonify({"success": True, "session_id": session.id, "status": session.status.value})

    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/collab/status/<session_id>", methods=["GET"])
@login_required
def get_collaboration_status(session_id):
    """
    Get current status of a collaboration session.

    Returns full session data including all messages exchanged.
    """
    try:
        from .collaboration_engine import get_collaboration_engine

        engine = get_collaboration_engine()
        session = engine.get_session(session_id)

        if not session:
            return jsonify({"success": False, "error": "Session not found"}), 404

        return jsonify({"success": True, "session": session.to_dict()})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/collab/stream/<session_id>", methods=["GET"])
@login_required
def stream_collaboration(session_id):
    """
    SSE endpoint for real-time collaboration updates.

    Streams new messages as they arrive instead of polling.
    Client connects with EventSource and receives 'message' events.
    """
    from .collaboration_engine import get_collaboration_engine
    import time as _time
    import json as _json

    engine = get_collaboration_engine()

    def generate():
        last_msg_count = 0
        last_status = None
        timeout_counter = 0
        max_timeout = 600  # 10 minutes max

        while timeout_counter < max_timeout:
            session = engine.get_session(session_id)
            if not session:
                yield f"data: {_json.dumps({'type': 'error', 'error': 'Session not found'})}\n\n"
                break

            current_status = session.status.value
            current_msg_count = len(session.messages)

            # Send status update if changed
            if current_status != last_status:
                yield f"data: {_json.dumps({'type': 'status', 'status': current_status, 'turn': session.current_turn, 'max_turns': session.max_turns})}\n\n"
                last_status = current_status

            # Send new messages
            if current_msg_count > last_msg_count:
                for msg in session.messages[last_msg_count:]:
                    yield f"data: {_json.dumps({'type': 'message', 'role': msg.role, 'content': msg.content, 'turn': msg.turn, 'timestamp': msg.timestamp})}\n\n"
                last_msg_count = current_msg_count

            # End stream if session is done
            if current_status in ("completed", "stopped", "error"):
                yield f"data: {_json.dumps({'type': 'done', 'status': current_status})}\n\n"
                break

            _time.sleep(1)
            timeout_counter += 1

        # Final keepalive close
        yield f"data: {_json.dumps({'type': 'close'})}\n\n"

    from flask import Response

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@consciousness_bp.route("/api/collab/resume-session/<session_id>", methods=["POST"])
@login_required
def resume_collaboration_session(session_id):
    """
    Resume/reload a collaboration session from DB.

    Used when user navigates back to an in-progress or completed session.
    Returns full session data with all messages.
    """
    try:
        from .collaboration_engine import get_collaboration_engine

        engine = get_collaboration_engine()
        session = engine.get_session(session_id)

        if not session:
            return jsonify({"success": False, "error": "Session not found"}), 404

        return jsonify({"success": True, "session": session.to_dict()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/collab/pause/<session_id>", methods=["POST"])
@login_required
def pause_collaboration(session_id):
    """Pause a running collaboration session."""
    from .collaboration_engine import get_collaboration_engine

    engine = get_collaboration_engine()
    success = engine.pause_session(session_id)
    return jsonify({"success": success})


@consciousness_bp.route("/api/collab/resume/<session_id>", methods=["POST"])
@login_required
def resume_collaboration(session_id):
    """Resume a paused collaboration session."""
    from .collaboration_engine import get_collaboration_engine

    engine = get_collaboration_engine()
    success = engine.resume_session(session_id)
    return jsonify({"success": success})


@consciousness_bp.route("/api/collab/stop/<session_id>", methods=["POST"])
@login_required
def stop_collaboration(session_id):
    """Stop a collaboration session early."""
    from .collaboration_engine import get_collaboration_engine

    engine = get_collaboration_engine()
    success = engine.stop_session(session_id)

    if success:
        audit_log(
            "COLLAB_STOP",
            {"user_id": current_user.id, "session_id": session_id},
            success=True,
        )

    return jsonify({"success": success})


@consciousness_bp.route("/api/collab/interject/<session_id>", methods=["POST"])
@login_required
def add_interjection(session_id):
    """
    Add user message to ongoing collaboration.

    Allows user to interject during AI-to-AI discussion.
    """
    data = request.get_json() or {}
    message = data.get("message", "")

    if not message:
        return jsonify({"success": False, "error": "Message required"}), 400

    from .collaboration_engine import get_collaboration_engine

    engine = get_collaboration_engine()
    success = engine.add_interjection(session_id, message)
    return jsonify({"success": success})


@consciousness_bp.route("/api/collab/learnings", methods=["GET"])
@login_required
def get_collab_learnings():
    """
    Get learning statistics from AI collaborations.

    Returns:
        - total_learnings: Total knowledge cards from collaborations
        - learnings_last_week: Cards created in last 7 days
        - top_topics: Most common topics learned
        - recent_learnings: Latest 5 learnings
    """
    try:
        from .learning_extractor import get_learning_stats

        stats = get_learning_stats()
        return jsonify({"success": True, **stats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/collab/history", methods=["GET"])
@login_required
def get_collab_history():
    """Get history of collaboration sessions."""
    try:
        from .learning_extractor import get_collaboration_history

        sessions = get_collaboration_history()
        return jsonify({"success": True, "sessions": sessions})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/collab/sessions", methods=["GET"])
@login_required
def list_collab_sessions():
    """List all active/recent collaboration sessions from DB + memory."""
    try:
        from .collaboration_engine import get_collaboration_engine

        engine = get_collaboration_engine()
        search = request.args.get("search", "").strip()
        status_filter = request.args.get("status", "").strip()

        sessions = engine.list_sessions()

        # Apply search filter
        if search:
            search_lower = search.lower()
            sessions = [s for s in sessions if search_lower in (s.get("topic", "") or "").lower()]

        # Apply status filter
        if status_filter and status_filter != "all":
            sessions = [s for s in sessions if s.get("status") == status_filter]

        return jsonify({"success": True, "sessions": sessions})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/collab/continue/<session_id>", methods=["POST"])
@login_required
def continue_collaboration(session_id):
    """Continue a stopped/completed collaboration session from where it left off."""
    try:
        import threading
        import asyncio
        from .collaboration_engine import get_collaboration_engine

        engine = get_collaboration_engine()

        # Run continue in background thread
        def run_continue():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(engine.continue_session(session_id))
            finally:
                loop.close()

        thread = threading.Thread(target=run_continue, daemon=True)
        thread.start()

        audit_log(
            "COLLAB_CONTINUE",
            {
                "user_id": current_user.id,
                "session_id": session_id,
            },
            success=True,
        )

        return jsonify({"success": True, "session_id": session_id, "status": "active"})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/collab/joint/start", methods=["POST"])
@login_required
def start_joint_collaboration():
    """Start a joint ARCHIE + Claude collaboration that produces work products."""
    import asyncio

    data = request.get_json() or {}
    topic = data.get("topic", "").strip()
    max_turns = min(int(data.get("max_turns", 10)), 20)

    if not topic:
        return jsonify({"success": False, "error": "Topic required"}), 400

    try:
        from .collaboration_engine import get_collaboration_engine

        engine = get_collaboration_engine()
        system_hint = data.get("system_hint", "")
        session = engine.start_session(topic, max_turns=max_turns, user_id=current_user.id, system_hint=system_hint)

        # Run joint collaboration in background thread
        import threading

        def run_joint():
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(engine.run_joint_collaboration(session.id))
            except Exception as e:
                logger.error(f"Joint collaboration error: {e}")
            finally:
                loop.close()

        thread = threading.Thread(target=run_joint, daemon=True)
        thread.start()

        return jsonify(
            {
                "success": True,
                "session_id": session.id,
                "topic": topic,
                "max_turns": max_turns,
                "status": "active",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/collab/export/<session_id>", methods=["GET"])
@login_required
def export_collaboration(session_id):
    """Export a collaboration session as Markdown."""
    try:
        from .collaboration_engine import get_collaboration_engine

        engine = get_collaboration_engine()
        session = engine.get_session(session_id)

        if not session:
            return jsonify({"success": False, "error": "Session not found"}), 404

        # Build markdown
        lines = []
        lines.append(f"# AI Collaboration: {session.topic}")
        lines.append(
            f"**Date**: {session.created_at} | **Status**: {session.status.value} | **Turns**: {session.current_turn}/{session.max_turns}"
        )
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Conversation")
        lines.append("")

        for msg in session.messages:
            role_label = {
                "archie": "A.R.C.H.I.E.",
                "claude": "Claude",
                "user": "User",
                "system": "System",
            }.get(msg.role, msg.role)
            role_icon = {
                "archie": "\U0001f9e0",
                "claude": "\U0001f916",
                "user": "\U0001f464",
                "system": "\u2699\ufe0f",
            }.get(msg.role, "")
            model_info = ""
            if msg.model_used:
                model_info = f" ({msg.model_used}"
                if msg.duration_ms:
                    model_info += f", {msg.duration_ms}ms"
                model_info += ")"

            lines.append(f"### Turn {msg.turn}")
            lines.append(f"**{role_icon} {role_label}**{model_info}")
            lines.append(msg.content)
            lines.append("")

        # Add work products if any
        products = engine.get_work_products(session_id)
        if products:
            lines.append("## Work Products")
            lines.append("")
            for p in products:
                approved = "\u2713" if p.get("approved") else "\u2717"
                lines.append(f"### [{p['product_type']}] {p['title']}")
                lines.append(f"**Author**: {p['author']} | **Approved**: {approved}")
                lines.append(p.get("content", ""))
                lines.append("")

        lines.append("---")
        lines.append("*Exported from A.R.C.H.I.E. Platform*")

        markdown = "\n".join(lines)
        return jsonify({"success": True, "markdown": markdown, "topic": session.topic})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/collab/work-products/<int:product_id>/save-to-kb", methods=["POST"])
@login_required
def save_work_product_to_kb(product_id):
    """Save a work product to the knowledge base."""
    conn = None
    cur = None
    conn = None
    cur = None
    try:
        from .collaboration_engine import get_collaboration_engine

        get_collaboration_engine()

        # Find the work product
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT wp.id, wp.product_type, wp.title, wp.content, wp.author,
                   cs.topic, cs.session_uuid::text as session_uuid
            FROM collaboration_work_products wp
            JOIN collaboration_sessions cs ON wp.session_id = cs.id
            WHERE wp.id = %s
        """,
            (product_id,),
        )
        product = cur.fetchone()
        if not product:
            return jsonify({"success": False, "error": "Work product not found"}), 404

        # Insert into knowledge_base
        title = f"[Collab] {product['title']} — {product['topic'][:60]}"
        content = product["content"]
        cur.execute(
            """
            INSERT INTO knowledge_base (title, content, source_type, knowledge_type, importance_score)
            VALUES (%s, %s, 'collaboration', 'vault_note', 0.6)
            RETURNING id
        """,
            (title, content),
        )
        kb_id = cur.fetchone()["id"]
        conn.commit()

        # Generate embedding
        try:
            from ai_bridge.embedding_service import generate_embedding

            embedding = generate_embedding(f"{title}\n{content[:500]}")
            if embedding:
                cur.execute(
                    "UPDATE knowledge_base SET embedding = %s, has_embedding = TRUE WHERE id = %s",
                    (embedding, kb_id),
                )
                conn.commit()
        except Exception as emb_err:
            logger.warning(f"Failed to generate embedding for KB entry {kb_id}: {emb_err}")

        return jsonify({"success": True, "kb_id": kb_id, "title": title})

    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        if conn:
            conn.close()


@consciousness_bp.route("/api/collab/work-products/<session_id>", methods=["GET"])
@login_required
def get_work_products(session_id):
    """Get all work products for a collaboration session."""
    try:
        from .collaboration_engine import get_collaboration_engine

        engine = get_collaboration_engine()
        products = engine.get_work_products(session_id)
        return jsonify({"success": True, "products": products})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/collab/work-products/<int:product_id>/approve", methods=["POST"])
@login_required
def approve_work_product(product_id):
    """Approve a work product."""
    try:
        from .collaboration_engine import get_collaboration_engine

        engine = get_collaboration_engine()
        approved = engine.approve_work_product(product_id, current_user.username)

        if approved:
            # Log governance event for approval
            try:
                from tools.creed.admin_routes import log_governance_event

                log_governance_event(
                    event_type="work_product_approval",
                    category="collaboration",
                    action="approve_work_product",
                    reason=f"Work product {product_id} approved by {current_user.username}",
                    outcome="approved",
                )
            except Exception:
                pass

        return jsonify({"success": approved})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/collab/work-products/<int:product_id>/revise", methods=["POST"])
@login_required
def revise_work_product(product_id):
    """Create a new revision of a work product."""
    data = request.get_json() or {}
    new_content = data.get("content", "").strip()
    if not new_content:
        return jsonify({"success": False, "error": "Content required"}), 400

    try:
        from .collaboration_engine import get_collaboration_engine

        engine = get_collaboration_engine()
        new_id = engine.revise_work_product(product_id, new_content, current_user.username)
        if new_id:
            return jsonify({"success": True, "new_product_id": new_id})
        return jsonify({"success": False, "error": "Product not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/chat/history", methods=["GET"])
@login_required
def get_chat_history():
    """
    Load recent chat history for the current user.

    Returns solo (ARCHIE) and side-by-side messages from ai_conversations,
    keyed by chat_mode so the frontend can restore them on page load.
    """
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get recent solo/side-by-side messages (last 50)
        cur.execute(
            """
            SELECT id, conversation_id, message, response, model,
                   metadata, created_at
            FROM ai_conversations
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (current_user.id,),
        )
        rows = cur.fetchall()
        # Group by conversation_id, most recent conversation first
        conversations = {}
        for row in rows:
            cid = row["conversation_id"]
            if cid not in conversations:
                conversations[cid] = []
            conversations[cid].append(
                {
                    "id": row["id"],
                    "message": row["message"],
                    "response": row["response"],
                    "model": row["model"],
                    "chat_mode": (row["metadata"] or {}).get("chat_mode", "solo"),
                    "created_at": (row["created_at"].isoformat() if row["created_at"] else None),
                }
            )

        # Get the most recent conversation for solo mode
        solo_messages = []
        solo_conversation_id = None
        for cid, msgs in conversations.items():
            mode = msgs[0].get("chat_mode", "solo")
            if mode in ("solo", ""):
                solo_conversation_id = cid
                # Reverse so oldest is first
                solo_messages = list(reversed(msgs))
                break

        # Get recent side-by-side messages
        side_messages = []
        for cid, msgs in conversations.items():
            for m in msgs:
                if m.get("chat_mode") == "side-by-side-claude":
                    side_messages.append(m)
        side_messages = list(reversed(side_messages[:20]))

        return jsonify(
            {
                "success": True,
                "solo": {
                    "conversation_id": solo_conversation_id,
                    "messages": solo_messages,
                },
                "side_by_side_claude": side_messages,
            }
        )

    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# ============================================================================
# CONVERSATION THREAD MANAGEMENT
# ============================================================================


@consciousness_bp.route("/api/conversations", methods=["GET"])
@login_required
def list_conversations():
    """
    List all conversation threads for the current user.

    Returns threads ordered by last_message_at DESC, limit 200.
    Each item includes conversation_id, title, chat_mode, message_count,
    created_at, and last_message_at.
    """
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT conversation_id, title, chat_mode, message_count,
                   created_at, last_message_at
            FROM ai_conversation_threads
            WHERE user_id = %s AND (is_archived = false OR is_archived IS NULL)
            ORDER BY last_message_at DESC
            LIMIT 200
            """,
            (current_user.id,),
        )
        threads = cur.fetchall()
        # Serialize datetimes
        for t in threads:
            if t.get("created_at"):
                t["created_at"] = t["created_at"].isoformat()
            if t.get("last_message_at"):
                t["last_message_at"] = t["last_message_at"].isoformat()

        return jsonify({"success": True, "data": threads})

    except Exception as e:
        logging.error(f"Error listing conversations: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/conversations/<conv_id>/messages", methods=["GET"])
@login_required
def get_conversation_messages(conv_id):
    """
    Get all messages for a specific conversation.

    Returns messages from ai_conversations ordered by created_at ASC.
    """
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, conversation_id, message, response, model,
                   metadata, created_at
            FROM ai_conversations
            WHERE user_id = %s AND conversation_id = %s
            ORDER BY created_at ASC
            """,
            (current_user.id, conv_id),
        )
        messages = cur.fetchall()
        # Serialize datetimes and extract chat_mode from metadata
        for m in messages:
            if m.get("created_at"):
                m["created_at"] = m["created_at"].isoformat()
            if m.get("metadata") and isinstance(m["metadata"], dict):
                m["chat_mode"] = m["metadata"].get("chat_mode", "solo")
            else:
                m["chat_mode"] = "solo"

        return jsonify({"success": True, "data": messages})

    except Exception as e:
        logging.error(f"Error fetching conversation messages: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/conversations/<conv_id>", methods=["DELETE"])
@login_required
def delete_conversation(conv_id):
    """
    Delete a conversation thread and all its messages.

    Removes from both ai_conversation_threads and ai_conversations.
    Only the owning user can delete their conversations.
    """
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()

        # Delete messages first (child rows)
        cur.execute(
            """
            DELETE FROM ai_conversations
            WHERE user_id = %s AND conversation_id = %s
            """,
            (current_user.id, conv_id),
        )
        messages_deleted = cur.rowcount

        # Delete the thread record
        cur.execute(
            """
            DELETE FROM ai_conversation_threads
            WHERE user_id = %s AND conversation_id = %s
            """,
            (current_user.id, conv_id),
        )
        thread_deleted = cur.rowcount

        conn.commit()
        if thread_deleted == 0 and messages_deleted == 0:
            return jsonify({"success": False, "error": "Conversation not found"}), 404

        return jsonify(
            {
                "success": True,
                "messages_deleted": messages_deleted,
                "thread_deleted": thread_deleted > 0,
            }
        )

    except Exception as e:
        logging.error(f"Error deleting conversation: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/conversations/<conv_id>", methods=["PUT"])
@login_required
def update_conversation(conv_id):
    """
    Update a conversation thread (rename).

    Request body:
        - title: New title for the conversation
    """
    conn = None
    cur = None
    try:
        data = request.get_json() or {}
        title = data.get("title", "").strip()

        if not title:
            return jsonify({"success": False, "error": "Title is required"}), 400

        if len(title) > 255:
            return (
                jsonify({"success": False, "error": "Title too long (max 255 chars)"}),
                400,
            )

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE ai_conversation_threads
            SET title = %s, updated_at = NOW()
            WHERE user_id = %s AND conversation_id = %s
            """,
            (title, current_user.id, conv_id),
        )
        updated = cur.rowcount

        conn.commit()
        if updated == 0:
            return jsonify({"success": False, "error": "Conversation not found"}), 404

        return jsonify({"success": True, "title": title})

    except Exception as e:
        logging.error(f"Error updating conversation: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# ─── File Upload Endpoint ───────────────────────────────────────────────────────

ALLOWED_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".py",
    ".js",
    ".html",
    ".css",
    ".yml",
    ".yaml",
    ".xml",
    ".sql",
    ".sh",
    ".ts",
    ".tsx",
}
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_EXTRACTED_TEXT = 20000


@consciousness_bp.route("/api/chat/upload", methods=["POST"])
@login_required
def chat_file_upload():
    """
    Upload a file for chat context. Extracts text from common file types.

    Accepts multipart form data with:
        - file: The uploaded file
        - store_in_knowledge (optional): 'true' to save to knowledge_base

    Returns extracted text, optional thumbnail (images), and metadata.
    """
    import tempfile
    from werkzeug.utils import secure_filename

    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file provided"}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"success": False, "error": "No filename"}), 400

    filename = secure_filename(uploaded.filename)
    if not filename:
        return jsonify({"success": False, "error": "Invalid filename"}), 400

    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    file_type = ext.lstrip(".")

    extracted_text = ""
    thumbnail = None
    tmp_path = None

    try:
        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp_path = tmp.name
            uploaded.save(tmp_path)

        # ── PDF extraction ──────────────────────────────────────────────
        if ext == ".pdf":
            try:
                import PyPDF2

                with open(tmp_path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    pages = []
                    for page in reader.pages:
                        text = page.extract_text()
                        if text:
                            pages.append(text)
                    extracted_text = "\n\n".join(pages)
            except ImportError:
                extracted_text = "[PyPDF2 not installed — cannot extract PDF text]"
            except Exception as e:
                logging.error(f"PDF extraction error: {e}")
                extracted_text = f"[PDF extraction failed: {e}]"

        # ── DOCX extraction ─────────────────────────────────────────────
        elif ext == ".docx":
            try:
                import docx

                doc = docx.Document(tmp_path)
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                extracted_text = "\n\n".join(paragraphs)
            except ImportError:
                extracted_text = "[python-docx not installed — cannot extract DOCX text]"
            except Exception as e:
                logging.error(f"DOCX extraction error: {e}")
                extracted_text = f"[DOCX extraction failed: {e}]"

        # ── Image processing ────────────────────────────────────────────
        elif ext in ALLOWED_IMAGE_EXTENSIONS:
            try:
                from PIL import Image
                import io

                img = Image.open(tmp_path)
                img.thumbnail((200, 200))

                # Convert to RGB if needed (e.g. RGBA PNGs)
                if img.mode in ("RGBA", "P", "LA"):
                    img = img.convert("RGB")

                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85)
                buf.seek(0)
                thumbnail = "data:image/jpeg;base64," + base64.b64encode(buf.read()).decode("utf-8")
            except ImportError:
                logging.error("Pillow not installed — cannot process image")
            except Exception as e:
                logging.error(f"Image thumbnail error: {e}")

            # Try OCR if pytesseract is available
            try:
                import pytesseract
                from PIL import Image as PILImage

                img = PILImage.open(tmp_path)
                extracted_text = pytesseract.image_to_string(img)
            except ImportError:
                extracted_text = "[Image file — OCR not available (pytesseract not installed)]"
            except Exception as e:
                logging.error(f"OCR error: {e}")
                extracted_text = f"[Image file — OCR failed: {e}]"

        # ── Text-based files ────────────────────────────────────────────
        elif ext in ALLOWED_TEXT_EXTENSIONS:
            try:
                with open(tmp_path, "r", encoding="utf-8", errors="replace") as f:
                    extracted_text = f.read()
            except Exception as e:
                logging.error(f"Text read error: {e}")
                extracted_text = f"[Failed to read text file: {e}]"

        # ── Unsupported type ────────────────────────────────────────────
        else:
            return (
                jsonify({"success": False, "error": f"Unsupported file type: {ext}"}),
                400,
            )

        # Cap extracted text
        if len(extracted_text) > MAX_EXTRACTED_TEXT:
            extracted_text = extracted_text[:MAX_EXTRACTED_TEXT]

        # ── Optional: store in knowledge base ───────────────────────────
        store_in_knowledge = request.form.get("store_in_knowledge", "").lower() == "true"
        if store_in_knowledge and extracted_text.strip():
            conn = None
            cur = None
            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO knowledge_base
                        (title, content, source_type, tags, importance_score, created_at, updated_at)
                    VALUES (%s, %s, 'chat_upload', %s, 0.5, NOW(), NOW())
                    """,
                    (
                        f"Chat Upload: {filename}",
                        extracted_text,
                        json.dumps(["chat-upload", file_type]),
                    ),
                )
                conn.commit()
            except Exception as e:
                logging.error(f"Knowledge base insert error: {e}")
            finally:
                if cur:
                    cur.close()
                if conn:
                    conn.close()

        return jsonify(
            {
                "success": True,
                "filename": filename,
                "file_type": file_type,
                "extracted_text": extracted_text,
                "thumbnail": thumbnail,
                "text_length": len(extracted_text),
            }
        )

    except Exception as e:
        logging.error(f"File upload processing error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

    finally:
        # Clean up temp file
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@consciousness_bp.route("/api/terminal/token", methods=["POST"])
@login_required
@admin_required
def generate_terminal_token():
    """Generate a one-time auth token for the Claude Terminal (ttyd SSO)."""
    import secrets

    conn = None
    cur = None
    try:
        token = secrets.token_urlsafe(32)

        conn = get_db()
        cur = conn.cursor()

        # Clean up expired and used tokens
        cur.execute("DELETE FROM terminal_auth_tokens WHERE expires_at < NOW() OR used = TRUE")

        # Insert new token with 60-second expiry
        cur.execute(
            """
            INSERT INTO terminal_auth_tokens (user_id, token, expires_at)
            VALUES (%s, %s, NOW() + INTERVAL '60 seconds')
            """,
            (current_user.id, token),
        )
        conn.commit()
        return jsonify({"success": True, "token": token})

    except Exception as e:
        logging.error(f"Error generating terminal token: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/claude/chat", methods=["POST"])
@login_required
@admin_required
def claude_side_chat():
    """
    Send a message to Claude via the CLI proxy (side-by-side mode).

    Request body:
        - message: The user's message to Claude

    Returns:
        - response: Claude's reply
    """
    import asyncio

    data = request.get_json() or {}
    message = data.get("message", "").strip()

    if not message:
        return jsonify({"success": False, "error": "Message required"}), 400

    try:
        from .claude_bridge import get_claude_bridge

        bridge = get_claude_bridge()

        # Run async send_message in a new event loop
        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(
                bridge.send_message(
                    message,
                    system_prompt=(
                        "You are Claude, chatting directly with a human user in a side-by-side "
                        "interface alongside A.R.C.H.I.E. (another AI). Be helpful, concise, and friendly. "
                        "Answer the user's questions directly."
                    ),
                )
            )
        finally:
            loop.close()

        if response:
            # Persist Claude side-by-side message to DB
            conn = None
            cur = None
            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO ai_conversations
                    (user_id, conversation_id, message, response, model, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        current_user.id,
                        data.get("conversation_id", "claude-side-" + str(current_user.id)),
                        message,
                        response,
                        "claude-max-cli",
                        json.dumps({"chat_mode": "side-by-side-claude"}),
                    ),
                )
                conn.commit()
            except Exception as db_err:
                logger.warning(f"Failed to persist Claude message: {db_err}")
            finally:
                if cur:
                    cur.close()
                if conn:
                    conn.close()

            return jsonify({"success": True, "response": response})
        else:
            return jsonify({"success": False, "error": "No response from Claude"}), 502

    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/claude/status", methods=["GET"])
@login_required
def get_claude_status():
    """
    Check Claude CLI and ttyd status.

    Returns:
        - claude: Claude CLI availability
        - ttyd: ttyd service status
    """
    try:
        from .claude_bridge import get_claude_bridge

        bridge = get_claude_bridge()
        return jsonify(
            {
                "success": True,
                "claude": bridge.health_check(),
                "ttyd": bridge.get_ttyd_status(),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/claude/sync-context", methods=["POST"])
@login_required
def sync_context_to_claude():
    """
    Send ARCHIE's conversation context to Claude via the proxy.
    Primes Claude with the current conversation so it can continue the work.
    """
    try:
        from .claude_bridge import get_claude_bridge

        data = request.get_json() or {}
        context = data.get("context", "")
        if not context:
            return jsonify({"success": False, "error": "No context provided"}), 400

        bridge = get_claude_bridge()
        bridge.clear_history()

        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                bridge.send_message(
                    f"Here is the context from ARCHIE's conversation that you should be aware of:\n\n{context}\n\nPlease acknowledge you've received this context."
                )
            )
        finally:
            loop.close()

        return jsonify(
            {
                "success": True,
                "response": result[:200] if result else "Context received",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# VOICE MANAGEMENT ROUTES
# ============================================================================


@consciousness_bp.route("/api/voice/dashboard", methods=["GET"])
@login_required
@admin_required
def voice_dashboard():
    """Aggregated voice stats: cached words, hit rate, storage, today's gens"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                COUNT(*) as cached_words,
                COALESCE(SUM(hit_count), 0) as total_hits,
                COALESCE(SUM(usage_count), 0) as total_usage,
                COALESCE(SUM(LENGTH(full_audio_cache)), 0) as storage_bytes,
                COALESCE(AVG(duration_ms) FILTER (WHERE duration_ms > 0), 0)::INTEGER as avg_gen_ms
            FROM voice_word_cache
        """
        )
        cache_stats = dict(cur.fetchone())

        cur.execute(
            """
            SELECT
                COUNT(*) as today_gens,
                COUNT(*) FILTER (WHERE cached = TRUE) as today_cache_hits,
                COALESCE(AVG(generation_time_ms) FILTER (WHERE cached = FALSE), 0)::INTEGER as today_avg_ms
            FROM voice_generation_log
            WHERE created_at::date = CURRENT_DATE
        """
        )
        today = dict(cur.fetchone())

        total_requests = cache_stats["total_hits"] + cache_stats["cached_words"]
        hit_rate = round(100.0 * cache_stats["total_hits"] / max(total_requests, 1), 1)

        cur.execute(
            """
            SELECT emotion_context, COUNT(*) as count,
                   SUM(hit_count) as hits
            FROM voice_word_cache
            WHERE emotion_context IS NOT NULL
            GROUP BY emotion_context
            ORDER BY count DESC
            LIMIT 10
        """
        )
        top_emotions = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT word_text, emotion_context, hit_count, duration_ms
            FROM voice_word_cache
            WHERE hit_count > 0
            ORDER BY hit_count DESC
            LIMIT 20
        """
        )
        top_words = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT id, status, job_type, total_words, completed_words, failed_words
            FROM voice_pregen_jobs
            WHERE status IN ('pending', 'running')
            ORDER BY created_at DESC
            LIMIT 5
        """
        )
        active_jobs = [dict(r) for r in cur.fetchall()]

        # Engine breakdown
        cur.execute(
            """
            SELECT COALESCE(engine, 'xtts_v2') as engine, COUNT(*) as count
            FROM voice_word_cache
            GROUP BY COALESCE(engine, 'xtts_v2')
        """
        )
        engine_breakdown = {r["engine"]: r["count"] for r in cur.fetchall()}
        return jsonify(
            {
                "success": True,
                "cached_words": cache_stats["cached_words"],
                "total_hits": cache_stats["total_hits"],
                "hit_rate": hit_rate,
                "storage_bytes": cache_stats["storage_bytes"],
                "storage_mb": round(cache_stats["storage_bytes"] / (1024 * 1024), 2),
                "avg_gen_ms": cache_stats["avg_gen_ms"],
                "today_gens": today["today_gens"],
                "today_cache_hits": today["today_cache_hits"],
                "today_avg_ms": today["today_avg_ms"],
                "top_emotions": top_emotions,
                "top_words": top_words,
                "active_jobs": active_jobs,
                "engine_breakdown": engine_breakdown,
            }
        )

    except Exception as e:
        logger.error(f"Voice dashboard error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/voice/speakers", methods=["GET"])
@login_required
@admin_required
def voice_speakers():
    """List all speakers grouped by engine, emotions, and parameter ranges"""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        from ai_bridge.voice_synthesis import get_voice_synthesizer

        synth = get_voice_synthesizer()
        all_speakers = synth.get_available_speakers()  # Returns both grouped
        emotions = list(synth.EMOTION_VOICE_MAP.keys())
        emotion_presets = {k: {pk: float(pv) for pk, pv in v.items()} for k, v in synth.EMOTION_VOICE_MAP.items()}

        return jsonify(
            {
                "success": True,
                "engines": ["kokoro", "xtts_v2"],
                "default_engine": "kokoro",
                "speakers": all_speakers,
                "emotions": emotions,
                "emotion_presets": emotion_presets,
                "engine_capabilities": {
                    "kokoro": {
                        "speed": True,
                        "pitch_shift": False,
                        "warmth": False,
                        "voice_blend": True,
                    },
                    "xtts_v2": {
                        "speed": True,
                        "pitch_shift": True,
                        "warmth": True,
                        "voice_blend": False,
                    },
                },
                "parameter_ranges": {
                    "speed": {"min": 0.50, "max": 2.00, "default": 1.00, "step": 0.05},
                    "pitch_shift": {
                        "min": 0.80,
                        "max": 1.20,
                        "default": 1.00,
                        "step": 0.01,
                    },
                    "warmth": {"min": 0.00, "max": 1.00, "default": 0.80, "step": 0.05},
                },
            }
        )

    except Exception as e:
        logger.error(f"Voice speakers error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/voice/preview", methods=["POST"])
@login_required
@admin_required
def voice_preview():
    """Generate preview audio with custom params (no save to profile)"""
    try:
        data = request.get_json()
        text = data.get("text", "Hello, I am A.R.C.H.I.E. How can I help you today?")
        speaker = data.get("speaker", "af_heart")
        speed = float(data.get("speed", 1.0))
        pitch_shift = float(data.get("pitch_shift", 1.0))
        warmth = float(data.get("warmth", 0.8))
        emotion = data.get("emotion", "neutral")
        quality = data.get("quality", "standard")
        engine = data.get("engine", "kokoro")
        voice_blend = data.get("voice_blend", None)
        language = data.get("language", "en")
        if quality not in ("standard", "high"):
            quality = "standard"
        if engine not in ("kokoro", "xtts_v2"):
            engine = "kokoro"
        if language not in (
            "en",
            "fr",
            "es",
            "de",
            "it",
            "pt",
            "pl",
            "tr",
            "ru",
            "nl",
            "cs",
            "ar",
            "zh-cn",
            "ja",
            "hu",
            "ko",
        ):
            language = "en"

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        from ai_bridge.voice_synthesis import get_voice_synthesizer

        synth = get_voice_synthesizer()
        result = synth.synthesize_with_params(
            text,
            speaker,
            speed,
            pitch_shift,
            warmth,
            emotion,
            quality,
            engine=engine,
            voice_blend=voice_blend,
            language=language,
        )

        return jsonify(result)

    except Exception as e:
        logger.error(f"Voice preview error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/voice/profiles", methods=["GET"])
@login_required
@admin_required
def voice_profiles_list():
    """List all agent voice profiles with cached word counts"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT p.*,
                   a.name as agent_name,
                   a.first_name as agent_first_name,
                   a.avatar_url as agent_avatar,
                   COALESCE(cache.cached_count, 0) as cached_words,
                   COALESCE(locked.locked_count, 0) as locked_words
            FROM agent_voice_profiles p
            LEFT JOIN agents a ON p.agent_id = a.id
            LEFT JOIN (
                SELECT agent_id, COALESCE(language, 'en') as lang, COUNT(*) as cached_count
                FROM voice_word_cache
                WHERE agent_id IS NOT NULL
                GROUP BY agent_id, COALESCE(language, 'en')
            ) cache ON cache.agent_id = p.agent_id AND cache.lang = p.language
            LEFT JOIN (
                SELECT agent_id, COALESCE(language, 'en') as lang, COUNT(*) as locked_count
                FROM voice_word_cache
                WHERE agent_id IS NOT NULL AND is_locked = TRUE
                GROUP BY agent_id, COALESCE(language, 'en')
            ) locked ON locked.agent_id = p.agent_id AND locked.lang = p.language
            ORDER BY p.created_at DESC
        """
        )
        profiles = []
        for row in cur.fetchall():
            d = dict(row)
            for k in ("speed", "pitch_shift", "warmth"):
                if d.get(k) is not None:
                    d[k] = float(d[k])
            if d.get("created_at"):
                d["created_at"] = d["created_at"].isoformat()
            if d.get("updated_at"):
                d["updated_at"] = d["updated_at"].isoformat()
            # Ensure engine defaults
            if not d.get("engine"):
                d["engine"] = "xtts_v2"
            profiles.append(d)

        cur.execute(
            """
            SELECT id, name, first_name, avatar_url
            FROM agents WHERE status = 'active'
            ORDER BY name
        """
        )
        agents = [dict(r) for r in cur.fetchall()]
        return jsonify({"success": True, "profiles": profiles, "agents": agents})

    except Exception as e:
        logger.error(f"Voice profiles list error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/voice/profiles", methods=["POST"])
@login_required
@admin_required
def voice_profile_save():
    """Create or update agent voice profile (upsert on agent_id + language)"""
    try:
        data = request.get_json()
        agent_id = data.get("agent_id")
        profile_name = data.get("profile_name", "Default")
        speaker = data.get("speaker", "af_heart")
        speed = float(data.get("speed", 1.0))
        pitch_shift = float(data.get("pitch_shift", 1.0))
        warmth = float(data.get("warmth", 0.8))
        default_emotion = data.get("default_emotion", "neutral")
        emotion_overrides = data.get("emotion_overrides", {})
        engine = data.get("engine", "kokoro")
        voice_blend = data.get("voice_blend", None)
        language = data.get("language", "en")

        if engine not in ("kokoro", "xtts_v2"):
            engine = "kokoro"
        if language not in (
            "en",
            "fr",
            "es",
            "de",
            "it",
            "pt",
            "pl",
            "tr",
            "ru",
            "nl",
            "cs",
            "ar",
            "zh-cn",
            "ja",
            "hu",
            "ko",
        ):
            language = "en"

        if not agent_id:
            return jsonify({"success": False, "error": "agent_id required"}), 400

        conn = None
        cur = None
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO agent_voice_profiles
            (agent_id, profile_name, speaker, speed, pitch_shift, warmth,
             default_emotion, emotion_overrides, created_by, engine, voice_blend, language)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (agent_id, language) DO UPDATE SET
                profile_name = EXCLUDED.profile_name,
                speaker = EXCLUDED.speaker,
                speed = EXCLUDED.speed,
                pitch_shift = EXCLUDED.pitch_shift,
                warmth = EXCLUDED.warmth,
                default_emotion = EXCLUDED.default_emotion,
                emotion_overrides = EXCLUDED.emotion_overrides,
                engine = EXCLUDED.engine,
                voice_blend = EXCLUDED.voice_blend,
                updated_at = NOW()
            RETURNING id
        """,
            (
                agent_id,
                profile_name,
                speaker,
                speed,
                pitch_shift,
                warmth,
                default_emotion,
                json.dumps(emotion_overrides),
                current_user.id,
                engine,
                voice_blend,
                language,
            ),
        )
        result = cur.fetchone()
        conn.commit()
        return jsonify({"success": True, "profile_id": result["id"]})

    except Exception as e:
        logger.error(f"Voice profile save error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/voice/profiles/<int:profile_id>", methods=["DELETE"])
@login_required
@admin_required
def voice_profile_delete(profile_id):
    """Delete a voice profile"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM agent_voice_profiles WHERE id = %s", (profile_id,))
        deleted = cur.rowcount
        conn.commit()
        if deleted:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Profile not found"}), 404

    except Exception as e:
        logger.error(f"Voice profile delete error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/voice/profiles/<int:profile_id>/agent-name", methods=["PATCH"])
@login_required
@admin_required
def voice_profile_rename_agent(profile_id):
    """Rename the agent associated with a voice profile.

    Single-writer path: routes through agent_service.update_agent so the agents
    table only has one canonical mutation surface (Project #241 Track C.1).
    """
    try:
        data = request.get_json() or {}
        new_name = (data.get("name") or "").strip()
        if not new_name:
            return jsonify({"success": False, "error": "Name is required"}), 400

        from database import get_db_cursor

        with get_db_cursor(commit=False) as (_conn, cur):
            cur.execute("SELECT agent_id FROM agent_voice_profiles WHERE id = %s", (profile_id,))
            row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "error": "Profile not found"}), 404

        agent_id = row[0] if not isinstance(row, dict) else row["agent_id"]
        if not agent_service.update_agent(agent_id, name=new_name):
            return jsonify({"success": False, "error": "Agent not found"}), 404

        return jsonify({"success": True})

    except Exception as e:
        logger.error(f"Voice agent rename error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/voice/cache", methods=["GET"])
@login_required
@admin_required
def voice_cache_list():
    """Paginated cache entries with filters + agent group summaries"""
    conn = None
    cur = None
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 25))
        emotion = request.args.get("emotion", "")
        sort = request.args.get("sort", "hits")
        agent_id = request.args.get("agent_id", "")
        engine_filter = request.args.get("engine", "")
        language_filter = request.args.get("language", "")

        offset = (page - 1) * per_page

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        conditions = ["c.text_hash IS NOT NULL"]
        params = []

        if emotion:
            conditions.append("c.emotion_context = %s")
            params.append(emotion)
        if agent_id:
            conditions.append("c.agent_id = %s")
            params.append(int(agent_id))
        if engine_filter:
            conditions.append("COALESCE(c.engine, 'xtts_v2') = %s")
            params.append(engine_filter)
        if language_filter:
            conditions.append("COALESCE(c.language, 'en') = %s")
            params.append(language_filter)

        where = " AND ".join(conditions)

        ORDER_MAP = {
            "recent": "c.last_used DESC NULLS LAST",
            "largest": "LENGTH(c.full_audio_cache) DESC NULLS LAST",
        }
        order = ORDER_MAP.get(sort, "c.hit_count DESC")

        cur.execute(f"SELECT COUNT(*) as total FROM voice_word_cache c WHERE {where}", params)
        total = cur.fetchone()["total"]

        cur.execute(
            f"""
            SELECT c.word_id, c.word_text, c.emotion_context, c.hit_count, c.usage_count,
                   c.duration_ms, c.last_used, c.agent_id, c.is_locked,
                   COALESCE(c.engine, 'xtts_v2') as engine,
                   COALESCE(c.language, 'en') as language,
                   LENGTH(c.full_audio_cache) as audio_size,
                   a.name as agent_name
            FROM voice_word_cache c
            LEFT JOIN agents a ON c.agent_id = a.id
            WHERE {where}
            ORDER BY {order}
            LIMIT %s OFFSET %s
        """,
            params + [per_page, offset],
        )

        entries = []
        for row in cur.fetchall():
            d = dict(row)
            if d.get("last_used"):
                d["last_used"] = d["last_used"].isoformat()
            entries.append(d)

        # Agent group summaries (always return for cache overview)
        cur.execute(
            """
            SELECT c.agent_id,
                   COALESCE(a.name, 'No Agent') as agent_name,
                   COUNT(*) as word_count,
                   COALESCE(SUM(LENGTH(c.full_audio_cache)), 0) as total_size,
                   COALESCE(SUM(c.hit_count), 0) as total_hits
            FROM voice_word_cache c
            LEFT JOIN agents a ON c.agent_id = a.id
            WHERE c.text_hash IS NOT NULL
            GROUP BY c.agent_id, a.name
            ORDER BY word_count DESC
        """
        )
        agent_groups = []
        for row in cur.fetchall():
            d = dict(row)
            agent_groups.append(d)
        return jsonify(
            {
                "success": True,
                "entries": entries,
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": (total + per_page - 1) // per_page,
                "agent_groups": agent_groups,
            }
        )

    except Exception as e:
        logger.error(f"Voice cache list error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/voice/pregen", methods=["POST"])
@login_required
@admin_required
def voice_pregen_start():
    """Start a pre-generation job"""
    try:
        data = request.get_json()
        job_type = data.get("job_type", "manual")
        word_count = int(data.get("word_count", 100))
        emotions = data.get("emotions", ["neutral"])
        agent_id = data.get("agent_id")
        custom_phrases = data.get("custom_phrases", [])
        quality = data.get("quality", "high")
        language = data.get("language", "en")
        if quality not in ("standard", "high"):
            quality = "high"

        VALID_LANGUAGES = (
            "en",
            "fr",
            "es",
            "de",
            "it",
            "pt",
            "pl",
            "tr",
            "ru",
            "nl",
            "cs",
            "ar",
            "zh-cn",
            "ja",
            "hu",
            "ko",
        )
        if language not in VALID_LANGUAGES:
            language = "en"

        # Look up agent's voice profile for engine/language
        engine = data.get("engine", "kokoro")
        conn = None
        cur = None
        if agent_id:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT engine, language FROM agent_voice_profiles WHERE agent_id = %s AND language = %s",
                (agent_id, language),
            )
            profile = cur.fetchone()
            if not profile:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Agent has no voice profile for language: " + language,
                        }
                    ),
                    400,
                )
            engine = profile["engine"] or "kokoro"

        if engine not in ("kokoro", "xtts_v2"):
            engine = "kokoro"

        from .voice_pregen import start_pregen_job

        job_id = start_pregen_job(
            job_type=job_type,
            word_count=word_count,
            emotions=emotions,
            agent_id=agent_id,
            custom_phrases=custom_phrases,
            quality=quality,
            engine=engine,
            language=language,
        )

        return jsonify({"success": True, "job_id": job_id})

    except Exception as e:
        logger.error(f"Voice pregen start error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        if conn:
            conn.close()


@consciousness_bp.route("/api/voice/pregen/full-dna", methods=["POST"])
@login_required
@admin_required
def voice_full_dna():
    """Start a Full Voice DNA job — all phrases + top words across all 10 emotions"""
    conn = None
    cur = None
    conn = None
    cur = None
    try:
        data = request.get_json() or {}
        agent_id = data.get("agent_id")
        language = data.get("language", "en")

        if not agent_id:
            return jsonify({"success": False, "error": "agent_id required"}), 400

        # Look up agent's voice profile
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT engine, language FROM agent_voice_profiles WHERE agent_id = %s",
            (agent_id,),
        )
        profile = cur.fetchone()
        if not profile:
            return (
                jsonify({"success": False, "error": "Agent has no voice profile"}),
                400,
            )

        engine = profile["engine"] or "kokoro"

        ALL_EMOTIONS = [
            "neutral",
            "excited",
            "curious",
            "empathetic",
            "focused",
            "playful",
            "concerned",
            "thoughtful",
            "confident",
            "gentle",
        ]

        from .voice_pregen import start_pregen_job

        job_id = start_pregen_job(
            job_type="manual",
            word_count=200,
            emotions=ALL_EMOTIONS,
            agent_id=agent_id,
            quality="high",
            engine=engine,
            language=language,
        )

        return jsonify({"success": True, "job_id": job_id, "emotions": len(ALL_EMOTIONS)})

    except Exception as e:
        logger.error(f"Voice full DNA error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        if conn:
            conn.close()


@consciousness_bp.route("/api/voice/pregen/<int:job_id>", methods=["GET"])
@login_required
@admin_required
def voice_pregen_status(job_id):
    """Poll pre-gen job progress"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, agent_id, status, job_type, total_words, completed_words,
                   failed_words, started_at, completed_at, error_message
            FROM voice_pregen_jobs WHERE id = %s
        """,
            (job_id,),
        )
        job = cur.fetchone()
        if not job:
            return jsonify({"success": False, "error": "Job not found"}), 404

        d = dict(job)
        for k in ("started_at", "completed_at"):
            if d.get(k):
                d[k] = d[k].isoformat()

        d["progress_pct"] = round(100.0 * d["completed_words"] / max(d["total_words"], 1), 1)
        return jsonify({"success": True, "job": d})

    except Exception as e:
        logger.error(f"Voice pregen status error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@consciousness_bp.route("/api/voice/profile-lock-status/<int:profile_id>")
@login_required
@admin_required
def voice_profile_lock_status(profile_id):
    """Get locked cache entry count for a voice profile."""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """SELECT COUNT(*) FROM voice_word_cache vwc
            JOIN agent_voice_profiles avp ON avp.id = %s
            WHERE vwc.agent_id = avp.agent_id
            AND vwc.engine = avp.engine
            AND vwc.language = avp.language
            AND vwc.is_locked = TRUE""",
            (profile_id,),
        )
        count = cur.fetchone()[0]
        return jsonify({"success": True, "locked_count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        if conn:
            conn.close()


# Language/Translation routes moved to language_routes.py
