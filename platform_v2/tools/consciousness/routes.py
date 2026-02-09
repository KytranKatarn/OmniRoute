"""
Consciousness Module Routes - ADMIN-ONLY

This module handles:
- Memory Management (conversation memories from knowledge_base)
- Team Awareness (agent directory, performance tracking)
- Analytics (knowledge growth metrics)

All routes require admin authentication.
"""

from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import base64
import json
import logging
import os
import re
import sys

import requests

logger = logging.getLogger(__name__)

# Add platform root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from rbac import require_permission, Permission, has_permission
from logging_config import audit_log

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
                {"route": request.endpoint, "user_id": current_user.id if current_user.is_authenticated else None},
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
        password=os.getenv("DB_PASSWORD", "archiepass"),
    )


# ============================================================================
# MAIN DASHBOARD
# ============================================================================


@consciousness_bp.route("/")
@login_required
@admin_required
def index():
    """Consciousness dashboard - memory, analytics, team"""
    return render_template("tools/consciousness_dashboard.html")


# ============================================================================
# MEMORY MANAGEMENT ROUTES
# ============================================================================


@consciousness_bp.route("/memory")
@login_required
@admin_required
def memory():
    """View A.R.C.H.I.E.'s memory tables"""
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

        cur.close()
        conn.close()

        return render_template("tools/consciousness_memory.html", table_stats=table_stats)
    except Exception as e:
        flash(f"Error loading memory: {str(e)}", "error")
        return redirect(url_for("consciousness.index"))


@consciousness_bp.route("/memories/<view_type>", methods=["GET"])
@login_required
@admin_required
def get_memories(view_type):
    """Get memories by view type (recent, important, accessed, types)"""
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
            cur.execute(
                """
                SELECT * FROM knowledge_base
                ORDER BY created_at DESC
                LIMIT 50
            """
            )

        memories = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({"memories": memories, "view_type": view_type})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@consciousness_bp.route("/emotional-state", methods=["GET"])
