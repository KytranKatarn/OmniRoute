"""Consciousness module -- Dashboard routes.

Extracted from routes.py as part of the Consciousness module refactor.
Handles:
- Dashboard summary API (aggregated stats for the Consciousness dashboard)
"""

import logging
import os

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import jsonify, request
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
        """A.R.C.H.I.E.'s self-portrait -- aggregated stats for dashboard."""
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

            # Agent fleet — agents is the canonical table (agent_profiles is obsolete)
            cur.execute(
                """
                SELECT count(*) as total,
                       count(*) FILTER (WHERE shift_state = 'active') as active
                FROM agents
                WHERE shift_state != 'decommissioned'
            """
            )
            agents = cur.fetchone()

            # Agent wellness (avg mood/energy/stress)
            # IMPORTANT: table is agent_emotional_state (SINGULAR)
            cur.execute(
                """
                SELECT
                    avg(aes.energy_level) as avg_energy,
                    avg(aes.stress_level) as avg_stress,
                    avg(aes.mood_intensity) as avg_mood
                FROM agent_emotional_state aes
                JOIN agents a ON a.id = aes.agent_id
                WHERE a.worker_type = 'ai'
                  AND aes.timestamp > NOW() - INTERVAL '1 hour'
            """
            )
            wellness = cur.fetchone()

            # Fleet deployment status (AI fleet) — buckets must PARTITION the fleet.
            # 'deployed' previously mislabeled the active count; now reports the real
            # shift_state='deployed' and exposes 'active' separately.
            cur.execute(
                """
                SELECT
                    count(*) FILTER (WHERE shift_state = 'active') as active,
                    count(*) FILTER (WHERE shift_state = 'deployed') as deployed,
                    count(*) FILTER (WHERE shift_state = 'barracked') as barracked,
                    count(*) FILTER (WHERE shift_state IN ('off_duty', 'cooldown', 'winding_down')) as off_duty
                FROM agents
                WHERE worker_type = 'ai'
            """
            )
            fleet = cur.fetchone()

            # Recent dispatch activity (last hour) — unified across BOTH dispatch
            # sinks via the shared helper. Was task_execution_log-only, so the
            # FLEET STATUS card showed ~100% while bridge_jobs (fleet/cold-queue)
            # had real failures in the same hour. Now matches the DHQ panels.
            from services.dispatch_health_service import dispatch_health

            _dh1 = dispatch_health(1)
            recent = {
                "tasks_1h": _dh1["total"],
                "successes_1h": _dh1["success"],
                "failed_1h": _dh1["failed"],
                "pending_1h": _dh1["pending"],
                "success_rate": _dh1["success_rate"],
            }

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

            # Project-Knowledge link stats (safe if migration not yet run)
            try:
                cur.execute(
                    """SELECT count(*) as total_links,
                              count(*) FILTER (WHERE link_type = 'auto') as auto_links,
                              count(*) FILTER (WHERE link_type = 'manual') as manual_links,
                              count(DISTINCT project_id) as projects_linked,
                              count(DISTINCT knowledge_id) as knowledge_linked
                       FROM project_knowledge_links"""
                )
                link_stats = cur.fetchone()
            except Exception:
                link_stats = {
                    "total_links": 0,
                    "auto_links": 0,
                    "manual_links": 0,
                    "projects_linked": 0,
                    "knowledge_linked": 0,
                }

            # Intelligence total: everything ARCHIE knows
            intelligence_total = knowledge["total"] + trans["total_translations"] + decisions["cnt"]

            # Blended "intelligence" embedding (KB + translations + decisions)
            total_embedded = knowledge["embedded"] + trans_embedded + decisions["embedded"]
            intelligence_embed_pct = 0
            if intelligence_total > 0:
                intelligence_embed_pct = round(100.0 * total_embedded / intelligence_total, 1)
            # KB-only coverage — what the "knowledge" panel should report.
            kb_embed_pct = 0
            if knowledge["total"] > 0:
                kb_embed_pct = round(100.0 * knowledge["embedded"] / knowledge["total"], 1)

            return jsonify(
                {
                    "success": True,
                    "knowledge": {
                        "total": knowledge["total"],
                        "total_entries": intelligence_total,
                        "kb_entries": knowledge["total"],
                        "embedded": knowledge["embedded"],
                        "embed_pct": kb_embed_pct,
                        "intelligence_embedded": total_embedded,
                        "intelligence_embed_pct": intelligence_embed_pct,
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
                        # AI-only active count from the fleet partition query —
                        # 'active' above spans ALL worker types, so it must not
                        # be rendered next to deployed/barracked/off_duty (which
                        # are AI-only). fleet_active partitions the same
                        # population as the other fleet buckets.
                        "fleet_active": fleet["active"],
                        "deployed": fleet["deployed"],
                        "barracked": fleet["barracked"],
                        "off_duty": fleet["off_duty"],
                        "avg_energy": float(wellness["avg_energy"] or 0),
                        "avg_stress": float(wellness["avg_stress"] or 0),
                        "avg_mood": float(wellness["avg_mood"] or 0),
                        "tasks_last_hour": recent["tasks_1h"],
                        # Use the helper's decided-only rate (ok/(ok+failed)); do NOT
                        # recompute success/total — that dilutes with in-flight work.
                        "success_rate_1h": recent["success_rate"],
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
                    "project_links": {
                        "total_links": link_stats["total_links"],
                        "auto_links": link_stats["auto_links"],
                        "manual_links": link_stats["manual_links"],
                        "projects_linked": link_stats["projects_linked"],
                        "knowledge_linked": link_stats["knowledge_linked"],
                    },
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

    @bp.route("/api/dashboard/project-knowledge/<int:project_id>")
    @login_required
    @admin_required
    def api_project_knowledge(project_id):
        """Get linked knowledge entries and gap analysis for a project."""
        from services.knowledge_link_service import get_project_knowledge, get_project_knowledge_gaps

        type_filter = request.args.get("type")
        knowledge = get_project_knowledge(project_id, type_filter=type_filter)
        gaps = get_project_knowledge_gaps(project_id)
        return jsonify({"success": True, "knowledge": knowledge, "gaps": gaps})

    @bp.route("/api/dashboard/agent-contributions/<int:project_id>")
    @login_required
    @admin_required
    def api_agent_contributions(project_id):
        """Get agent work stats for a project."""
        from services.project_service import get_agent_contributions

        days = request.args.get("days", type=int)
        contributions = get_agent_contributions(project_id, days=days)
        return jsonify({"success": True, "contributions": contributions})

    @bp.route("/api/dashboard/knowledge-gaps")
    @login_required
    @admin_required
    def api_knowledge_gaps():
        """Get gap analysis for all active projects, sorted worst-first."""
        from services.knowledge_link_service import get_all_gaps

        status = request.args.get("status", "active,planning")
        gaps = get_all_gaps(status=status)
        return jsonify({"success": True, "gaps": gaps})

    @bp.route("/api/dashboard/link-knowledge", methods=["POST"])
    @login_required
    @admin_required
    def api_link_knowledge():
        """Manually link a knowledge entry to a project."""
        from services.knowledge_link_service import link_knowledge_to_project

        data = request.get_json() or {}
        project_id = data.get("project_id")
        knowledge_id = data.get("knowledge_id")
        if not project_id or not knowledge_id:
            return jsonify({"success": False, "error": "project_id and knowledge_id required"}), 400
        ok = link_knowledge_to_project(int(knowledge_id), int(project_id), link_type="manual")
        return jsonify({"success": ok})

    @bp.route("/api/dashboard/unlink-knowledge/<int:link_id>", methods=["DELETE"])
    @login_required
    @admin_required
    def api_unlink_knowledge(link_id):
        """Remove a project-knowledge link."""
        from database import get_db_cursor

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "DELETE FROM project_knowledge_links WHERE id = %s RETURNING project_id, knowledge_id",
                    (link_id,),
                )
                row = cur.fetchone()
                if row:
                    return jsonify(
                        {
                            "success": True,
                            "removed": {"project_id": row["project_id"], "knowledge_id": row["knowledge_id"]},
                        }
                    )
                return jsonify({"success": False, "error": "Link not found"}), 404
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/dashboard/generate-docs", methods=["POST"])
    @login_required
    @admin_required
    def api_generate_docs():
        """Trigger D.A.R.W.I.N. doc generation for a specific project."""
        from services.auto_doc_service import generate_project_docs, check_cooldown

        data = request.get_json() or {}
        project_id = data.get("project_id")
        if not project_id:
            return jsonify({"success": False, "error": "project_id required"}), 400

        try:
            project_id = int(project_id)
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Invalid project_id"}), 400

        # Check cooldown (but allow override with force=true)
        force = data.get("force", False)
        if not force:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT slug FROM unified_projects WHERE id = %s", (project_id,))
                row = cur.fetchone()
                if row and check_cooldown(row["slug"]):
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "Report generated within last 7 days. Use force=true to override.",
                            }
                        ),
                        429,
                    )

        result = generate_project_docs(project_id)
        if result["success"]:
            return jsonify({"success": True, "kb_id": result["kb_id"], "message": "Report generated successfully"})
        return jsonify({"success": False, "error": result["error"]}), 500

    @bp.route("/api/dashboard/agent-expertise")
    @login_required
    @admin_required
    def api_agent_expertise():
        """Get agent expertise scores per project — contributors + recommendations."""
        from services.knowledge_link_service import get_agent_expertise

        project_id = request.args.get("project_id", type=int)
        projects = get_agent_expertise(project_id=project_id)
        return jsonify({"success": True, "projects": projects})

    @bp.route("/api/dashboard/knowledge-graph")
    @login_required
    @admin_required
    def api_knowledge_graph():
        """Get knowledge graph data — projects as nodes, shared KB as edges."""
        from services.knowledge_link_service import get_knowledge_graph

        graph = get_knowledge_graph()
        return jsonify({"success": True, **graph})

    @bp.route("/api/emotional-state")
    @bp.route("/emotional-state")
    @login_required
    @admin_required
    def api_emotional_state():
        """Get A.R.C.H.I.E.'s current emotional state for the Fleet Wellness panel.

        Called by consciousness.js api("/emotional-state") — returns mood, energy,
        stress, and confidence so the EMOTIONAL STATE indicator stops showing '--'.
        Falls back to fleet-wide averages if A.R.C.H.I.E. has no personal record.
        """
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Try A.R.C.H.I.E.'s personal emotional state first
            cur.execute(
                """
                SELECT aes.current_mood, aes.mood_intensity,
                       aes.energy_level, aes.stress_level, aes.timestamp
                FROM agents a
                JOIN agent_emotional_state aes ON aes.agent_id = a.id
                WHERE a.name = 'A.R.C.H.I.E.'
                ORDER BY aes.timestamp DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()

            if row:
                return jsonify(
                    {
                        "success": True,
                        "mood": row["current_mood"] or "focused",
                        "energy": float(row["energy_level"] or 0.8),
                        "stress": float(row["stress_level"] or 0.2),
                        "confidence": float(row["mood_intensity"] or 0.7),
                        "timestamp": str(row["timestamp"]) if row["timestamp"] else None,
                        "source": "archie",
                    }
                )

            # Fallback: fleet-wide average across all AI agents
            cur.execute(
                """
                SELECT AVG(energy_level) AS energy, AVG(stress_level) AS stress,
                       AVG(mood_intensity) AS confidence,
                       MODE() WITHIN GROUP (ORDER BY current_mood) AS mood
                FROM agent_emotional_state aes
                JOIN agents a ON a.id = aes.agent_id
                WHERE a.worker_type = 'ai'
                  AND aes.timestamp > NOW() - INTERVAL '1 hour'
                """
            )
            avg = cur.fetchone()
            return jsonify(
                {
                    "success": True,
                    "mood": (avg["mood"] if avg and avg["mood"] else "focused"),
                    "energy": float(avg["energy"] or 0.8) if avg else 0.8,
                    "stress": float(avg["stress"] or 0.2) if avg else 0.2,
                    "confidence": float(avg["confidence"] or 0.7) if avg else 0.7,
                    "source": "fleet_average",
                }
            )
        except Exception as e:
            logger.error("Emotional state error: %s", e)
            return jsonify({"success": True, "mood": "focused", "energy": 0.8, "stress": 0.2, "confidence": 0.7})
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
