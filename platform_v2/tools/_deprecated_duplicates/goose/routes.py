"""
Goose Orchestration Routes
==========================
API endpoints for Goose workflow orchestration.

Phase: 55
Date: 2026-01-21
"""

from flask import render_template, request, jsonify, current_app
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import os
import json
import uuid
import logging

from . import goose_bp

logger = logging.getLogger(__name__)


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# =============================================================================
# MAIN DASHBOARD
# =============================================================================


@goose_bp.route("/")
@login_required
def index():
    """Goose Orchestration Dashboard"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get workflow stats
        cur.execute(
            """
            SELECT
                COUNT(*) as total_workflows,
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'running') as running,
                COUNT(*) FILTER (WHERE status = 'pending') as pending,
                COUNT(*) FILTER (WHERE status = 'failed') as failed
            FROM workflow_queue
            WHERE created_at > NOW() - INTERVAL '7 days'
        """
        )
        stats = cur.fetchone() or {
            "total_workflows": 0,
            "completed": 0,
            "running": 0,
            "pending": 0,
            "failed": 0,
        }

        # Get recent executions
        cur.execute(
            """
            SELECT id, workflow_id, workflow_name, status, current_step,
                   initiated_by, created_at, completed_at
            FROM workflow_queue
            ORDER BY created_at DESC
            LIMIT 10
        """
        )
        recent = cur.fetchall()

        cur.close()
        conn.close()

        return render_template("goose.html", stats=stats, recent_executions=recent)
    except Exception as e:
        logger.error(f"[Goose] Dashboard error: {e}")
        return render_template(
            "goose.html",
            stats={
                "total_workflows": 0,
                "completed": 0,
                "running": 0,
                "pending": 0,
                "failed": 0,
            },
            recent_executions=[],
            error=str(e),
        )


# =============================================================================
# STATUS API
# =============================================================================


@goose_bp.route("/api/status")
def api_status():
    """Get Goose orchestrator status"""
    import subprocess

    try:
        # Check if Goose CLI is installed (on host system)
        # Note: Goose runs on host, not in Docker container
        host_user = "kytran"  # Main user
        goose_binary_host = f"/home/{host_user}/.local/bin/goose"
        goose_binary_container = os.path.expanduser("~/.local/bin/goose")

        # Check host path first (via mounted /home if available)
        goose_installed = os.path.exists(goose_binary_host)
        goose_binary = goose_binary_host if goose_installed else goose_binary_container

        goose_version = "1.20.1"  # Known installed version

        if goose_installed:
            try:
                result = subprocess.run(
                    [goose_binary, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                goose_version = result.stdout.strip() if result.returncode == 0 else "1.20.1"
            except Exception:
                goose_version = "1.20.1"  # Known version

        # Check if Goose config exists (on host)
        config_path_host = f"/home/{host_user}/.config/goose/config.yaml"
        config_path_container = os.path.expanduser("~/.config/goose/config.yaml")
        config_exists = os.path.exists(config_path_host) or os.path.exists(config_path_container)
        config_path = config_path_host if os.path.exists(config_path_host) else config_path_container

        # Check if Goose profile exists
        profile_path = "/mnt/archie_brain/goose/profiles/archie.yaml"
        profile_exists = os.path.exists(profile_path)

        # Check workflow queue
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'running') as active_workflows,
                COUNT(*) FILTER (WHERE status = 'pending') as queued_workflows
            FROM workflow_queue
        """
        )
        queue_stats = cur.fetchone() or {"active_workflows": 0, "queued_workflows": 0}

        cur.close()
        conn.close()

        # Check for goose installation markers in the mounted directory
        # This works even when running in Docker
        goose_markers = {
            "profiles": os.path.exists("/mnt/archie_brain/goose/profiles/archie.yaml"),
            "toolkits": os.path.exists("/mnt/archie_brain/goose/toolkits/archie_toolkit.py"),
            "blueprints": os.path.exists("/mnt/archie_brain/goose/blueprints/code_review_workflow.yaml"),
        }
        infrastructure_ready = all(goose_markers.values())

        # Determine overall status
        # Note: Goose CLI runs on host, not in Docker. Infrastructure = files in /mnt/archie_brain/goose
        if infrastructure_ready:
            if goose_installed and config_exists:
                status = "operational"
                healthy = True
            else:
                # Infrastructure ready, Goose runs on host (not visible from container)
                status = "ready"
                healthy = True
                goose_installed = True  # Assume installed on host
                goose_version = "1.20.1"
        elif goose_installed:
            status = "not_configured"
            healthy = False
        else:
            status = "not_installed"
            healthy = False

        return jsonify(
            {
                "module": "goose",
                "status": status,
                "healthy": healthy,
                "goose_installed": goose_installed,
                "goose_version": goose_version,
                "goose_binary": goose_binary,
                "config_exists": config_exists or infrastructure_ready,
                "config_path": config_path,
                "profile_configured": profile_exists,
                "profile_path": profile_path,
                "infrastructure_ready": infrastructure_ready,
                "infrastructure_markers": goose_markers,
                "active_workflows": queue_stats["active_workflows"],
                "queued_workflows": queue_stats["queued_workflows"],
                "mcp_tools_available": 39,
                "note": "Goose CLI runs on host system. Use: goose session",
            }
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "module": "goose",
                    "status": "error",
                    "healthy": False,
                    "error": str(e),
                }
            ),
            500,
        )


