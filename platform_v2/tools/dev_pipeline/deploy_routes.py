"""Dev Pipeline — Deploy tab routes.

Unified deployment view pulling from both Improvements Lab and Sandbox Manager.
Provides a single /api/deploy/* namespace for deployment history,
monitoring, and rollback operations.
"""

import logging

from flask import jsonify, request
from flask_login import login_required
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


def register_deploy_routes(bp, admin_required):
    """Register deployment-related routes on the dev_pipeline blueprint."""

    @bp.route("/api/deploy/history")
    @login_required
    @admin_required
    def deploy_history():
        """Unified deployment history from improvement_proposals (deployed status)."""
        try:
            from database import get_db_connection

            with get_db_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                try:
                    cur.execute(
                        """
                        SELECT id, title, category, priority, risk_level,
                               status, deployed_at, approved_at,
                               backup_name, metadata
                        FROM improvement_proposals
                        WHERE status IN ('deployed', 'implemented')
                        ORDER BY deployed_at DESC NULLS LAST
                        LIMIT 50
                        """
                    )
                    deployments = [dict(r) for r in cur.fetchall()]

                    cur.execute(
                        """
                        SELECT
                            COUNT(*) FILTER (WHERE status IN ('deployed', 'implemented')) as total_deployed,
                            COUNT(*) FILTER (WHERE status = 'tested') as ready_to_deploy,
                            COUNT(*) FILTER (WHERE status = 'fix_requested') as failed
                        FROM improvement_proposals
                        """
                    )
                    stats = dict(cur.fetchone())

                    return jsonify(
                        {
                            "success": True,
                            "deployments": deployments,
                            "stats": stats,
                        }
                    )
                finally:
                    cur.close()
        except Exception as e:
            logger.error(f"Deploy history error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/deploy/ready")
    @login_required
    @admin_required
    def deploy_ready():
        """Get proposals that are ready to deploy (status = tested)."""
        try:
            from database import get_db_connection

            with get_db_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                try:
                    cur.execute(
                        """
                        SELECT id, title, category, priority, risk_level,
                               status, approved_at, metadata
                        FROM improvement_proposals
                        WHERE status = 'tested'
                        ORDER BY priority DESC, approved_at ASC
                        """
                    )
                    return jsonify(
                        {
                            "success": True,
                            "proposals": [dict(r) for r in cur.fetchall()],
                        }
                    )
                finally:
                    cur.close()
        except Exception as e:
            logger.error(f"Deploy ready error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