@login_required
@admin_required
def emotional_state():
    """Get current emotional state with rich data from multiple tables"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Main emotional state with extra fields
        cur.execute(
            """
            SELECT id, timestamp, current_mood as mood, mood_intensity as energy,
                   relationship_strength as confidence, user_id, notes,
                   mood_context, conversation_tone,
                   user_happiness_detected, user_stress_detected
            FROM archie_emotional_state
            ORDER BY timestamp DESC
            LIMIT 1
        """
        )
        state = cur.fetchone()

        # Agent emotional state (ARCHIE's own feelings)
        cur.execute(
            """
            SELECT current_mood, mood_intensity, energy_level, stress_level,
                   trigger_event, previous_mood, mood_duration_minutes
            FROM agent_emotional_state
            ORDER BY timestamp DESC
            LIMIT 1
        """
        )
        agent_state = cur.fetchone()

        # Recent mood transitions
        cur.execute(
            """
            SELECT current_mood, previous_mood, trigger_event,
                   mood_duration_minutes, timestamp
            FROM agent_emotional_state
            WHERE previous_mood IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT 5
        """
        )
        mood_transitions = cur.fetchall()

        # Recent emotional memories
        cur.execute(
            """
            SELECT event_type, context_summary, user_emotion_detected,
                   emotional_intensity, relationship_impact, event_timestamp
            FROM emotional_memory
            ORDER BY event_timestamp DESC
            LIMIT 5
        """
        )
        emotional_memories = cur.fetchall()

        # Relationship strength per user
        cur.execute(
            """
            SELECT aes.user_id, u.username,
                   aes.relationship_strength, aes.current_mood,
                   aes.timestamp
            FROM archie_emotional_state aes
            JOIN users u ON aes.user_id = u.id
            WHERE aes.user_id IS NOT NULL
            AND aes.id IN (
                SELECT MAX(id) FROM archie_emotional_state
                WHERE user_id IS NOT NULL
                GROUP BY user_id
            )
            ORDER BY aes.relationship_strength DESC
        """
        )
        relationships = cur.fetchall()

        cur.close()
        conn.close()

        result = dict(state) if state else {"mood": "neutral", "energy": 0.5, "confidence": 0.5}
        if agent_state:
            result["agent_state"] = dict(agent_state)
        result["mood_transitions"] = [dict(t) for t in mood_transitions]
        result["emotional_memories"] = [dict(m) for m in emotional_memories]
        result["relationships"] = [dict(r) for r in relationships]

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@consciousness_bp.route("/backup", methods=["POST"])
@login_required
@admin_required
def backup_consciousness():
    """Backup A.R.C.H.I.E.'s consciousness"""
    try:
        import subprocess

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"/var/backups/archie_brain/archie_consciousness_{timestamp}.sql"

        # Create backup directory if it doesn't exist
        os.makedirs("/var/backups/archie_brain", exist_ok=True)

        # Backup knowledge_base table
        result = subprocess.run(
            [
                "docker",
                "exec",
                "archie_database",
                "pg_dump",
                "-U",
                "archie",
                "-d",
                "archie",
                "-t",
                "knowledge_base",
                "-t",
                "long_term_memory",
                "-f",
                backup_file,
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            return jsonify({"success": True, "message": f"Consciousness backed up to {backup_file}"})
        else:
            return jsonify({"success": False, "error": result.stderr}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/stats", methods=["GET"])
@login_required
@admin_required
def get_stats():
    """Get comprehensive knowledge statistics - ALL database fields for complete business awareness"""
    print("🧠 [BACKEND] get_consciousness_stats called - COMPREHENSIVE MODE")
    import psycopg2.extras

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
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

        print(f"🧠 [BACKEND] TOTAL KNOWLEDGE: {total_knowledge}")
        print(f"  - Long-term memories: {long_term_memories}")
        print(f"  - Improvement proposals: {improvement_proposals_count}")
        print(f"  - Improvement conversations: {improvement_conversations_count}")
        print(f"  - Codebase knowledge: {codebase_knowledge_count}")
        print(f"  - AI conversations: {ai_conversations_count}")
        print(f"  - Core identity: {core_identity_count}")
        print(f"  - Learning resources (GitHub): {knowledge_base_count}")
        print(f"  - Claude Code sessions: {claude_code_sessions_count}")

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
            ORDER BY date DESC
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

        cur.close()
        conn.close()

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
        print(f"🧠 [BACKEND] Returning COMPREHENSIVE stats:")
        print(f"  - {total_knowledge} TOTAL KNOWLEDGE (all sources)")
        print(f"  - {len(memory_types)} memory types")
        print(f"  - {len(categories)} categories")
        print(f"  - {len(all_tags)} unique tags")
        print(
            f"  - {len(new_tags)} NEW tags detected (7d: {len([t for t in new_tags if t['tag_age'] == 'new_7d'])}, 30d: {len([t for t in new_tags if t['tag_age'] == 'new_30d'])})"
        )
        print(f"  - {len(metadata_fields)} metadata fields tracked")
        return jsonify(result)
    except Exception as e:
        import traceback

        print("❌ [BACKEND] Error in get_consciousness_stats:")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/search", methods=["POST"])
@login_required
@admin_required
def search_knowledge():
    """Search across knowledge_base"""
    print("🔍 [BACKEND] search_knowledge called")

    data = request.json
    query = data.get("query", "")
    category = data.get("category")
    knowledge_type = data.get("knowledge_type")
    limit = data.get("limit", 50)

    conn = get_db()
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

        cur.close()
        conn.close()

        return jsonify({"results": results, "count": len(results)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@consciousness_bp.route("/memory/<int:memory_id>", methods=["DELETE"])
@login_required
@admin_required
def delete_memory(memory_id):
    """Delete a memory from knowledge_base"""
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("DELETE FROM knowledge_base WHERE id = %s", (memory_id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@consciousness_bp.route("/memory/<int:memory_id>", methods=["PUT"])
@login_required
@admin_required
def update_memory(memory_id):
    """Update a memory"""
    data = request.json

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            UPDATE knowledge_base
            SET content = %s,
                category = %s,
                tags = %s,
                importance_score = %s,
                updated_at = NOW()
            WHERE id = %s
        """,
            (data.get("content"), data.get("category"), data.get("tags", []), data.get("importance_score"), memory_id),
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@consciousness_bp.route("/ingest-text", methods=["POST"])
@login_required
@admin_required
def ingest_text():
    """Manually add text knowledge to consciousness"""
    data = request.json
    content = data.get("content")
    category = data.get("category", "manual")
    tags = data.get("tags", [])

    if not content:
        return jsonify({"error": "Content required"}), 400

    conn = get_db()
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
        cur.close()
        conn.close()

        return jsonify({"success": True, "message": "Knowledge added"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@consciousness_bp.route("/knowledge/create", methods=["POST"])
@login_required
@admin_required
def create_knowledge():
    """Create a new knowledge entry with full details (title, content, category, etc.)"""
    data = request.json

    title = data.get("title")
    content = data.get("content")
    category = data.get("category", "uncategorized")
    tags = data.get("tags", [])
    knowledge_type = data.get("knowledge_type", "vault_note")
    importance_score = data.get("importance_score", 0.8)
    is_documentation = data.get("is_documentation", True)

    if not title or not content:
        return jsonify({"error": "Title and content are required"}), 400

    conn = get_db()
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
            (title, content, knowledge_type, category, tags, importance_score, is_documentation),
        )

        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "message": "Knowledge entry created", "id": new_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@consciousness_bp.route("/knowledge/<int:knowledge_id>", methods=["GET"])
@login_required
@admin_required
def get_knowledge(knowledge_id):
    """Get a specific knowledge entry by ID"""
    conn = get_db()
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
        cur.close()
        conn.close()

        if entry:
            return jsonify({"success": True, "entry": dict(entry)})
        else:
            return jsonify({"error": "Entry not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@consciousness_bp.route("/knowledge/list", methods=["GET"])
@login_required
@admin_required
def list_knowledge():
    """List knowledge entries with filtering and pagination"""
    category = request.args.get("category")
    knowledge_type = request.args.get("type")
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))

    conn = get_db()
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

        cur.close()
        conn.close()

        return jsonify(
            {"success": True, "entries": [dict(e) for e in entries], "total": total, "limit": limit, "offset": offset}
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@consciousness_bp.route("/knowledge/categories", methods=["GET"])
@login_required
@admin_required
def get_categories():
    """Get all categories with counts"""
    conn = get_db()
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
        cur.close()
        conn.close()

        return jsonify({"success": True, "categories": [dict(c) for c in categories]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# TEAM AWARENESS ROUTES (Agent Management)
# ============================================================================


@consciousness_bp.route("/team")
@login_required
@admin_required
def team_awareness():
    """Team directory - all agents, performance, capabilities"""
    return render_template("tools/team_awareness.html")


@consciousness_bp.route("/team/agents", methods=["GET"])
@login_required
@admin_required
def get_agents():
    """Get all agents with their capabilities and metrics"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Query from agents table (the actual team members)
        cur.execute(
            """
            SELECT
                a.id,
                a.name,
                a.first_name,
                a.last_name,
                a.title,
                a.department,
                a.worker_type,
                a.status,
                a.tier,
                a.model,
                a.total_tasks_completed as tasks_completed,
                a.success_rate,
                a.total_tokens_used as tokens_used,
                a.total_cost,
                a.last_used,
                at.name as agent_type
            FROM agents a
            LEFT JOIN agent_types at ON a.type_id = at.id
            WHERE a.status = 'active'
            ORDER BY a.name
            LIMIT 50
        """
        )

        agents = cur.fetchall()

        # Convert to serializable format
        for agent in agents:
            if agent.get("last_used"):
                agent["last_used"] = agent["last_used"].isoformat()
            # Ensure worker_type has a default
            if not agent.get("worker_type"):
                agent["worker_type"] = "internal"
            # Calculate display name
            if agent.get("first_name") and agent.get("last_name"):
                agent["full_name"] = f"{agent['first_name']} {agent['last_name']}"
            else:
                agent["full_name"] = agent.get("name", "Unknown")
            # Ensure role fallback
            agent["role"] = agent.get("title") or agent.get("agent_type") or "Agent"

        cur.close()
        conn.close()

        return jsonify({"success": True, "agents": agents})
    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/team/agents/<int:agent_id>", methods=["GET"])
@login_required
@admin_required
def get_agent_details(agent_id):
    """Get detailed information about a specific agent"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM users WHERE id = %s AND is_agent = TRUE
        """,
            (agent_id,),
        )

        agent = cur.fetchone()

        if not agent:
            return jsonify({"error": "Agent not found"}), 404

        # Get recent tasks
        cur.execute(
            """
            SELECT * FROM agent_tasks
            WHERE agent_id = %s
            ORDER BY created_at DESC
            LIMIT 10
        """,
            (agent_id,),
        )

        recent_tasks = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"agent": agent, "recent_tasks": recent_tasks})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@consciousness_bp.route("/team/agents/<int:agent_id>/performance", methods=["GET"])
@login_required
@admin_required
def get_agent_performance(agent_id):
    """Get agent performance metrics"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                COUNT(*) as total_tasks,
                COUNT(*) FILTER (WHERE status = 'completed') as completed_tasks,
                COUNT(*) FILTER (WHERE status = 'failed') as failed_tasks,
                AVG(CASE WHEN completion_time IS NOT NULL
                    THEN EXTRACT(EPOCH FROM completion_time - created_at)
                    ELSE NULL END) as avg_completion_seconds
            FROM agent_tasks
            WHERE agent_id = %s
        """,
            (agent_id,),
        )

        performance = cur.fetchone()
        cur.close()
        conn.close()

        return jsonify(performance)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@consciousness_bp.route("/team/leaderboard", methods=["GET"])
@login_required
@admin_required
def performance_leaderboard():
    """Get agent performance leaderboard"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                u.id,
                u.username,
                u.full_name,
                COUNT(at.id) as total_tasks,
                COUNT(at.id) FILTER (WHERE at.status = 'completed') as completed_tasks,
                ROUND(AVG(CASE WHEN at.status = 'completed' THEN 1.0 ELSE 0.0 END)::numeric, 2) as success_rate
            FROM users u
            LEFT JOIN agent_tasks at ON u.id = at.agent_id
            WHERE u.is_agent = TRUE
            GROUP BY u.id
            ORDER BY success_rate DESC, completed_tasks DESC
            LIMIT 20
        """
        )

        leaderboard = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({"leaderboard": leaderboard})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@consciousness_bp.route("/team-awareness-data", methods=["GET"])
@login_required
@admin_required
def get_team_awareness_data():
    """Get A.R.C.H.I.E.'s team awareness - all agents and their details (ENHANCED)"""
    print("🧠 [BACKEND] get_team_awareness_data called - COMPREHENSIVE MODE")
    import psycopg2.extras

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Get all active agents with comprehensive details
        cur.execute(
            """
            SELECT
                a.id, a.name, a.first_name, a.last_name, a.email,
                a.title, a.department, a.pronouns, a.bio,
                a.tier, a.model, a.status,
                a.monthly_budget, a.total_cost, a.total_tokens_used,
                a.last_used, a.created_at,
                a.worker_type, a.requires_api_approval, a.api_provider,
                a.cost_tier, a.api_enabled, a.api_key_configured,
                at.name as agent_type, at.category as type_category
            FROM agents a
            LEFT JOIN agent_types at ON a.type_id = at.id
            WHERE a.status = 'active'
            ORDER BY a.department, a.first_name
        """
        )
        agents = cur.fetchall()

        # Get department summary
        cur.execute(
            """
            SELECT
                department,
                COUNT(*) as agent_count,
                SUM(CASE WHEN worker_type = 'internal' THEN 1 ELSE 0 END) as internal_count,
                SUM(CASE WHEN worker_type = 'contract' THEN 1 ELSE 0 END) as contract_count,
                SUM(monthly_budget) as total_budget,
                SUM(total_cost) as total_spent
            FROM agents
            WHERE status = 'active'
            GROUP BY department
            ORDER BY agent_count DESC
        """
        )
        departments = cur.fetchall()

        # Get overall statistics
        cur.execute(
            """
            SELECT
                COUNT(*) as total_agents,
                COUNT(DISTINCT department) as total_departments,
                SUM(monthly_budget) as total_budget,
                SUM(total_cost) as total_cost,
                SUM(total_tokens_used) as total_tokens,
                COUNT(CASE WHEN last_used >= NOW() - INTERVAL '7 days' THEN 1 END) as active_last_week,
                SUM(CASE WHEN worker_type = 'internal' THEN 1 ELSE 0 END) as internal_agents,
                SUM(CASE WHEN worker_type = 'contract' THEN 1 ELSE 0 END) as contract_agents,
                SUM(CASE WHEN worker_type = 'contract' AND api_enabled = TRUE THEN 1 ELSE 0 END) as contract_enabled,
                SUM(CASE WHEN worker_type = 'contract' AND api_enabled = FALSE THEN 1 ELSE 0 END) as contract_disabled
            FROM agents
            WHERE status = 'active'
        """
        )
        stats = cur.fetchone()

        # Organize agents by department
        by_department = {}
        for agent in agents:
            dept = agent["department"] or "Unassigned"
            if dept not in by_department:
                by_department[dept] = []
            by_department[dept].append(dict(agent))

        cur.close()
        conn.close()

        # Convert datetime objects to ISO format
        for agent in agents:
            if agent["last_used"]:
                agent["last_used"] = agent["last_used"].isoformat()
            if agent["created_at"]:
                agent["created_at"] = agent["created_at"].isoformat()

        result = {
            "success": True,
            "team": {
                "agents": [dict(a) for a in agents],
                "by_department": by_department,
                "departments": [dict(d) for d in departments],
                "statistics": dict(stats),
            },
        }

        print(f"🧠 [BACKEND] Returning {stats['total_agents']} agents across {stats['total_departments']} departments")
        return jsonify(result)

    except Exception as e:
        import traceback

        print("❌ [BACKEND] Error in get_team_awareness_data:")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# ANALYTICS ROUTES
# ============================================================================


@consciousness_bp.route("/analytics")
@login_required
@admin_required
def analytics():
    """Knowledge growth analytics dashboard"""
    return render_template("tools/consciousness_analytics.html")


@consciousness_bp.route("/analytics/knowledge-growth", methods=["GET"])
@login_required
@admin_required
def knowledge_growth():
    """Knowledge base growth metrics over time"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Growth by day (last 30 days)
        cur.execute(
            """
            SELECT
                DATE(created_at) as date,
                COUNT(*) as entries_added,
                knowledge_type
            FROM knowledge_base
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY DATE(created_at), knowledge_type
            ORDER BY date DESC
        """
        )

        growth_data = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({"growth_data": growth_data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@consciousness_bp.route("/improvements", methods=["GET"])
@login_required
@admin_required
def get_consciousness_improvements():
    """Get improvements tracked in consciousness (mistake_learned entries)"""

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT * FROM knowledge_base
            WHERE knowledge_type = 'mistake_learned'
            ORDER BY importance_score DESC, created_at DESC
        """
        )

        improvements = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({"improvements": improvements})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# CONVERSATION SESSIONS - ARCHIE'S MEMORY TIMELINE
# ============================================================================


@consciousness_bp.route("/sessions", methods=["GET"])
@login_required
@admin_required
def get_conversation_sessions():
    """Get all conversation sessions - ARCHIE's memory timeline"""

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get query parameters
        limit = request.args.get("limit", 50, type=int)
        phase = request.args.get("phase")
        topic = request.args.get("topic")

        sql = """
            SELECT
                cs.*,
                LENGTH(cs.full_transcript) as transcript_length,
                EXTRACT(EPOCH FROM (cs.compact_triggered_at - cs.started_at)) as session_duration_seconds,
                kb.id as knowledge_entry_id,
                kb.importance_score
            FROM conversation_sessions cs
            LEFT JOIN knowledge_base kb ON kb.source_id = cs.id::text
                AND kb.source_type = 'conversation_session'
            WHERE 1=1
        """
        params = []

        if phase:
            sql += " AND cs.phase = %s"
            params.append(phase)

        if topic:
            sql += " AND cs.primary_topic = %s"
            params.append(topic)

        sql += " ORDER BY cs.compact_triggered_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(sql, params)
        sessions = cur.fetchall()

        # Get summary stats
        cur.execute(
            """
            SELECT
                COUNT(*) as total_sessions,
                COUNT(DISTINCT phase) as unique_phases,
                COUNT(DISTINCT primary_topic) as unique_topics,
                SUM(LENGTH(full_transcript)) as total_characters,
                AVG(LENGTH(full_transcript)) as avg_characters,
                MIN(started_at) as first_session,
                MAX(compact_triggered_at) as latest_session
            FROM conversation_sessions
        """
        )
        stats = cur.fetchone()

        cur.close()
        conn.close()

        return jsonify({"sessions": sessions, "stats": stats, "count": len(sessions)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@consciousness_bp.route("/sessions/<int:session_id>", methods=["GET"])
@login_required
@admin_required
def get_session_detail(session_id):
    """Get full details of a specific conversation session"""

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT * FROM conversation_sessions WHERE id = %s
        """,
            (session_id,),
        )

        session = cur.fetchone()

        if not session:
            return jsonify({"error": "Session not found"}), 404

        # Get related knowledge entries
        cur.execute(
            """
            SELECT * FROM knowledge_base
            WHERE source_id = %s AND source_type = 'conversation_session'
        """,
            (str(session_id),),
        )

        knowledge_entries = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"session": session, "knowledge_entries": knowledge_entries})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# EMOTIONAL STATE TRACKING - ARCHIE'S FEELINGS OVER TIME
# ============================================================================


@consciousness_bp.route("/emotions/timeline", methods=["GET"])
@login_required
@admin_required
def get_emotional_timeline():
    """Get ARCHIE's emotional state over time with mood labels and stress data"""

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        days = request.args.get("days", 30, type=int)

        # Get emotional state history with mood labels
        cur.execute(
            """
            SELECT
                DATE(timestamp) as date,
                AVG(CASE WHEN current_mood = 'happy' THEN 1.0
                         WHEN current_mood = 'curious' THEN 0.8
                         WHEN current_mood = 'focused' THEN 0.6
                         WHEN current_mood = 'neutral' THEN 0.5
                         WHEN current_mood = 'confused' THEN 0.3
                         WHEN current_mood = 'frustrated' THEN 0.2
                         ELSE 0.5 END) as avg_mood_score,
                AVG(mood_intensity) as avg_energy,
                AVG(relationship_strength) as avg_confidence,
                COUNT(*) as measurement_count,
                MODE() WITHIN GROUP (ORDER BY current_mood) as dominant_mood
            FROM archie_emotional_state
            WHERE timestamp > NOW() - INTERVAL '%s days'
            GROUP BY DATE(timestamp)
            ORDER BY date DESC
        """,
            (days,),
        )
        timeline = cur.fetchall()

        # Get stress data from agent_emotional_state if available
        cur.execute(
            """
            SELECT
                DATE(timestamp) as date,
                AVG(stress_level) as avg_stress,
                AVG(energy_level) as avg_agent_energy
            FROM agent_emotional_state
            WHERE timestamp > NOW() - INTERVAL '%s days'
            GROUP BY DATE(timestamp)
            ORDER BY date DESC
        """,
            (days,),
        )
        stress_data = {str(r["date"]): r for r in cur.fetchall()}

        # Merge stress data into timeline
        for entry in timeline:
            date_key = str(entry["date"])
            if date_key in stress_data:
                entry["avg_stress"] = stress_data[date_key]["avg_stress"]
                entry["avg_agent_energy"] = stress_data[date_key]["avg_agent_energy"]

        # Get current emotional state
        cur.execute(
            """
            SELECT id, timestamp, current_mood as mood, mood_intensity as energy,
                   relationship_strength as confidence, user_id, notes
            FROM archie_emotional_state
            ORDER BY timestamp DESC LIMIT 1
        """
        )
        current_state = cur.fetchone()

        cur.close()
        conn.close()

        return jsonify({"timeline": timeline, "current_state": current_state})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# MEMORY GROWTH CHARTS - ARCHIE'S BRAIN EXPANSION
# ============================================================================


@consciousness_bp.route("/memory/growth", methods=["GET"])
@login_required
@admin_required
def get_memory_growth():
    """Get memory growth over time - ARCHIE's brain expansion"""

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        days = request.args.get("days", 30, type=int)

        # Growth by knowledge type
        cur.execute(
            """
            SELECT
                DATE(created_at) as date,
                knowledge_type,
                COUNT(*) as entries_added,
                AVG(importance_score) as avg_importance
            FROM knowledge_base
            WHERE created_at > NOW() - INTERVAL '%s days'
            GROUP BY DATE(created_at), knowledge_type
            ORDER BY date DESC, entries_added DESC
        """,
            (days,),
        )

        growth_by_type = cur.fetchall()

        # Growth by category
        cur.execute(
            """
            SELECT
                DATE(created_at) as date,
                category,
                COUNT(*) as entries_added
            FROM knowledge_base
            WHERE created_at > NOW() - INTERVAL '%s days'
              AND category IS NOT NULL
            GROUP BY DATE(created_at), category
            ORDER BY date DESC, entries_added DESC
        """,
            (days,),
        )

        growth_by_category = cur.fetchall()

        # Cumulative growth
        cur.execute(
            """
            WITH daily_additions AS (
                SELECT
                    DATE(created_at) as date,
                    COUNT(*) as daily_count
                FROM knowledge_base
                WHERE created_at > NOW() - INTERVAL '%s days'
                GROUP BY DATE(created_at)
            )
            SELECT
                date,
                daily_count,
                SUM(daily_count) OVER (ORDER BY date) as cumulative_count
            FROM daily_additions
            ORDER BY date
        """,
            (days,),
        )

        cumulative_growth = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {
                "growth_by_type": growth_by_type,
                "growth_by_category": growth_by_category,
                "cumulative_growth": cumulative_growth,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# TAGGED EXPERIENCES - ARCHIE'S CATEGORIZED MEMORIES
# ============================================================================


@consciousness_bp.route("/experiences", methods=["GET"])
@login_required
@admin_required
def get_tagged_experiences():
    """Get all tagged experiences - ARCHIE's categorized memories"""

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get all unique tags with counts
        cur.execute(
            """
            SELECT
                tag,
                COUNT(*) as usage_count,
                AVG(importance_score) as avg_importance,
                MAX(created_at) as last_used
            FROM knowledge_base, unnest(tags) as tag
            GROUP BY tag
            ORDER BY usage_count DESC
            LIMIT 100
        """
        )

        popular_tags = cur.fetchall()

        # Get tag co-occurrence (tags that appear together)
        cur.execute(
            """
            SELECT
                t1.tag as tag1,
                t2.tag as tag2,
                COUNT(*) as co_occurrence
            FROM
                knowledge_base kb,
                unnest(kb.tags) as t1(tag),
                unnest(kb.tags) as t2(tag)
            WHERE t1.tag < t2.tag
            GROUP BY t1.tag, t2.tag
            HAVING COUNT(*) > 2
            ORDER BY co_occurrence DESC
            LIMIT 50
        """
        )

        tag_relationships = cur.fetchall()

        # Get experiences by tag (most recent)
        tag_filter = request.args.get("tag")
        if tag_filter:
            cur.execute(
                """
                SELECT * FROM knowledge_base
                WHERE %s = ANY(tags)
                ORDER BY created_at DESC
                LIMIT 50
            """,
                (tag_filter,),
            )

            experiences = cur.fetchall()
        else:
            experiences = []

        cur.close()
        conn.close()

        return jsonify(
            {"popular_tags": popular_tags, "tag_relationships": tag_relationships, "experiences": experiences}
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# LEARNING PATTERNS - ARCHIE'S KNOWLEDGE ACQUISITION
# ============================================================================


@consciousness_bp.route("/learning-patterns", methods=["GET"])
@login_required
@admin_required
def get_learning_patterns():
    """Analyze ARCHIE's learning patterns"""

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Most accessed knowledge (what ARCHIE references most)
        cur.execute(
            """
            SELECT
                id,
                knowledge_type,
                title,
                content,
                category,
                tags,
                access_count,
                importance_score,
                last_accessed,
                created_at
            FROM knowledge_base
            WHERE access_count > 0
            ORDER BY access_count DESC
            LIMIT 20
        """
        )

        most_accessed = cur.fetchall()

        # Learning velocity (knowledge added per day)
        cur.execute(
            """
            SELECT
                DATE(created_at) as date,
                COUNT(*) as entries_added,
                AVG(importance_score) as avg_importance
            FROM knowledge_base
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """
        )

        learning_velocity = cur.fetchall()

        # Knowledge retention (old memories still accessed)
        cur.execute(
            """
            SELECT
                knowledge_type,
                COUNT(*) as total_entries,
                COUNT(*) FILTER (WHERE last_accessed > NOW() - INTERVAL '7 days') as accessed_recently,
                ROUND(AVG(EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400)::numeric, 1) as avg_age_days
            FROM knowledge_base
            GROUP BY knowledge_type
            ORDER BY total_entries DESC
        """
        )

        retention_by_type = cur.fetchall()

        # Importance distribution
        cur.execute(
            """
            SELECT
                CASE
                    WHEN importance_score >= 0.9 THEN 'Critical (0.9+)'
                    WHEN importance_score >= 0.7 THEN 'Important (0.7-0.9)'
                    WHEN importance_score >= 0.5 THEN 'Medium (0.5-0.7)'
                    ELSE 'Low (<0.5)'
                END as importance_category,
                COUNT(*) as count,
                knowledge_type
            FROM knowledge_base
            GROUP BY importance_category, knowledge_type
            ORDER BY
                CASE importance_category
                    WHEN 'Critical (0.9+)' THEN 1
                    WHEN 'Important (0.7-0.9)' THEN 2
                    WHEN 'Medium (0.5-0.7)' THEN 3
                    ELSE 4
                END,
                count DESC
        """
        )

        importance_distribution = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {
                "most_accessed": most_accessed,
                "learning_velocity": learning_velocity,
                "retention_by_type": retention_by_type,
                "importance_distribution": importance_distribution,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# GIT REPOSITORY TRACKING - WHAT ARCHIE WAS WORKING ON
# ============================================================================


@consciousness_bp.route("/work-context", methods=["GET"])
@login_required
@admin_required
def get_work_context():
    """Get ARCHIE's work context - Git branches, commits, phases"""

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Sessions by branch
        cur.execute(
            """
            SELECT
                git_branch,
                COUNT(*) as session_count,
                COUNT(DISTINCT phase) as phases_worked,
                COUNT(DISTINCT primary_topic) as topics_covered,
                MIN(started_at) as first_session,
                MAX(compact_triggered_at) as last_session
            FROM conversation_sessions
            WHERE git_branch IS NOT NULL AND git_branch != 'unknown'
            GROUP BY git_branch
            ORDER BY session_count DESC
        """
        )

        branch_activity = cur.fetchall()

        # Sessions by phase
        cur.execute(
            """
            SELECT
                phase,
                COUNT(*) as session_count,
                COUNT(DISTINCT git_branch) as branches_used,
                COUNT(DISTINCT primary_topic) as topics_covered,
                SUM(LENGTH(full_transcript)) as total_content
            FROM conversation_sessions
            GROUP BY phase
            ORDER BY session_count DESC
        """
        )

        phase_distribution = cur.fetchall()

        # Recent work sessions
        cur.execute(
            """
            SELECT
                cs.id,
                cs.session_name,
                cs.git_branch,
                cs.git_commit,
                cs.phase,
                cs.primary_topic,
                cs.compact_triggered_at,
                cs.processing_status,
                LENGTH(cs.full_transcript) as transcript_length
            FROM conversation_sessions cs
            ORDER BY cs.compact_triggered_at DESC
            LIMIT 20
        """
        )

        recent_work = cur.fetchall()

        # Topic distribution
        cur.execute(
            """
            SELECT
                primary_topic,
                COUNT(*) as session_count,
                AVG(LENGTH(full_transcript)) as avg_content_length
            FROM conversation_sessions
            WHERE primary_topic IS NOT NULL
            GROUP BY primary_topic
            ORDER BY session_count DESC
        """
        )

        topic_distribution = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {
                "branch_activity": branch_activity,
                "phase_distribution": phase_distribution,
                "recent_work": recent_work,
                "topic_distribution": topic_distribution,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# COMPREHENSIVE BRAIN STATE - EVERYTHING AT ONCE
# ============================================================================


@consciousness_bp.route("/brain-state", methods=["GET"])
@login_required
@admin_required
def get_complete_brain_state():
    """Get ARCHIE's complete brain state - all consciousness data"""

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
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
                   relationship_strength as confidence, user_id, notes
            FROM archie_emotional_state
            ORDER BY timestamp DESC LIMIT 1
        """
        )

        current_emotion = cur.fetchone()

        cur.close()
        conn.close()

        return jsonify(
            {
                "overall_stats": overall_stats,
                "knowledge_by_type": knowledge_by_type,
                "sessions_summary": sessions_summary,
                "recent_activity": recent_activity,
                "top_memories": top_memories,
                "current_emotion": current_emotion or {"mood": "neutral", "energy": 0.5, "confidence": 0.5},
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# DOCUMENT INGESTION ROUTES (migrated from admin)
# ============================================================================


@consciousness_bp.route("/ingest-directory", methods=["POST"])
@login_required
@admin_required
def ingest_directory():
    """Ingest documents from a directory into knowledge base"""
    import os
    import json
    from datetime import datetime

    data = request.json
    directory_path = data.get("path", "/mnt/archie_brain/docs")
    category = data.get("category", "documentation")

    conn = get_db()
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
                            (id, content, category, tags, source, importance, metadata, created_at)
                            VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s, NOW())
                            ON CONFLICT DO NOTHING
                        """,
                            (
                                content[:5000],  # Limit content size
                                category,
                                [subcategory, os.path.splitext(filename)[1][1:]],  # tags
                                f"file:{rel_path}",
                                0.7,  # importance
                                json.dumps({"filename": filename, "path": rel_path, "size": len(content)}),
                            ),
                        )

                        files_processed += 1
                    except Exception as e:
                        errors.append(f"{filename}: {str(e)}")

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "files_processed": files_processed, "errors": errors})
    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/browse-files", methods=["POST"])
@login_required
@admin_required
def browse_files():
    """Browse files in docs directory and show ingestion status"""
    import os
    import psycopg2.extras
    from datetime import datetime

    data = request.json
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
        conn = get_db()
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
                from datetime import datetime

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

        cur.close()
        conn.close()

        # Sort by name
        files_info.sort(key=lambda x: x["name"])

        return jsonify(
            {"success": True, "files": files_info, "total_files": len(files_info), "directory": directory_path}
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/view-file", methods=["POST"])
@login_required
@admin_required
def view_file():
    """View contents of a specific file"""
    import os

    data = request.json
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


@consciousness_bp.route("/ingest-all-docs", methods=["POST"])
@login_required
@admin_required
def ingest_all_docs():
    """DEPRECATED: Docs now live in knowledge_base table via docs_migration.py.

    Use Mission Control's Knowledge Base tab or run:
      docker exec archie_platform python3 /app/tools/blueprint/docs_migration.py

    This endpoint returns a deprecation notice and points to the knowledge_base table.
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM knowledge_base WHERE source_type = 'docs_migration'")
        kb_count = cur.fetchone()[0]
        cur.close()
        conn.close()

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


# ============================================================================
# UNIFIED KNOWLEDGE API (Phase 4: Integration Layer)
# ============================================================================


@consciousness_bp.route("/unified/search", methods=["POST"])
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
        result = service.search(query=query, knowledge_types=knowledge_types, categories=categories, limit=limit)

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/unified/stats", methods=["GET"])
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


@consciousness_bp.route("/unified/agent-context", methods=["POST"])
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
            return jsonify({"success": False, "error": "Task description required"}), 400

        service = get_unified_knowledge_service()
        context = service.get_agent_context(task_description, agent_type)

        return jsonify({"success": True, "context": context})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/unified/check-mistakes", methods=["POST"])
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
            {"success": True, "mistakes": mistakes, "count": len(mistakes), "has_warnings": len(mistakes) > 0}
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
            error_type=error_type, error_message=error_message, solution=solution, context=context, tags=tags
        )

        if entry_id:
            return jsonify({"success": True, "entry_id": entry_id, "message": f"Mistake recorded as entry #{entry_id}"})
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

        return jsonify({"success": True, "activity": activity, "count": len(activity), "hours": hours})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# KNOWLEDGE GRAPH & BACKLINKS (Migrated from Obsidian)
# ============================================================================


@consciousness_bp.route("/knowledge/graph", methods=["GET"])
@login_required
@admin_required
def get_knowledge_graph():
    """
    Get knowledge link graph for D3.js visualization.
    Returns nodes and edges of all knowledge connections.
    """
    try:
        from knowledge_vault_indexer import KnowledgeVaultIndexer

        limit = request.args.get("limit", 100, type=int)

        indexer = KnowledgeVaultIndexer()
        graph = indexer.get_link_graph(limit=limit)

        return jsonify(
            {
                "success": True,
                "graph": graph,
                "node_count": len(graph.get("nodes", [])),
                "edge_count": len(graph.get("edges", [])),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/knowledge/<int:knowledge_id>/backlinks", methods=["GET"])
@login_required
@admin_required
def get_knowledge_backlinks(knowledge_id):
    """
    Get all knowledge entries that link to this entry.
    Essential for understanding how knowledge is interconnected.
    """
    try:
        from knowledge_vault_indexer import KnowledgeVaultIndexer

        indexer = KnowledgeVaultIndexer()
        backlinks = indexer.get_backlinks(knowledge_id)

        return jsonify({"success": True, "knowledge_id": knowledge_id, "backlinks": backlinks, "count": len(backlinks)})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# TEAM AWARENESS API (migrated from admin)
# ============================================================================


@consciousness_bp.route("/team-awareness", methods=["GET"])
@login_required
@admin_required
def get_team_awareness():
    """Get A.R.C.H.I.E.'s team awareness - all agents and their details"""
    print("🧠 [BACKEND] get_team_awareness called")
    import psycopg2.extras

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Get all active agents
        cur.execute(
            """
            SELECT
                a.id, a.name, a.first_name, a.last_name, a.email,
                a.title, a.department, a.pronouns, a.bio,
                a.tier, a.model, a.status,
                a.monthly_budget, a.total_cost, a.total_tokens_used,
                a.last_used, a.created_at,
                a.worker_type, a.requires_api_approval, a.api_provider,
                a.cost_tier, a.api_enabled, a.api_key_configured,
                at.name as agent_type, at.category as type_category
            FROM agents a
            LEFT JOIN agent_types at ON a.type_id = at.id
            WHERE a.status = 'active'
            ORDER BY a.department, a.first_name
        """
        )
        agents = cur.fetchall()

        # Get department summary
        cur.execute(
            """
            SELECT
                department,
                COUNT(*) as agent_count,
                SUM(CASE WHEN worker_type = 'internal' THEN 1 ELSE 0 END) as internal_count,
                SUM(CASE WHEN worker_type = 'contract' THEN 1 ELSE 0 END) as contract_count,
                SUM(monthly_budget) as total_budget,
                SUM(total_cost) as total_spent
            FROM agents
            WHERE status = 'active'
            GROUP BY department
            ORDER BY agent_count DESC
        """
        )
        departments = cur.fetchall()

        # Get overall statistics
        cur.execute(
            """
            SELECT
                COUNT(*) as total_agents,
                COUNT(DISTINCT department) as total_departments,
                SUM(monthly_budget) as total_budget,
                SUM(total_cost) as total_cost,
                SUM(total_tokens_used) as total_tokens,
                COUNT(CASE WHEN last_used >= NOW() - INTERVAL '7 days' THEN 1 END) as active_last_week,
                SUM(CASE WHEN worker_type = 'internal' THEN 1 ELSE 0 END) as internal_agents,
                SUM(CASE WHEN worker_type = 'contract' THEN 1 ELSE 0 END) as contract_agents,
                SUM(CASE WHEN worker_type = 'contract' AND api_enabled = TRUE THEN 1 ELSE 0 END) as contract_enabled,
                SUM(CASE WHEN worker_type = 'contract' AND api_enabled = FALSE THEN 1 ELSE 0 END) as contract_disabled
            FROM agents
            WHERE status = 'active'
        """
        )
        stats = cur.fetchone()

        # Organize agents by department
        by_department = {}
        for agent in agents:
            dept = agent["department"] or "Unassigned"
            if dept not in by_department:
                by_department[dept] = []
            by_department[dept].append(dict(agent))

        cur.close()
        conn.close()

        # Convert datetime objects to ISO format
        for agent in agents:
            if agent["last_used"]:
                agent["last_used"] = agent["last_used"].isoformat()
            if agent["created_at"]:
                agent["created_at"] = agent["created_at"].isoformat()

        result = {
            "success": True,
            "team": {
                "agents": [dict(a) for a in agents],
                "by_department": by_department,
                "departments": [dict(d) for d in departments],
                "statistics": dict(stats),
            },
        }

        print(f"🧠 [BACKEND] Returning {stats['total_agents']} agents across {stats['total_departments']} departments")
        return jsonify(result)

    except Exception as e:
        import traceback

        print("❌ [BACKEND] Error in get_team_awareness:")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


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
                WHERE created_at >= NOW() - INTERVAL '%s hours'
                ORDER BY created_at DESC
                LIMIT %s
            """,
                (hours, limit),
            )
            knowledge_events = cur.fetchall()
            for event in knowledge_events:
                event["created_at"] = event["created_at"].isoformat() if event["created_at"] else None
                activities.append(dict(event))

        # 2. Recent agent executions
        if not event_type or event_type == "execution":
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
                WHERE ae.started_at >= NOW() - INTERVAL '%s hours'
                ORDER BY ae.started_at DESC
                LIMIT %s
            """,
                (hours, limit),
            )
            execution_events = cur.fetchall()
            for event in execution_events:
                event["created_at"] = event["created_at"].isoformat() if event["created_at"] else None
                activities.append(dict(event))

        # 3. Recent improvement proposals
        if not event_type or event_type == "improvement":
            cur.execute(
                """
                SELECT
                    id,
                    'improvement' as event_type,
                    title,
                    status as subtype,
                    priority,
                    complexity,
                    created_at,
                    CASE
                        WHEN status = 'proposed' THEN 'New improvement proposed'
                        WHEN status = 'approved' THEN 'Improvement approved'
                        WHEN status = 'in_progress' THEN 'Improvement in progress'
                        WHEN status = 'completed' THEN 'Improvement completed'
                        WHEN status = 'rejected' THEN 'Improvement rejected'
                        ELSE 'Improvement ' || status
                    END as description
                FROM improvement_proposals
                WHERE created_at >= NOW() - INTERVAL '%s hours'
                ORDER BY created_at DESC
                LIMIT %s
            """,
                (hours, limit),
            )
            improvement_events = cur.fetchall()
            for event in improvement_events:
                event["created_at"] = event["created_at"].isoformat() if event["created_at"] else None
                activities.append(dict(event))

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
                WHERE started_at >= NOW() - INTERVAL '%s hours'
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
                    mood_intensity as energy,
                    relationship_strength as confidence,
                    timestamp as created_at,
                    'Mood: ' || current_mood || ' (Energy: ' || ROUND(mood_intensity::numeric, 2) || ')' as description
                FROM archie_emotional_state
                WHERE timestamp >= NOW() - INTERVAL '%s hours'
                ORDER BY timestamp DESC
                LIMIT %s
            """,
                (hours, limit),
            )
            emotional_events = cur.fetchall()
            for event in emotional_events:
                event["created_at"] = event["created_at"].isoformat() if event["created_at"] else None
                activities.append(dict(event))

        # 6. LLM alerts (from Phase 27)
        if not event_type or event_type == "llm_alert":
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
                WHERE created_at >= NOW() - INTERVAL '%s hours'
                ORDER BY created_at DESC
                LIMIT %s
            """,
                (hours, limit),
            )
            llm_events = cur.fetchall()
            for event in llm_events:
                event["created_at"] = event["created_at"].isoformat() if event["created_at"] else None
                activities.append(dict(event))

        # 7. Project activity
        if not event_type or event_type == "project":
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
                WHERE created_at >= NOW() - INTERVAL '%s hours'
                ORDER BY created_at DESC
                LIMIT %s
            """,
                (hours, limit),
            )
            project_events = cur.fetchall()
            for event in project_events:
                event["created_at"] = event["created_at"].isoformat() if event["created_at"] else None
                activities.append(dict(event))

        # 8. Work sessions
        if not event_type or event_type == "work_session":
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
                WHERE started_at >= NOW() - INTERVAL '%s hours'
                ORDER BY started_at DESC
                LIMIT %s
            """,
                (hours, limit),
            )
            session_events = cur.fetchall()
            for event in session_events:
                event["created_at"] = event["created_at"].isoformat() if event["created_at"] else None
                activities.append(dict(event))

        cur.close()
        conn.close()

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
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/activity-stats")
@login_required
@admin_required
def get_activity_stats():
    """Get activity statistics for the dashboard"""
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
                   relationship_strength as confidence, timestamp
            FROM archie_emotional_state
            ORDER BY timestamp DESC
            LIMIT 1
        """
        )
        emotional = cur.fetchone()

        # Get LLM health summary
        cur.execute(
            """
            SELECT
                COUNT(CASE WHEN status = 'online' THEN 1 END) as online,
                COUNT(CASE WHEN status = 'offline' THEN 1 END) as offline,
                COUNT(CASE WHEN status = 'degraded' THEN 1 END) as degraded,
                COUNT(*) as total
            FROM llm_connections
        """
        )
        llm_health = cur.fetchone()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "stats": dict(stats) if stats else {},
                "emotional_state": (
                    dict(emotional) if emotional else {"mood": "neutral", "energy": 0.8, "confidence": 0.8}
                ),
                "llm_health": dict(llm_health) if llm_health else {},
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


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
    print(f"Memory service not available: {e}")


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

        return (
            jsonify(
                {"success": True, "memory_id": memory_id, "source": "agent_memory" if agent_id else "long_term_memory"}
            )
            if memory_id
            else jsonify({"success": False, "error": "Failed to record"})
        ), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/save-conversation", methods=["POST"])
@login_required
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
            from .memory_service import store_embedding

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
            print(f"Embedding generation failed (non-critical): {embed_err}")

        cur.close()
        conn.close()

        return jsonify({"success": True, "memory_id": memory_id, "title": title, "message_count": len(messages)})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# GITHUB LEARNING INTEGRATION
# ============================================================================

# Extensions worth downloading and indexing
INDEXABLE_CODE_EXT = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".java",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".go",
    ".rs",
    ".rb",
    ".sh",
    ".bash",
    ".sql",
    ".php",
    ".swift",
    ".kt",
    ".scala",
    ".vue",
    ".svelte",
    ".lua",
    ".r",
    ".cs",
}
INDEXABLE_DOC_EXT = {".md", ".txt", ".rst", ".adoc"}
INDEXABLE_CONFIG_EXT = {".json", ".yaml", ".yml", ".toml", ".ini", ".conf", ".env"}
INDEXABLE_WEB_EXT = {".html", ".css", ".scss", ".less"}
INDEXABLE_EXT = INDEXABLE_CODE_EXT | INDEXABLE_DOC_EXT | INDEXABLE_CONFIG_EXT | INDEXABLE_WEB_EXT

SKIP_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    "env",
    ".env",
    "dist",
    "build",
    "coverage",
    ".tox",
    "target",
    ".idea",
    ".vscode",
    ".mypy_cache",
    ".pytest_cache",
    ".eggs",
    "egg-info",
    ".next",
    ".nuxt",
    "vendor",
    "bower_components",
    ".gradle",
    ".mvn",
}

SKIP_FILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "composer.lock",
    "Gemfile.lock",
    "Cargo.lock",
    "poetry.lock",
    "Pipfile.lock",
}

MAX_FILE_SIZE = 500_000  # 500 KB per file
MAX_CONTENT_STORE = 100_000  # 100 KB stored in DB
MAX_FILES_PER_REPO = 500  # cap per repo


def _get_github_headers():
    """Return (headers_dict, has_token) for GitHub API requests."""
    github_token = None
    try:
        token_path = "/mnt/archie_brain/secrets/api/github_token.txt"
        if os.path.exists(token_path):
            with open(token_path, "r") as f:
                github_token = f.read().strip()
    except Exception:
        pass
    if not github_token:
        github_token = os.environ.get("GITHUB_TOKEN")

    headers = {"Accept": "application/vnd.github.v3+json"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    return headers, bool(github_token)


@consciousness_bp.route("/github/index-selective", methods=["POST"])
@login_required
@admin_required
def github_index_selective():
    """
    Index specific files/folders from a GitHub repo with semantic embeddings
    This allows ARCHIE to learn from GitHub repositories with higher priority
    """
    import requests
    import base64

    data = request.get_json() or {}
    repo_url = data.get("repo_url", "").strip()
    paths = data.get("paths", [])
    priority = data.get("priority", "high")  # high, medium, low

    if not repo_url:
        return jsonify({"success": False, "error": "Repository URL required"}), 400

    # Parse GitHub URL
    # Formats: https://github.com/user/repo or github.com/user/repo
    try:
        parts = repo_url.replace("https://", "").replace("http://", "").replace("github.com/", "").split("/")
        owner = parts[0]
        repo = parts[1].replace(".git", "")
    except Exception:
        return jsonify({"success": False, "error": "Invalid GitHub URL format"}), 400

    # Priority mapping
    priority_scores = {"high": 0.95, "medium": 0.85, "low": 0.75}
    importance = priority_scores.get(priority, 0.85)

    headers, _has_token = _get_github_headers()

    # If no paths specified, use the recursive tree API for full repo index
    if not paths:
        try:
            # Look up repo_type from github_repositories
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT repo_type FROM github_repositories WHERE repo_name LIKE %s LIMIT 1",
                (f"%{owner}/{repo}%",),
            )
            row = cur.fetchone()
            repo_type = row["repo_type"] if row else repo.lower()
            cur.close()
            conn.close()

            indexed_count, errors, skipped = _reindex_repo_via_tree(owner, repo, repo_type, importance)
            return jsonify(
                {
                    "success": True,
                    "indexed_count": indexed_count,
                    "repo": f"{owner}/{repo}",
                    "priority": priority,
                    "skipped": skipped,
                    "errors": errors if errors else None,
                }
            )
        except Exception as e:
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500

    # Paths specified — use Contents API for targeted indexing
    indexed_count = 0
    errors = []

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        for path in paths:
            path = path.strip().strip("/")

            # Get contents from GitHub API
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
            response = requests.get(api_url, headers=headers, timeout=30)

            if response.status_code != 200:
                errors.append(f"Failed to fetch {path}: {response.status_code}")
                continue

            contents = response.json()

            # Handle single file vs directory
            if isinstance(contents, dict):
                contents = [contents]

            for item in contents:
                if item.get("type") == "file":
                    file_url = item.get("download_url")
                    if not file_url:
                        continue

                    try:
                        file_response = requests.get(file_url, timeout=30)
                        if file_response.status_code != 200:
                            continue

                        file_content = file_response.text
                        file_path_val = item.get("path", "")
                        file_name = item.get("name", "")

                        if len(file_content) > MAX_FILE_SIZE:
                            continue

                        ext = os.path.splitext(file_name)[1].lower()

                        cur.execute(
                            """
                            INSERT INTO knowledge_base (
                                knowledge_type, title, content, category, file_path,
                                importance_score, source_type, file_name, file_extension,
                                memory_metadata, tags, repo_type, created_at
                            ) VALUES (
                                'github_file', %s, %s, 'github', %s,
                                %s, 'github_selective', %s, %s,
                                %s, %s, %s, NOW()
                            )
                            ON CONFLICT (file_path) WHERE source_type = 'github_selective'
                            DO UPDATE SET
                                content = EXCLUDED.content,
                                importance_score = EXCLUDED.importance_score,
                                updated_at = NOW()
                            RETURNING id
                        """,
                            (
                                file_name,
                                file_content[:MAX_CONTENT_STORE],
                                f"{owner}/{repo}/{file_path_val}",
                                importance,
                                file_name,
                                ext,
                                json.dumps(
                                    {
                                        "repo": f"{owner}/{repo}",
                                        "priority": priority,
                                        "indexed_by": current_user.username,
                                        "sha": item.get("sha"),
                                        "size": item.get("size"),
                                    }
                                ),
                                ["github", "selective", owner, repo, priority],
                                repo.lower(),
                            ),
                        )

                        result = cur.fetchone()
                        if result:
                            indexed_count += 1

                    except Exception as file_err:
                        errors.append(f"Error processing {item.get('name')}: {str(file_err)}")

                elif item.get("type") == "dir":
                    # Recurse into directories
                    paths.append(item.get("path", ""))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "indexed_count": indexed_count,
                "repo": f"{owner}/{repo}",
                "priority": priority,
                "errors": errors if errors else None,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


def _reindex_repo_via_tree(owner, repo, repo_type, importance=0.85):
    """
    Recursively index a GitHub repo using the Tree API (1 API call for full tree).
    Downloads content via raw.githubusercontent.com (no API quota).
    Returns (indexed_count, errors, skipped_count).
    """
    import requests
    import time

    headers, _has_token = _get_github_headers()
    errors = []

    # 1. Get default branch
    repo_api = f"https://api.github.com/repos/{owner}/{repo}"
    resp = requests.get(repo_api, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"Failed to fetch repo info for {owner}/{repo}: {resp.status_code}")
    default_branch = resp.json().get("default_branch", "main")

    # 2. Get full tree recursively (1 API call)
    tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1"
    resp = requests.get(tree_url, headers=headers, timeout=60)
    if resp.status_code != 200:
        raise Exception(f"Failed to fetch tree for {owner}/{repo}: {resp.status_code}")
    tree_data = resp.json()
    all_items = tree_data.get("tree", [])

    # 3. Filter blobs only, skip unwanted dirs/files, only indexable extensions
    candidates = []
    for item in all_items:
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")
        size = item.get("size", 0)
        filename = os.path.basename(path)
        ext = os.path.splitext(filename)[1].lower()

        # Skip by extension
        if ext not in INDEXABLE_EXT:
            continue

        # Skip by size
        if size > MAX_FILE_SIZE:
            continue

        # Skip by directory
        path_parts = path.split("/")
        if any(part in SKIP_DIRS for part in path_parts[:-1]):
            continue

        # Skip by filename
        if filename in SKIP_FILES:
            continue

        candidates.append((path, filename, ext, size))

    # 4. Sort by priority: README first, then code, then docs, then config
    def sort_key(item):
        _path, fname, ext, _size = item
        if fname.lower().startswith("readme"):
            return (0, _path)
        if ext in INDEXABLE_CODE_EXT:
            return (1, _path)
        if ext in INDEXABLE_DOC_EXT:
            return (2, _path)
        return (3, _path)

    candidates.sort(key=sort_key)
    candidates = candidates[:MAX_FILES_PER_REPO]

    # 5. Delete old entries for this repo
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "DELETE FROM knowledge_base WHERE knowledge_type = 'github_file' AND repo_type = %s",
        (repo_type,),
    )
    deleted = cur.rowcount
    conn.commit()

    # 6. Download and insert each file
    indexed_count = 0
    skipped_count = 0
    raw_base = f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}"

    for path, filename, ext, size in candidates:
        try:
            raw_url = f"{raw_base}/{path}"
            file_resp = requests.get(raw_url, timeout=30)
            if file_resp.status_code != 200:
                errors.append(f"Download failed ({file_resp.status_code}): {path}")
                skipped_count += 1
                continue

            content = file_resp.text
            if len(content) > MAX_FILE_SIZE:
                skipped_count += 1
                continue

            # Use repo-qualified title to avoid unique constraint collisions
            title = f"{owner}/{repo}: {path}"

            cur.execute("SAVEPOINT sp_file")
            cur.execute(
                """
                INSERT INTO knowledge_base (
                    knowledge_type, title, content, category, file_path,
                    importance_score, source_type, file_name, file_extension,
                    memory_metadata, tags, repo_type, created_at
                ) VALUES (
                    'github_file', %s, %s, 'github', %s,
                    %s, 'github_tree', %s, %s,
                    %s, %s, %s, NOW()
                )
                """,
                (
                    title,
                    content[:MAX_CONTENT_STORE],
                    f"{owner}/{repo}/{path}",
                    importance,
                    filename,
                    ext,
                    json.dumps(
                        {
                            "repo": f"{owner}/{repo}",
                            "branch": default_branch,
                            "size": size,
                        }
                    ),
                    ["github", owner, repo, repo_type],
                    repo_type,
                ),
            )
            cur.execute("RELEASE SAVEPOINT sp_file")
            indexed_count += 1

            # Polite delay between downloads
            if indexed_count % 10 == 0:
                time.sleep(0.05)

        except Exception as file_err:
            cur.execute("ROLLBACK TO SAVEPOINT sp_file")
            errors.append(f"Error: {path}: {str(file_err)}")
            skipped_count += 1

    conn.commit()

    # 7. Update github_repositories row
    cur.execute(
        """
        UPDATE github_repositories
        SET indexed = true, indexed_files = %s, indexed_at = NOW(),
            status = 'indexed', updated_at = NOW()
        WHERE repo_type = %s
        """,
        (indexed_count, repo_type),
    )
    conn.commit()
    cur.close()
    conn.close()

    return indexed_count, errors, skipped_count


@consciousness_bp.route("/github/reindex-all", methods=["POST"])
@login_required
@admin_required
def github_reindex_all():
    """Re-index all tracked repositories using the Tree API."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, repo_name, repo_type FROM github_repositories ORDER BY id")
        repos = cur.fetchall()
        cur.close()
        conn.close()

        results = []
        total_indexed = 0
        total_errors = []

        for repo_row in repos:
            repo_name = repo_row["repo_name"]
            repo_type = repo_row["repo_type"]
            try:
                parts = repo_name.split("/")
                owner = parts[0]
                repo = parts[1]
                indexed, errs, skipped = _reindex_repo_via_tree(owner, repo, repo_type)
                total_indexed += indexed
                total_errors.extend(errs)
                results.append(
                    {
                        "repo": repo_name,
                        "repo_type": repo_type,
                        "indexed": indexed,
                        "skipped": skipped,
                        "errors": len(errs),
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "repo": repo_name,
                        "repo_type": repo_type,
                        "indexed": 0,
                        "error": str(e),
                    }
                )
                total_errors.append(f"{repo_name}: {str(e)}")

        return jsonify(
            {
                "success": True,
                "total_indexed": total_indexed,
                "total_repos": len(repos),
                "results": results,
                "errors": total_errors if total_errors else None,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/github/reindex/<int:repo_id>", methods=["POST"])
@login_required
@admin_required
def github_reindex_single(repo_id):
    """Re-index a single tracked repository using the Tree API."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, repo_name, repo_type FROM github_repositories WHERE id = %s", (repo_id,))
        repo_row = cur.fetchone()
        cur.close()
        conn.close()

        if not repo_row:
            return jsonify({"success": False, "error": "Repository not found"}), 404

        repo_name = repo_row["repo_name"]
        repo_type = repo_row["repo_type"]
        parts = repo_name.split("/")
        owner = parts[0]
        repo = parts[1]

        indexed, errs, skipped = _reindex_repo_via_tree(owner, repo, repo_type)
        return jsonify(
            {
                "success": True,
                "repo": repo_name,
                "indexed": indexed,
                "skipped": skipped,
                "errors": errs if errs else None,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/github/repositories", methods=["GET"])
@login_required
@admin_required
def github_repositories():
    """List tracked GitHub repositories with their status"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT gr.id, gr.repo_name, gr.repo_type, gr.status, gr.indexed,
                   gr.indexed_files, gr.cloned_at, gr.updated_at, gr.indexed_at,
                   (SELECT COUNT(*) FROM knowledge_base kb
                    WHERE kb.knowledge_type = 'github_file'
                    AND kb.repo_type = gr.repo_type) as actual_file_count
            FROM github_repositories gr
            ORDER BY gr.updated_at DESC
        """
        )
        repos = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "repositories": [dict(r) for r in repos], "count": len(repos)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/github/repositories/<int:repo_id>", methods=["DELETE"])
@login_required
@admin_required
def github_repository_delete(repo_id):
    """Delete a tracked repository and its indexed files. Use ?preview=true for impact summary."""
    preview = request.args.get("preview", "").lower() == "true"
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get repo info
        cur.execute("SELECT id, repo_name, repo_type FROM github_repositories WHERE id = %s", (repo_id,))
        repo = cur.fetchone()
        if not repo:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Repository not found"}), 404

        repo = dict(repo)
        repo_type = repo["repo_type"]

        # Get impact: count files that would be deleted
        cur.execute(
            """
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN is_code THEN 1 ELSE 0 END) as code_files,
                   SUM(CASE WHEN is_documentation THEN 1 ELSE 0 END) as doc_files
            FROM knowledge_base
            WHERE knowledge_type = 'github_file' AND repo_type = %s
            """,
            (repo_type,),
        )
        impact = dict(cur.fetchone())

        if preview:
            cur.close()
            conn.close()
            return jsonify({"success": True, "preview": True, "repo": repo, "impact": impact})

        # Actually delete
        cur.execute(
            "DELETE FROM knowledge_base WHERE knowledge_type = 'github_file' AND repo_type = %s",
            (repo_type,),
        )
        deleted_files = cur.rowcount
        cur.execute("DELETE FROM github_repositories WHERE id = %s", (repo_id,))
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "deleted_files": deleted_files, "repo_name": repo["repo_name"]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/github/indexed", methods=["GET"])
@login_required
@admin_required
def github_indexed_list():
    """List all selectively indexed GitHub content. Optional ?file_type=code|docs to filter."""
    file_type = request.args.get("file_type", "").lower()
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        base_where = "(source_type = 'github_selective' OR knowledge_type = 'github_file')"
        if file_type == "code":
            base_where += " AND is_code = true"
        elif file_type == "docs":
            base_where += " AND is_documentation = true"

        cur.execute(
            f"""
            SELECT id, title, file_path, importance_score, has_embedding,
                   memory_metadata, created_at, updated_at, knowledge_type,
                   is_code, is_documentation, repo_type
            FROM knowledge_base
            WHERE {base_where}
            ORDER BY created_at DESC
            LIMIT 200
        """
        )
        items = cur.fetchall()

        # Get stats
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN has_embedding THEN 1 ELSE 0 END) as with_embeddings,
                (SELECT COUNT(*) FROM github_repositories) as repos,
                SUM(CASE WHEN is_code THEN 1 ELSE 0 END) as code_files,
                SUM(CASE WHEN is_documentation THEN 1 ELSE 0 END) as docs
            FROM knowledge_base
            WHERE source_type = 'github_selective' OR knowledge_type = 'github_file'
        """
        )
        stats = cur.fetchone()

        cur.close()
        conn.close()

        items_list = [dict(i) for i in items]
        return jsonify(
            {
                "success": True,
                "items": items_list,
                "files": items_list,  # Alias for frontend compatibility
                "stats": dict(stats) if stats else {},
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/github/search-semantic", methods=["POST"])
@login_required
def github_search_semantic():
    """Semantic search across indexed GitHub files"""
    data = request.get_json() or {}
    query = data.get("query", "").strip()
    limit = data.get("limit", 10)

    if not query:
        return jsonify({"success": False, "error": "Query required"}), 400

    try:
        from .memory_service import semantic_search

        results = semantic_search(query, source_types=["knowledge_base"], limit=limit, min_similarity=0.5)

        # Filter to github files only
        github_results = [
            r for r in results if r.get("knowledge_type") == "github_file" or r.get("source_type") == "github_selective"
        ]

        return jsonify({"success": True, "results": github_results, "count": len(github_results)})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# DEPENDENCY SCANNER ENDPOINTS
# ============================================================================


def _store_dependency_scan(cursor, scan_result):
    """Store scan results as upgrade_suggestion entries in knowledge_base.

    Only stores packages that have updates OR vulnerabilities.
    Deletes old suggestions for same package+source before inserting.
    """
    source = scan_result.get("source", "unknown")
    stored = 0

    for dep in scan_result.get("dependencies", []):
        has_vulns = bool(dep.get("vulnerabilities"))
        has_update = dep.get("has_update", False)
        is_deprecated = bool(dep.get("deprecated"))

        if not has_update and not has_vulns and not is_deprecated:
            continue

        pkg = dep["package"]
        ecosystem = dep["ecosystem"]

        # Determine severity and importance score
        severities = [v["severity"] for v in dep.get("vulnerabilities", [])]
        if "CRITICAL" in severities:
            severity = "critical"
            importance = 0.95
        elif "HIGH" in severities:
            severity = "high"
            importance = 0.90
        elif "MEDIUM" in severities:
            severity = "medium"
            importance = 0.80
        elif is_deprecated:
            severity = "high"
            importance = 0.85
        else:
            severity = "low"
            importance = 0.75

        # Build markdown content
        lines = [f"## {pkg} ({ecosystem})"]
        lines.append(f"**Source:** {source}")
        if dep["current_version"]:
            lines.append(f"**Current:** {dep['current_version']}")
        if dep["latest_version"]:
            lines.append(f"**Latest:** {dep['latest_version']}")
        if is_deprecated:
            lines.append(f"**DEPRECATED:** {dep['deprecated']}")
        if has_vulns:
            lines.append(f"\n### Vulnerabilities ({len(dep['vulnerabilities'])})")
            for v in dep["vulnerabilities"]:
                lines.append(f"- **{v['severity']}** [{v['id']}]: {v.get('summary', '')}")
                if v.get("patched_version"):
                    lines.append(f"  - Patched in: {v['patched_version']}")

        content = "\n".join(lines)
        # Include source in title to avoid unique constraint collisions across repos
        source_label = source.split("/")[-1] if "/" in source else source
        title = (
            f"[{severity.upper()}] {pkg} {dep['current_version']} → {dep['latest_version']} ({source_label})"
            if has_update
            else f"[{severity.upper()}] {pkg} - vulnerability ({source_label})"
        )

        metadata = json.dumps(
            {
                "severity": severity,
                "ecosystem": ecosystem,
                "package": pkg,
                "current_version": dep["current_version"],
                "latest_version": dep["latest_version"],
                "has_update": has_update,
                "deprecated": dep.get("deprecated"),
                "vulnerability_count": len(dep.get("vulnerabilities", [])),
                "vulnerabilities": dep.get("vulnerabilities", []),
                "scan_source": source,
                "scanned_at": scan_result.get("scanned_at"),
            }
        )

        # Delete old suggestion for same package+source
        cursor.execute(
            """DELETE FROM knowledge_base
               WHERE knowledge_type = 'upgrade_suggestion'
                 AND memory_metadata->>'package' = %s
                 AND memory_metadata->>'scan_source' = %s""",
            (pkg, source),
        )

        cursor.execute(
            """INSERT INTO knowledge_base
               (title, content, knowledge_type, source_type, primary_category,
                importance_score, memory_metadata, created_at)
               VALUES (%s, %s, 'upgrade_suggestion', 'dependency_scan', 'dependency_security',
                       %s, %s, NOW())""",
            (title, content, importance, metadata),
        )
        stored += 1

    return stored


@consciousness_bp.route("/github/scan-dependencies", methods=["POST"])
@login_required
@admin_required
def github_scan_dependencies():
    """Scan GitHub repos for dependency updates and vulnerabilities."""
    from .dependency_scanner import DependencyScanner

    data = request.get_json() or {}
    repo_id = data.get("repo_id")
    include_platform = data.get("include_platform", True)

    # Load GitHub token from env or file
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        try:
            with open("/mnt/archie_brain/secrets/api/github_token.txt", "r") as f:
                github_token = f.read().strip()
        except FileNotFoundError:
            pass

    scanner = DependencyScanner(github_token=github_token)
    results_summary = {
        "scans_performed": 0,
        "entries_created": 0,
        "total_updates": 0,
        "total_vulnerabilities": 0,
        "critical_count": 0,
        "scan_details": [],
    }

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get repos to scan
        if repo_id:
            cur.execute(
                "SELECT id, repo_name FROM github_repositories WHERE id = %s",
                (repo_id,),
            )
        else:
            cur.execute("SELECT id, repo_name FROM github_repositories WHERE status IN ('cloned', 'indexed')")
        repos = cur.fetchall()

        dep_files = ["package.json", "requirements.txt"]

        for repo in repos:
            repo_name = repo["repo_name"]
            # repo_name is already in owner/repo format
            owner_repo = repo_name

            headers = {}
            if github_token:
                headers["Authorization"] = f"Bearer {github_token}"
                headers["Accept"] = "application/vnd.github.v3+json"

            for dep_file in dep_files:
                try:
                    resp = requests.get(
                        f"https://api.github.com/repos/{owner_repo}/contents/{dep_file}",
                        headers=headers,
                        timeout=10,
                    )
                    if resp.status_code != 200:
                        continue

                    file_data = resp.json()
                    content = base64.b64decode(file_data.get("content", "")).decode("utf-8")

                    scan = scanner.scan_dependency_file(content, dep_file, owner_repo)
                    cur.execute("SAVEPOINT dep_scan")
                    stored = _store_dependency_scan(cur, scan)
                    cur.execute("RELEASE SAVEPOINT dep_scan")

                    results_summary["scans_performed"] += 1
                    results_summary["entries_created"] += stored
                    results_summary["total_updates"] += scan.get("updates_available", 0)
                    results_summary["total_vulnerabilities"] += scan.get("vulnerabilities_found", 0)
                    results_summary["critical_count"] += scan.get("critical_count", 0)
                    results_summary["scan_details"].append(
                        {
                            "source": owner_repo,
                            "file": dep_file,
                            "packages": scan.get("packages_scanned", 0),
                            "updates": scan.get("updates_available", 0),
                            "vulnerabilities": scan.get("vulnerabilities_found", 0),
                        }
                    )
                except Exception as e:
                    cur.execute("ROLLBACK TO SAVEPOINT dep_scan")
                    logger.warning(f"Failed to scan {owner_repo}/{dep_file}: {e}")

        # Scan local platform requirements.txt if requested
        if include_platform:
            try:
                local_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "requirements.txt"
                )
                with open(local_path, "r") as f:
                    content = f.read()

                scan = scanner.scan_dependency_file(content, "requirements.txt", "local/platform_v2")
                cur.execute("SAVEPOINT local_scan")
                stored = _store_dependency_scan(cur, scan)
                cur.execute("RELEASE SAVEPOINT local_scan")

                results_summary["scans_performed"] += 1
                results_summary["entries_created"] += stored
                results_summary["total_updates"] += scan.get("updates_available", 0)
                results_summary["total_vulnerabilities"] += scan.get("vulnerabilities_found", 0)
                results_summary["critical_count"] += scan.get("critical_count", 0)
                results_summary["scan_details"].append(
                    {
                        "source": "local/platform_v2",
                        "file": "requirements.txt",
                        "packages": scan.get("packages_scanned", 0),
                        "updates": scan.get("updates_available", 0),
                        "vulnerabilities": scan.get("vulnerabilities_found", 0),
                    }
                )
            except Exception as e:
                cur.execute("ROLLBACK TO SAVEPOINT local_scan")
                logger.warning(f"Failed to scan local requirements.txt: {e}")

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, **results_summary})

    except Exception as e:
        logger.error(f"Dependency scan failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/github/dependency-report", methods=["GET"])
