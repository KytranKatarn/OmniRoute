"""Integration Routes -- Cross-module health and status

Extracted from routes.py as part of the Consciousness module refactor.
Handles:
- Cross-module health status (Dev HQ, Bridge, Ollama, GitHub)
- Pipeline test (ADR-013 compliance)
- Dev HQ summary for cross-module view
"""

import logging
import os
from database import _get_db_password
import urllib.request

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import jsonify
from flask_login import login_required

from services import project_service

logger = logging.getLogger(__name__)


def _get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def register_integration_routes(bp, admin_required):
    """Register all integration-related routes on the consciousness blueprint."""

    @bp.route("/api/integration/health")
    @login_required
    @admin_required
    def integration_health():
        """Cross-module health status"""
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            active_count = project_service.get_active_project_count()
            cur.execute("SELECT count(*) as cnt FROM bridge_stations WHERE is_active = true")
            bridge = cur.fetchone()
            ollama_ok = False
            try:
                ollama_host = os.getenv("OLLAMA_HOST", "host.docker.internal:11434")
                if not ollama_host.startswith("http"):
                    ollama_host = "http://" + ollama_host
                req = urllib.request.urlopen(f"{ollama_host}/api/tags", timeout=3)
                ollama_ok = req.status == 200
            except Exception as e:
                logger.debug("Ollama health check failed: %s", e)
            cur.execute("SELECT count(*) as cnt FROM github_repositories WHERE indexed = true")
            github = cur.fetchone()
            return jsonify(
                {
                    "success": True,
                    "systems": {
                        "devhq": {"status": "online", "projects": active_count},
                        "bridge": {"status": "online", "stations": bridge["cnt"]},
                        "ollama": {"status": "online" if ollama_ok else "offline"},
                        "github": {"status": "online", "repos": github["cnt"]},
                    },
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()
            conn.close()

    @bp.route("/api/integration/test-pipeline", methods=["POST"])
    @login_required
    @admin_required
    def api_test_pipeline():
        """Test translation pipeline -- verify it routes through Bridge."""
        import time

        steps = []
        # Step 1: Call translation service
        start = time.time()
        try:
            from ai_bridge.translation_service import translate_text

            result = translate_text("Hello, how are you?", "fr")
            elapsed = round((time.time() - start) * 1000)
            steps.append(
                {
                    "step": "Translation Service",
                    "status": "ok",
                    "ms": elapsed,
                    "result": str(result)[:100],
                }
            )
        except Exception as e:
            steps.append(
                {
                    "step": "Translation Service",
                    "status": "error",
                    "error": str(e)[:200],
                }
            )
        # Step 2: Check Bridge log
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT id, model_used, tokens_used, duration_ms as execution_time_ms, created_at
                FROM task_execution_log ORDER BY created_at DESC LIMIT 1
            """
            )
            log_entry = cur.fetchone()
            if log_entry:
                steps.append(
                    {
                        "step": "Bridge Log Entry",
                        "status": "ok",
                        "model": log_entry.get("model_used", "unknown"),
                        "tokens": log_entry.get("tokens_used", 0),
                    }
                )
            else:
                steps.append(
                    {
                        "step": "Bridge Log Entry",
                        "status": "warning",
                        "note": "No recent log entry",
                    }
                )
        except Exception as e:
            steps.append(
                {
                    "step": "Bridge Log Check",
                    "status": "error",
                    "error": str(e)[:200],
                }
            )
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
        return jsonify({"success": True, "steps": steps})

    @bp.route("/api/integration/devhq-summary")
    @login_required
    @admin_required
    def api_devhq_summary():
        """Latest Dev HQ data for cross-module view."""
        try:
            projects = project_service.get_recent_projects(5)
            decisions = project_service.get_recent_decisions(5)
            return jsonify(
                {
                    "success": True,
                    "projects": projects,
                    "decisions": decisions,
                }
            )
        except Exception as e:
            logger.exception("Error in integration health")
            return jsonify({"success": False, "error": str(e)}), 500