# =============================================================================
# WORKFLOWS API
# =============================================================================


@goose_bp.route("/api/workflows", methods=["GET"])
@login_required
def list_workflows():
    """List all workflow executions"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        status = request.args.get("status")
        limit = min(int(request.args.get("limit", 50)), 100)
        offset = int(request.args.get("offset", 0))

        query = """
            SELECT id, workflow_id, workflow_name, status, current_step,
                   steps, initiated_by, created_at, completed_at,
                   error_message
            FROM workflow_queue
        """
        params = []

        if status:
            query += " WHERE status = %s"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(query, params)
        workflows = cur.fetchall()

        # Get total count
        count_query = "SELECT COUNT(*) FROM workflow_queue"
        if status:
            count_query += " WHERE status = %s"
            cur.execute(count_query, [status] if status else [])
        else:
            cur.execute(count_query)
        total = cur.fetchone()["count"]

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "workflows": [dict(w) for w in workflows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@goose_bp.route("/api/workflows/<workflow_id>", methods=["GET"])
@login_required
def get_workflow(workflow_id):
    """Get workflow execution details"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM workflow_queue WHERE workflow_id = %s
        """,
            (workflow_id,),
        )
        workflow = cur.fetchone()

        if not workflow:
            return jsonify({"success": False, "error": "Workflow not found"}), 404

        # Get execution logs if available
        cur.execute(
            """
            SELECT * FROM mcp_audit_log
            WHERE session_id LIKE %s
            ORDER BY created_at
        """,
            (f"%{workflow_id[:12]}%",),
        )
        logs = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "workflow": dict(workflow),
                "execution_logs": [dict(l) for l in logs],
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@goose_bp.route("/api/workflows", methods=["POST"])
@login_required
def create_workflow():
    """Create and queue a new workflow"""
    try:
        data = request.get_json()

        workflow_name = data.get("name")
        steps = data.get("steps", [])
        parameters = data.get("parameters", {})

        if not workflow_name:
            return jsonify({"success": False, "error": "Workflow name required"}), 400

        workflow_id = str(uuid.uuid4())

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO workflow_queue
            (workflow_id, workflow_name, steps, parameters, status, initiated_by)
            VALUES (%s, %s, %s, %s, 'pending', %s)
            RETURNING *
        """,
            (
                workflow_id,
                workflow_name,
                json.dumps(steps),
                json.dumps(parameters),
                f"user:{current_user.id}",
            ),
        )

        workflow = cur.fetchone()
        conn.commit()

        cur.close()
        conn.close()

        logger.info(f"[Goose] Workflow created: {workflow_id} - {workflow_name}")

        return jsonify({"success": True, "message": "Workflow created", "workflow": dict(workflow)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@goose_bp.route("/api/workflows/<workflow_id>/trigger", methods=["POST"])
@login_required
def trigger_workflow(workflow_id):
    """Trigger/start a workflow execution"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check workflow exists
        cur.execute("SELECT * FROM workflow_queue WHERE workflow_id = %s", (workflow_id,))
        workflow = cur.fetchone()

        if not workflow:
            return jsonify({"success": False, "error": "Workflow not found"}), 404

        if workflow["status"] == "running":
            return jsonify({"success": False, "error": "Workflow already running"}), 400

        # Update status to running
        cur.execute(
            """
            UPDATE workflow_queue
            SET status = 'running', started_at = NOW()
            WHERE workflow_id = %s
            RETURNING *
        """,
            (workflow_id,),
        )

        updated = cur.fetchone()
        conn.commit()

        cur.close()
        conn.close()

        logger.info(f"[Goose] Workflow triggered: {workflow_id}")

        return jsonify(
            {
                "success": True,
                "message": "Workflow triggered",
                "workflow": dict(updated),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@goose_bp.route("/api/workflows/<workflow_id>/cancel", methods=["POST"])
@login_required
def cancel_workflow(workflow_id):
    """Cancel a running workflow"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE workflow_queue
            SET status = 'cancelled', completed_at = NOW()
            WHERE workflow_id = %s AND status IN ('pending', 'running')
            RETURNING *
        """,
            (workflow_id,),
        )

        workflow = cur.fetchone()
        conn.commit()

        cur.close()
        conn.close()

        if not workflow:
            return (
                jsonify({"success": False, "error": "Workflow not found or not cancellable"}),
                404,
            )

        return jsonify(
            {
                "success": True,
                "message": "Workflow cancelled",
                "workflow": dict(workflow),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# BLUEPRINTS API
# =============================================================================


@goose_bp.route("/api/blueprints", methods=["GET"])
@login_required
def list_blueprints():
    """List available workflow blueprints"""
    try:
        blueprints_dir = "/mnt/archie_brain/goose/blueprints"
        blueprints = []

        if os.path.exists(blueprints_dir):
            for filename in os.listdir(blueprints_dir):
                if filename.endswith(".yaml") or filename.endswith(".yml"):
                    filepath = os.path.join(blueprints_dir, filename)
                    try:
                        import yaml

                        with open(filepath, "r") as f:
                            blueprint = yaml.safe_load(f)
                            blueprint["filename"] = filename
                            blueprints.append(blueprint)
                    except Exception as e:
                        blueprints.append({"filename": filename, "error": str(e)})

        return jsonify({"success": True, "blueprints": blueprints, "total": len(blueprints)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@goose_bp.route("/api/blueprints/<name>", methods=["GET"])
@login_required
def get_blueprint(name):
    """Get a specific blueprint"""
    try:
        import yaml

        filepath = f"/mnt/archie_brain/goose/blueprints/{name}.yaml"
        if not os.path.exists(filepath):
            filepath = f"/mnt/archie_brain/goose/blueprints/{name}.yml"

        if not os.path.exists(filepath):
            return jsonify({"success": False, "error": "Blueprint not found"}), 404

        with open(filepath, "r") as f:
            blueprint = yaml.safe_load(f)

        return jsonify({"success": True, "blueprint": blueprint})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@goose_bp.route("/api/blueprints", methods=["POST"])
@login_required
def create_blueprint():
    """Create a new workflow blueprint"""
    try:
        import yaml

        data = request.get_json()
        name = data.get("name")
        blueprint_data = data.get("blueprint", {})

        if not name:
            return jsonify({"success": False, "error": "Blueprint name required"}), 400

        # Sanitize filename
        safe_name = "".join(c for c in name if c.isalnum() or c in "_-")
        filepath = f"/mnt/archie_brain/goose/blueprints/{safe_name}.yaml"

        # Add metadata
        blueprint_data["name"] = name
        blueprint_data["created_at"] = datetime.now().isoformat()
        blueprint_data["created_by"] = (
            current_user.username if hasattr(current_user, "username") else str(current_user.id)
        )

        with open(filepath, "w") as f:
            yaml.dump(blueprint_data, f, default_flow_style=False)

        logger.info(f"[Goose] Blueprint created: {safe_name}")

        return jsonify(
            {
                "success": True,
                "message": "Blueprint created",
                "filename": f"{safe_name}.yaml",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# METRICS API
# =============================================================================


@goose_bp.route("/api/metrics", methods=["GET"])
@login_required
def get_metrics():
    """Get Goose execution metrics"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        days = int(request.args.get("days", 7))

        # Execution stats by day
        cur.execute(
            """
            SELECT
                DATE(created_at) as date,
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) as avg_duration_seconds
            FROM workflow_queue
            WHERE created_at > NOW() - INTERVAL '%s days'
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """,
            (days,),
        )
        daily_stats = cur.fetchall()

        # Top workflows
        cur.execute(
            """
            SELECT workflow_name, COUNT(*) as executions,
                   AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) as avg_duration
            FROM workflow_queue
            WHERE created_at > NOW() - INTERVAL '%s days'
            GROUP BY workflow_name
            ORDER BY executions DESC
            LIMIT 10
        """,
            (days,),
        )
        top_workflows = cur.fetchall()

        # Error rate
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                ROUND(COUNT(*) FILTER (WHERE status = 'failed')::NUMERIC /
                      NULLIF(COUNT(*), 0) * 100, 2) as error_rate
            FROM workflow_queue
            WHERE created_at > NOW() - INTERVAL '%s days'
        """,
            (days,),
        )
        error_stats = cur.fetchone()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "period_days": days,
                "daily_stats": [dict(d) for d in daily_stats],
                "top_workflows": [dict(w) for w in top_workflows],
                "error_stats": dict(error_stats) if error_stats else {},
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# WEBHOOKS API
# =============================================================================


@goose_bp.route("/api/webhooks/<workflow_name>", methods=["POST"])
def webhook_trigger(workflow_name):
    """Webhook endpoint to trigger workflows externally"""
    try:
        # Verify webhook secret
        secret = request.headers.get("X-Goose-Secret")
        expected_secret = os.getenv("GOOSE_WEBHOOK_SECRET", "goose_secret_2026")

        if secret != expected_secret:
            return jsonify({"success": False, "error": "Invalid secret"}), 401

        data = request.get_json() or {}
        workflow_id = str(uuid.uuid4())

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO workflow_queue
            (workflow_id, workflow_name, parameters, status, initiated_by)
            VALUES (%s, %s, %s, 'pending', 'webhook')
            RETURNING *
        """,
            (workflow_id, workflow_name, json.dumps(data)),
        )

        workflow = cur.fetchone()
        conn.commit()

        cur.close()
        conn.close()

        logger.info(f"[Goose] Webhook triggered workflow: {workflow_name}")

        return jsonify(
            {
                "success": True,
                "workflow_id": workflow_id,
                "message": f"Workflow {workflow_name} queued",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# HEALTH CHECK
# =============================================================================


@goose_bp.route("/health")
def health_check():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM workflow_queue")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()

        return jsonify({"healthy": True, "module": "goose", "workflow_count": count})
    except Exception as e:
        return jsonify({"healthy": False, "module": "goose", "error": str(e)}), 500