@login_required
@admin_required
def github_dependency_report():
    """Get summary report of dependency scan results."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                COUNT(*) as total_suggestions,
                COUNT(*) FILTER (WHERE memory_metadata->>'severity' = 'critical') as critical_count,
                COUNT(*) FILTER (WHERE memory_metadata->>'severity' = 'high') as high_count,
                COUNT(*) FILTER (WHERE memory_metadata->>'severity' = 'medium') as medium_count,
                COUNT(*) FILTER (WHERE memory_metadata->>'severity' = 'low') as low_count,
                COUNT(*) FILTER (WHERE (memory_metadata->>'has_update')::boolean = true) as updates_available,
                COUNT(*) FILTER (WHERE (memory_metadata->>'vulnerability_count')::int > 0) as with_vulnerabilities,
                MAX(created_at) as last_scan
            FROM knowledge_base
            WHERE knowledge_type = 'upgrade_suggestion'
        """
        )
        summary = dict(cur.fetchone())

        # Group by ecosystem
        cur.execute(
            """
            SELECT
                memory_metadata->>'ecosystem' as ecosystem,
                COUNT(*) as count
            FROM knowledge_base
            WHERE knowledge_type = 'upgrade_suggestion'
            GROUP BY memory_metadata->>'ecosystem'
        """
        )
        by_ecosystem = [dict(r) for r in cur.fetchall()]

        # Group by source
        cur.execute(
            """
            SELECT
                memory_metadata->>'scan_source' as source,
                COUNT(*) as count,
                COUNT(*) FILTER (WHERE memory_metadata->>'severity' IN ('critical', 'high')) as urgent
            FROM knowledge_base
            WHERE knowledge_type = 'upgrade_suggestion'
            GROUP BY memory_metadata->>'scan_source'
            ORDER BY urgent DESC
        """
        )
        by_source = [dict(r) for r in cur.fetchall()]

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "summary": summary,
                "by_ecosystem": by_ecosystem,
                "by_source": by_source,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/github/upgrade-suggestions", methods=["GET"])
