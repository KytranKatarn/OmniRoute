"""Consciousness module -- Dashboard routes.

Extracted from routes.py as part of the Consciousness module refactor.
Handles:
- Dashboard summary API (aggregated stats for the Consciousness dashboard)
"""

import logging
import os

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import jsonify
from flask_login import login_required

from database import _get_db_password
from services import project_service

logger = logging.getLogger(__name__)


def _get_db():
    """Get database connection."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def register_dashboard_routes(bp, admin_required):
    """Register dashboard-related routes on the consciousness blueprint."""

    @bp.route("/api/dashboard/summary")
    @login_required
    @admin_required
    def api_dashboard_summary():
        """ARCHIE's self-portrait -- aggregated stats for dashboard."""
        conn = None
        cur = None
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Knowledge stats
            cur.execute(
                """
                SELECT
                    count(*) as total,
                    count(*) FILTER (WHERE embedding IS NOT NULL) as embedded,
                    count(DISTINCT category) as categories
                FROM knowledge_base
                WHERE knowledge_type != 'archie_v1'
            """
            )
            knowledge = cur.fetchone()

            # Agent fleet
            cur.execute(
                """
                SELECT count(*) as total,
                       count(*) FILTER (WHERE status = 'active') as active
                FROM agent_profiles
            """
            )
            agents = cur.fetchone()

            # Agent wellness (avg mood/energy/stress)
            # IMPORTANT: table is agent_emotional_state (SINGULAR)
            cur.execute(
                """
                SELECT
                    avg(energy_level) as avg_energy,
                    avg(stress_level) as avg_stress,
                    avg(mood_intensity) as avg_mood
                FROM agent_emotional_state
            """
            )
            wellness = cur.fetchone()

            # Fleet deployment status from agents table (Starbase data)
            cur.execute(
                """
                SELECT
                    count(*) FILTER (WHERE shift_state = 'active') as deployed,
                    count(*) FILTER (WHERE shift_state = 'barracked') as barracked,
                    count(*) FILTER (WHERE shift_state IN ('off_duty', 'cooldown', 'winding_down')) as off_duty
                FROM agents
            """
            )
            fleet = cur.fetchone()

            # Recent dispatch activity (last hour)
            cur.execute(
                """
                SELECT count(*) as tasks_1h,
                       count(*) FILTER (WHERE success = true) as successes_1h
                FROM task_execution_log
                WHERE created_at > NOW() - INTERVAL '1 hour'
            """
            )
            recent = cur.fetchone()

            # Projects (from Dev HQ) -- via shared service
            projects = project_service.get_project_stats()

            # Tasks -- via shared service
            tasks = project_service.get_task_stats()

            # Recent activity (blended feed) -- via shared service
            activity = project_service.get_recent_activity()

            # Integration health
            cur.execute("SELECT count(*) as cnt FROM bridge_stations WHERE is_active = true")
            stations = cur.fetchone()

            # Knowledge breakdown by type (for Neural Core nodes)
            cur.execute(
                """
                SELECT knowledge_type, count(*) as cnt
                FROM knowledge_base
                WHERE knowledge_type != 'archie_v1'
                GROUP BY knowledge_type
            """
            )
            kb_types = {r["knowledge_type"]: r["cnt"] for r in cur.fetchall()}

            # Repo count
            cur.execute("SELECT count(*) as cnt FROM github_repositories")
            repo_count = cur.fetchone()["cnt"]

            # Session count
            cur.execute("SELECT count(*) as cnt FROM conversation_sessions")
            session_count = cur.fetchone()["cnt"]

            # Translation stats
            cur.execute(
                """
                SELECT count(DISTINCT key) as total_keys,
                       count(DISTINCT language) as languages,
                       count(*) as total_translations
                FROM translations
            """
            )
            trans = cur.fetchone()

            # Decisions stats
            cur.execute(
                """
                SELECT count(*) as cnt,
                       count(*) FILTER (WHERE embedding IS NOT NULL) as embedded
                FROM project_decisions
            """
            )
            decisions = cur.fetchone()

            # Translation embedding stats
            cur.execute(
                """
                SELECT count(*) FILTER (WHERE embedding IS NOT NULL) as embedded
                FROM translations
            """
            )
            trans_embedded = cur.fetchone()["embedded"]

            # Intelligence total: everything ARCHIE knows
            intelligence_total = knowledge["total"] + trans["total_translations"] + decisions["cnt"]

            # Embed % against full intelligence
            total_embedded = knowledge["embedded"] + trans_embedded + decisions["embedded"]
            embed_pct = 0
            if intelligence_total > 0:
                embed_pct = round(100.0 * total_embedded / intelligence_total, 1)

            return jsonify(
                {
                    "success": True,
                    "knowledge": {
                        "total": knowledge["total"],
                        "total_entries": intelligence_total,
                        "kb_entries": knowledge["total"],
                        "embedded": total_embedded,
                        "embed_pct": embed_pct,
                        "categories": knowledge["categories"],
                        "conversations": kb_types.get("conversation_memory", 0),
                        "github_files": kb_types.get("github_file", 0),
                        "code_snippets": kb_types.get("code_snippet", 0),
                        "vault_notes": kb_types.get("vault_note", 0),
                        "mistakes": kb_types.get("mistake_learned", 0),
                        "improvements": kb_types.get("improvement", 0) + kb_types.get("upgrade_suggestion", 0),
                        "repos": repo_count,
                        "sessions": session_count,
                        "translations": trans["total_translations"],
                        "translation_keys": trans["total_keys"],
                        "languages": trans["languages"],
                        "decisions": decisions["cnt"],
                    },
                    "agents": {
                        "total": agents["total"],
                        "active": agents["active"],
                        "deployed": fleet["deployed"],
                        "barracked": fleet["barracked"],
                        "off_duty": fleet["off_duty"],
                        "avg_energy": float(wellness["avg_energy"] or 0),
                        "avg_stress": float(wellness["avg_stress"] or 0),
                        "avg_mood": float(wellness["avg_mood"] or 0),
                        "tasks_last_hour": recent["tasks_1h"],
                        "success_rate_1h": round(recent["successes_1h"] / max(recent["tasks_1h"], 1) * 100, 1),
                    },
                    "projects": {
                        "active": projects["active"],
                        "completed": projects["completed"],
                        "tasks_in_progress": tasks["in_progress"],
                        "tasks_done": tasks["done"],
                        "tasks_total": tasks["total"],
                    },
                    "activity": activity,
                    "stations_active": stations["cnt"],
                    "translations": trans["total_translations"],
                }
            )
        except Exception as e:
            logger.error("Dashboard summary error: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
