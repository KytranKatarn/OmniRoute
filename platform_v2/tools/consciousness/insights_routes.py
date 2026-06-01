"""Insights Routes -- Analytics, sessions, learning patterns, experiences

Extracted from routes.py as part of the Consciousness module refactor.
Handles:
- Analytics dashboard + knowledge growth
- Improvements (mistake_learned entries)
- Conversation sessions timeline
- Emotional timeline (redirect to team routes for actual data)
- Learning patterns (access frequency, retention, importance)
- Tagged experiences
- Work context (git branches, phases, topics)
"""

import logging
import os
from database import _get_db_password

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import jsonify, render_template, request
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


def register_insights_routes(bp, admin_required):
    """Register all insights/analytics routes on the consciousness blueprint."""

    # ==================================================================
    # INSIGHTS SUMMARY (for consciousness.js dashboard)
    # ==================================================================

    @bp.route("/api/insights/summary")
    @login_required
    @admin_required
    def api_insights_summary():
        """Analytics overview for the Insights tab."""
        conn = _get_db()
        cur = None
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            # Bridge stats (last 7 days)
            cur.execute(
                """
                SELECT count(*) as total,
                       avg(duration_ms) as avg_time,
                       sum(tokens_used) as total_tokens,
                       count(DISTINCT model_used) as models_used
                FROM task_execution_log
                WHERE created_at > now() - interval '7 days'
            """
            )
            bridge = cur.fetchone()
            # Knowledge growth
            cur.execute(
                """
                SELECT count(*) as new_entries
                FROM knowledge_base
                WHERE created_at > now() - interval '7 days'
                  AND knowledge_type != 'archie_v1'
            """
            )
            growth = cur.fetchone()
            # Sessions count
            sessions_total = 0
            try:
                cur.execute("SELECT count(*) as total FROM conversation_sessions")
                sessions_row = cur.fetchone()
                if sessions_row:
                    sessions_total = sessions_row["total"]
            except Exception:
                conn.rollback()
            return jsonify(
                {
                    "success": True,
                    "bridge_stats": {
                        "total": bridge["total"] if bridge else 0,
                        "avg_time_ms": round(float(bridge["avg_time"] or 0)) if bridge else 0,
                        "total_tokens": bridge["total_tokens"] if bridge else 0,
                        "models_used": bridge["models_used"] if bridge else 0,
                    },
                    "knowledge_growth": growth["new_entries"] if growth else 0,
                    "sessions": sessions_total,
                }
            )
        except Exception as e:
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            conn.close()

    # ==================================================================
    # ANALYTICS
    # ==================================================================

    @bp.route("/analytics")
    @login_required
    @admin_required
    def analytics():
        """Knowledge growth analytics dashboard"""
        return render_template("consciousness_analytics.html")

    @bp.route("/analytics/knowledge-growth", methods=["GET"])
    @login_required
    @admin_required
    def knowledge_growth():
        """Knowledge base growth metrics over time"""
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            # Growth by day (last 30 days)
            cur.execute(
                """
                SELECT
                    DATE(created_at)::text as date,
                    COUNT(*) as entries_added,
                    knowledge_type
                FROM knowledge_base
                WHERE created_at > NOW() - INTERVAL '30 days'
                GROUP BY DATE(created_at), knowledge_type
                ORDER BY date ASC
            """
            )

            growth_data = cur.fetchall()

            return jsonify({"growth_data": growth_data})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # ==================================================================
    # IMPROVEMENTS
    # ==================================================================

    @bp.route("/improvements", methods=["GET"])
    @login_required
    @admin_required
    def get_consciousness_improvements():
        """Get improvements tracked in consciousness (mistake_learned entries)"""
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT id, knowledge_type, title, content, category, tags,
                       importance_score, access_count, source_type, created_at, updated_at
                FROM knowledge_base
                WHERE knowledge_type = 'mistake_learned'
                ORDER BY importance_score DESC, created_at DESC
                LIMIT 100
            """
            )

            improvements = cur.fetchall()

            return jsonify({"improvements": improvements})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # ==================================================================
    # CONVERSATION SESSIONS - ARCHIE'S MEMORY TIMELINE
    # ==================================================================

    @bp.route("/sessions", methods=["GET"])
    @login_required
    @admin_required
    def get_conversation_sessions():
        """Get all conversation sessions - ARCHIE's memory timeline"""
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
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

            return jsonify({"sessions": sessions, "stats": stats, "count": len(sessions)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    @bp.route("/sessions/<int:session_id>", methods=["GET"])
    @login_required
    @admin_required
    def get_session_detail(session_id):
        """Get full details of a specific conversation session"""
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
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

            return jsonify({"session": session, "knowledge_entries": knowledge_entries})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # ==================================================================
    # LEARNING PATTERNS - ARCHIE'S KNOWLEDGE ACQUISITION
    # ==================================================================

    @bp.route("/learning-patterns", methods=["GET"])
    @login_required
    @admin_required
    def get_learning_patterns():
        """Analyze ARCHIE's learning patterns"""
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
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
                    DATE(created_at)::text as date,
                    COUNT(*) as entries_added,
                    AVG(importance_score) as avg_importance
                FROM knowledge_base
                WHERE created_at > NOW() - INTERVAL '30 days'
                GROUP BY DATE(created_at)
                ORDER BY date ASC
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
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # ==================================================================
    # TAGGED EXPERIENCES
    # ==================================================================

    @bp.route("/experiences", methods=["GET"])
    @login_required
    @admin_required
    def get_tagged_experiences():
        """Get all tagged experiences - ARCHIE's categorized memories"""
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
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

            return jsonify(
                {
                    "popular_tags": popular_tags,
                    "tag_relationships": tag_relationships,
                    "experiences": experiences,
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # ==================================================================
    # WORK CONTEXT - GIT BRANCHES, PHASES, TOPICS
    # ==================================================================

    @bp.route("/work-context", methods=["GET"])
    @login_required
    @admin_required
    def get_work_context():
        """Get ARCHIE's work context - Git branches, commits, phases"""
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
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
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