@login_required
@admin_required
def github_upgrade_suggestions():
    """List upgrade suggestions with optional filters."""
    severity = request.args.get("severity")
    ecosystem = request.args.get("ecosystem")
    source = request.args.get("source")
    limit = request.args.get("limit", 50, type=int)

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        conditions = ["knowledge_type = 'upgrade_suggestion'"]
        params = []

        if severity:
            conditions.append("memory_metadata->>'severity' = %s")
            params.append(severity)
        if ecosystem:
            conditions.append("memory_metadata->>'ecosystem' = %s")
            params.append(ecosystem)
        if source:
            conditions.append("memory_metadata->>'scan_source' = %s")
            params.append(source)

        where = " AND ".join(conditions)
        params.append(limit)

        cur.execute(
            f"""SELECT id, title, content, importance_score, memory_metadata, created_at
                FROM knowledge_base
                WHERE {where}
                ORDER BY importance_score DESC, created_at DESC
                LIMIT %s""",
            params,
        )
        suggestions = []
        for row in cur.fetchall():
            r = dict(row)
            if isinstance(r.get("memory_metadata"), str):
                r["memory_metadata"] = json.loads(r["memory_metadata"])
            suggestions.append(r)

        cur.close()
        conn.close()

        return jsonify({"success": True, "suggestions": suggestions, "count": len(suggestions)})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/chat-volume", methods=["GET"])
