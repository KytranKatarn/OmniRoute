"""Integration Routes -- Cross-module health and status

Extracted from routes.py as part of the Consciousness module refactor.
Handles:
- Cross-module health status (Dev HQ, Bridge, Ollama, GitHub)
"""

import logging
import os
import urllib.request

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import jsonify
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


def register_integration_routes(bp, admin_required):
    """Register all integration-related routes on the consciousness blueprint."""

    @bp.route("/api/integration/health")
    @login_required
    @admin_required
    def integration_health():
        """Cross-module health status"""
        with _get_db() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT count(*) as cnt FROM unified_projects WHERE status = 'active'")
            devhq = cur.fetchone()
            cur.execute("SELECT count(*) as cnt FROM bridge_stations WHERE is_active = true")
            bridge = cur.fetchone()
            ollama_ok = False
            try:
                ollama_host = os.getenv("OLLAMA_HOST", "host.docker.internal:11434")
                if not ollama_host.startswith("http"):
                    ollama_host = "http://" + ollama_host
                req = urllib.request.urlopen(f"{ollama_host}/api/tags", timeout=3)
                ollama_ok = req.status == 200
            except Exception:
                pass
            cur.execute("SELECT count(*) as cnt FROM github_repositories WHERE indexed = true")
            github = cur.fetchone()
            return jsonify(
                {
                    "success": True,
                    "systems": {
                        "devhq": {"status": "online", "projects": devhq["cnt"]},
                        "bridge": {"status": "online", "stations": bridge["cnt"]},
                        "ollama": {"status": "online" if ollama_ok else "offline"},
                        "github": {"status": "online", "repos": github["cnt"]},
                    },
                }
            )