@login_required
@admin_required
def get_chat_volume():
    """Get chat conversation volume per day for last 30 days"""
    try:
        days = request.args.get("days", 30, type=int)
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT DATE(created_at) as date, COUNT(*) as count
            FROM ai_conversations
            WHERE created_at >= NOW() - INTERVAL '%s days'
            GROUP BY DATE(created_at)
            ORDER BY date ASC
        """,
            (days,),
        )
        volume = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "volume": [dict(v) for v in volume]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
        return (
            jsonify({"success": True, "collection_id": collection_id})
            if collection_id
            else jsonify({"success": False, "error": "Failed"})
        ), 500
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
        return jsonify({"success": False, "error": "memory_type and memory_id required"}), 400

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
        return (
            jsonify({"success": True, "new_importance": new_score}) if new_score else jsonify({"success": False})
        ), 500
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
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Run the maintenance function
        cur.execute("SELECT * FROM run_memory_maintenance()")
        results = [dict(r) for r in cur.fetchall()]

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "results": results, "message": "Memory maintenance completed"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/memory/preferences", methods=["GET"])
@login_required
def get_preferences():
    """Get user memory preferences"""
    try:
        user_id = current_user.id if hasattr(current_user, "id") else 1
        category = request.args.get("category")
        min_confidence = float(request.args.get("min_confidence", 0.5))

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM get_user_preferences(%s, %s, %s)", (user_id, category, min_confidence))
        preferences = [dict(p) for p in cur.fetchall()]

        cur.close()
        conn.close()

        return jsonify({"success": True, "data": preferences, "count": len(preferences)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/memory/preferences", methods=["POST"])
@login_required
def learn_preference():
    """Learn a new preference"""
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
            return jsonify({"success": False, "error": "category, key, and value required"}), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT learn_preference(%s, %s, %s, %s, %s, %s)",
            (user_id, category, key, value, confidence, json.dumps(context) if context else None),
        )
        pref_id = cur.fetchone()[0]

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "preference_id": pref_id, "message": f"Preference learned: {category}/{key}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/memory/system-stats", methods=["GET"])
@login_required
def get_memory_system_stats():
    """Get comprehensive memory system statistics"""
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

        cur.close()
        conn.close()

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
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/memory/extract", methods=["POST"])
@login_required
@admin_required
def extract_memories():
    """Extract memories from text content"""
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

        cur.execute("SELECT extract_memories_from_text(%s, %s, %s, %s)", (content, user_id, source_type, importance))
        memory_id = cur.fetchone()[0]

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "memory_id": memory_id, "message": "Memory extracted and stored"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
                        "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                        "trigger": str(job.trigger),
                    }
                )
            status["scheduled_jobs"] = jobs
            status["scheduler_running"] = scheduler.running
        else:
            status["scheduler_running"] = False
            status["scheduled_jobs"] = []

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
            return jsonify({"success": False, "error": f"Invalid task. Valid tasks: {valid_tasks}"}), 400

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

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "user_stats": user_stats if isinstance(user_stats, list) else dict(user_stats) if user_stats else None,
                "recent_sessions": [dict(s) for s in recent_sessions],
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# PHASE 62: BRIDGE ANALYTICS, AGENT SKILLS, SELF-IMPROVEMENT
# ============================================================================


@consciousness_bp.route("/bridge-analytics", methods=["GET"])
@login_required
@admin_required
def get_bridge_analytics():
    """Get bridge interaction analytics for dashboard"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Overall stats
        cur.execute(
            """
            SELECT
                COUNT(*) as total_calls,
                COUNT(*) FILTER (WHERE success = TRUE) as successful_calls,
                COUNT(*) FILTER (WHERE escalated_to_claude = TRUE) as claude_escalations,
                COALESCE(SUM(tokens_used), 0) as total_tokens,
                COALESCE(SUM(cost_estimate), 0)::numeric::float as total_cost,
                ROUND(AVG(execution_time_ms)::numeric, 0) as avg_execution_ms
            FROM bridge_interaction_log
            WHERE created_at > NOW() - INTERVAL '30 days'
        """
        )
        stats = cur.fetchone() or {}

        # Escalation patterns - what's being escalated to Claude
        cur.execute(
            """
            SELECT
                COALESCE(intent_type, 'unknown') as intent_type,
                COALESCE(module_name, 'unknown') as module_name,
                COUNT(*) as escalation_count,
                ROUND(AVG(execution_time_ms)::numeric, 0) as avg_time_ms,
                COALESCE(SUM(cost_estimate), 0)::numeric::float as total_cost
            FROM bridge_interaction_log
            WHERE escalated_to_claude = TRUE
              AND created_at > NOW() - INTERVAL '30 days'
            GROUP BY intent_type, module_name
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
                module_name,
                intent_type,
                model_used,
                tokens_used,
                execution_time_ms,
                success,
                escalated_to_claude,
                LEFT(prompt_summary, 100) as prompt_preview,
                created_at
            FROM bridge_interaction_log
            ORDER BY created_at DESC
            LIMIT 20
        """
        )
        recent_calls = cur.fetchall()

        # Daily trend (last 7 days)
        cur.execute(
            """
            SELECT
                DATE(created_at) as date,
                COUNT(*) as calls,
                COUNT(*) FILTER (WHERE escalated_to_claude = TRUE) as escalations
            FROM bridge_interaction_log
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY DATE(created_at)
            ORDER BY date
        """
        )
        daily_trend = cur.fetchall()

        cur.close()
        conn.close()

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


@consciousness_bp.route("/agent-skills", methods=["GET"])
@login_required
@admin_required
def get_agent_skills():
    """Get agent skills and learning data for dashboard"""
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
                all.id,
                all.agent_id,
                a.name as agent_name,
                a.role as agent_role,
                all.skill_name,
                all.skill_category,
                all.confidence,
                all.successful_uses,
                all.failed_uses,
                all.learned_from,
                all.last_used_at,
                all.created_at
            FROM agent_learning_log all
            JOIN agents a ON all.agent_id = a.id
            ORDER BY all.confidence DESC, all.successful_uses DESC
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

        cur.close()
        conn.close()

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


@consciousness_bp.route("/improvements-proposals", methods=["GET"])
@login_required
@admin_required
def get_improvement_proposals():
    """Get improvement proposals for approval workflow"""
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

        cur.close()
        conn.close()

        # Map 'proposed' status to 'pending' for frontend consistency
        formatted_proposals = []
        for p in proposals:
            proposal = dict(p)
            if proposal.get("status") == "proposed":
                proposal["status"] = "pending"
            formatted_proposals.append(proposal)

        return jsonify({"success": True, "proposals": formatted_proposals, "stats": dict(stats) if stats else {}})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/improvements/<int:proposal_id>/approve", methods=["POST"])
@login_required
@admin_required
def approve_proposal(proposal_id):
    """Approve an improvement proposal"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        note = request.json.get("note", "Approved by admin") if request.json else "Approved by admin"

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
        cur.close()
        conn.close()

        if proposal:
            audit_log("PROPOSAL_APPROVED", {"proposal_id": proposal_id, "user_id": current_user.id})
            return jsonify({"success": True, "proposal": dict(proposal)})
        else:
            return jsonify({"success": False, "error": "Proposal not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/improvements/<int:proposal_id>/reject", methods=["POST"])
@login_required
@admin_required
def reject_proposal(proposal_id):
    """Reject an improvement proposal"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        reason = request.json.get("reason", "Rejected by admin") if request.json else "Rejected by admin"

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
        cur.close()
        conn.close()

        if proposal:
            audit_log("PROPOSAL_REJECTED", {"proposal_id": proposal_id, "user_id": current_user.id, "reason": reason})
            return jsonify({"success": True, "proposal": dict(proposal)})
        else:
            return jsonify({"success": False, "error": "Proposal not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/improvements/<int:proposal_id>/test", methods=["POST"])
@login_required
@admin_required
def test_proposal_in_sandbox(proposal_id):
    """Queue a proposal for sandbox testing"""
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
        cur.close()
        conn.close()

        if proposal:
            audit_log("PROPOSAL_TESTING", {"proposal_id": proposal_id, "user_id": current_user.id})
            # TODO: Trigger actual sandbox test here
            return jsonify(
                {"success": True, "proposal": dict(proposal), "message": "Proposal queued for sandbox testing"}
            )
        else:
            return jsonify({"success": False, "error": "Proposal not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# PER-AGENT MEMORY MANAGEMENT (Phase 67: IAAE-Compliant)
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
            SELECT am.*, a.name as agent_name, a.role as agent_role,
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

        cur.close()
        conn.close()

        return jsonify(
            {"success": True, "memories": [dict(m) for m in memories], "total": total, "limit": limit, "offset": offset}
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/agent-memory/<int:memory_id>", methods=["GET"])
@login_required
@admin_required
def get_agent_memory(memory_id):
    """Get a specific agent memory by ID"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT am.*, a.name as agent_name, a.role as agent_role,
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

        cur.close()
        conn.close()

        if memory:
            return jsonify({"success": True, "memory": dict(memory)})
        else:
            return jsonify({"success": False, "error": "Memory not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/agent-memory/<int:memory_id>", methods=["PUT"])
@login_required
@admin_required
def update_agent_memory(memory_id):
    """Update an agent memory"""
    data = request.get_json() or {}

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
                {"memory_id": memory_id, "agent_id": memory.get("agent_id"), "updated_by": current_user.id},
            )

        cur.close()
        conn.close()

        if memory:
            return jsonify({"success": True, "memory": dict(memory)})
        else:
            return jsonify({"success": False, "error": "Memory not found or deleted"}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/agent-memory/<int:memory_id>/soft-delete", methods=["POST"])
@login_required
@admin_required
def soft_delete_agent_memory(memory_id):
    """
    Soft-delete an agent memory (IAAE-compliant).
    Memory is marked as deleted but remains in database for audit trail.
    """
    data = request.get_json() or {}
    reason = data.get("reason", "Admin deletion")

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Soft-delete with IAAE tracking
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
            # Log deletion for IAAE audit
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

            cur.close()
            conn.close()

            return jsonify(
                {
                    "success": True,
                    "message": "Memory soft-deleted (IAAE-compliant)",
                    "memory_id": memory_id,
                    "deleted_at": datetime.now().isoformat(),
                    "can_restore": True,
                }
            )
        else:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Memory not found or already deleted"}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/agent-memory/<int:memory_id>/restore", methods=["POST"])
@login_required
@admin_required
def restore_agent_memory(memory_id):
    """
    Restore a soft-deleted agent memory (IAAE-compliant).
    Only admin can restore memories.
    """
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
            # Log restoration for IAAE audit
            audit_log(
                "AGENT_MEMORY_RESTORED",
                {"memory_id": memory_id, "agent_id": restored.get("agent_id"), "restored_by": current_user.id},
            )

            cur.close()
            conn.close()

            return jsonify({"success": True, "message": "Memory restored successfully", "memory_id": memory_id})
        else:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Memory not found or not deleted"}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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

        cur.close()
        conn.close()

        if memory:
            return jsonify(
                {
                    "success": True,
                    "memory": dict(memory),
                    "message": f"Memory reinforced (count: {memory.get('reinforcement_count')})",
                }
            )
        else:
            return jsonify({"success": False, "error": "Memory not found or deleted"}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/agent-memory/stats", methods=["GET"])
@login_required
@admin_required
def agent_memory_stats():
    """Get statistics for agent memories"""
    agent_id = request.args.get("agent_id", type=int)

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

        cur.close()
        conn.close()

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
        import traceback

        traceback.print_exc()
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
        import traceback

        traceback.print_exc()
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
        session = engine.start_session(topic, max_turns)

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
        import traceback

        traceback.print_exc()
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
    """List all active/recent collaboration sessions in memory."""
    try:
        from .collaboration_engine import get_collaboration_engine

        engine = get_collaboration_engine()
        sessions = engine.list_sessions()
        return jsonify({"success": True, "sessions": sessions})
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
        cur.close()
        conn.close()

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
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
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
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/claude/chat", methods=["POST"])
@login_required
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
                        "interface alongside ARCHIE (another AI). Be helpful, concise, and friendly. "
                        "Answer the user's questions directly."
                    ),
                )
            )
        finally:
            loop.close()

        if response:
            # Persist Claude side-by-side message to DB
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
                cur.close()
                conn.close()
            except Exception as db_err:
                logger.warning(f"Failed to persist Claude message: {db_err}")

            return jsonify({"success": True, "response": response})
        else:
            return jsonify({"success": False, "error": "No response from Claude"}), 502

    except Exception as e:
        import traceback

        traceback.print_exc()
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
        return jsonify({"success": True, "claude": bridge.health_check(), "ttyd": bridge.get_ttyd_status()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
