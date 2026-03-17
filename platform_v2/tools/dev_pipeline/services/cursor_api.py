"""
Cursor IDE Integration API
REST API endpoints for Cursor IDE integration

Author: A.R.C.H.I.E. Platform
Date: 2026-01-05
"""

import sys
from flask import Blueprint, jsonify, request, send_file
from flask_login import login_required, current_user
from functools import wraps

sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
try:
    from cursor_context_generator import CursorContextGenerator
except ImportError:
    CursorContextGenerator = None

# Create blueprint
cursor_bp = Blueprint("cursor", __name__, url_prefix="/api/cursor")


def admin_required(f):
    """Decorator to require admin access"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, "is_admin", False):
            return jsonify({"success": False, "error": "Admin access required"}), 403
        return f(*args, **kwargs)

    return decorated_function


@cursor_bp.route("/prepare/<int:proposal_id>", methods=["POST"])
@login_required
@admin_required
def prepare_cursor_project(proposal_id):
    """
    Prepare Cursor IDE project for a proposal

    Creates:
    - Sandbox Git branch
    - .cursorrules file with full context
    - Instructions for user

    Returns:
        {
            'success': True,
            'proposal_id': int,
            'branch_name': str,
            'git_url': str,
            'cursorrules_url': str,
            'instructions': str
        }
    """
    try:
        if CursorContextGenerator is None:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Cursor integration not available on this node",
                    }
                ),
                503,
            )
        generator = CursorContextGenerator()
        result = generator.prepare_cursor_package(proposal_id)

        if result["success"]:
            return jsonify(
                {
                    "success": True,
                    "proposal_id": proposal_id,
                    "branch_name": result["branch_name"],
                    "git_url": result["git_url"],
                    "cursorrules_url": f"/api/cursor/rules/{proposal_id}",
                    "download_url": f"/api/cursor/download-rules/{proposal_id}",
                    "instructions": result["instructions"],
                    "proposal": result.get("proposal", {}),
                }
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": result.get("error", "Failed to prepare Cursor project"),
                    }
                ),
                500,
            )

    except Exception as e:
        import traceback

        return (
            jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}),
            500,
        )


@cursor_bp.route("/rules/<int:proposal_id>", methods=["GET"])
@login_required
def get_cursorrules(proposal_id):
    """
    Get .cursorrules content for a proposal

    Returns: Plain text .cursorrules content
    """
    try:
        if CursorContextGenerator is None:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Cursor integration not available on this node",
                    }
                ),
                503,
            )
        generator = CursorContextGenerator()
        result = generator.generate_cursorrules(proposal_id)

        if result["success"]:
            return jsonify(
                {
                    "success": True,
                    "content": result["cursorrules_content"],
                    "branch_name": result["branch_name"],
                    "proposal": result.get("proposal", {}),
                }
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": result.get("error", "Failed to generate .cursorrules"),
                    }
                ),
                404,
            )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@cursor_bp.route("/download-rules/<int:proposal_id>", methods=["GET"])
@login_required
def download_cursorrules(proposal_id):
    """
    Download .cursorrules file for a proposal

    Returns: .cursorrules file download
    """
    try:
        if CursorContextGenerator is None:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Cursor integration not available on this node",
                    }
                ),
                503,
            )
        generator = CursorContextGenerator()
        result = generator.generate_cursorrules(proposal_id)

        if result["success"]:
            # Create temporary file
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", suffix=".cursorrules", delete=False) as f:
                f.write(result["cursorrules_content"])
                temp_path = f.name

            return send_file(
                temp_path,
                as_attachment=True,
                download_name=f".cursorrules-proposal-{proposal_id}",
                mimetype="text/plain",
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": result.get("error", "Failed to generate .cursorrules"),
                    }
                ),
                404,
            )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@cursor_bp.route("/status/<int:proposal_id>", methods=["GET"])
@login_required
def get_cursor_status(proposal_id):
    """
    Get current status of Cursor work for a proposal

    Returns:
        {
            'success': True,
            'branch_name': str,
            'branch_exists': bool,
            'commits': List[dict],
            'last_commit_at': str,
            'status': str
        }
    """
    try:
        from services.git_branch_manager import GitBranchManager

        git_manager = GitBranchManager()
        branch_name = f"sandbox-proposal-{proposal_id}"

        # Check if branch exists
        branch_exists = git_manager.branch_exists(branch_name)

        if not branch_exists:
            return jsonify(
                {
                    "success": True,
                    "branch_name": branch_name,
                    "branch_exists": False,
                    "status": "not_started",
                    "message": "Sandbox branch not created yet",
                }
            )

        # Get commit history for this branch
        result = git_manager._run_git_command(
            [
                "git",
                "log",
                f"{git_manager.production_branch}..{branch_name}",
                "--pretty=format:%H|%an|%ae|%at|%s",
                "-10",  # Last 10 commits
            ]
        )

        commits = []
        if result["success"] and result["stdout"]:
            for line in result["stdout"].split("\n"):
                if line.strip():
                    parts = line.split("|")
                    if len(parts) >= 5:
                        commits.append(
                            {
                                "hash": parts[0],
                                "author_name": parts[1],
                                "author_email": parts[2],
                                "timestamp": int(parts[3]),
                                "message": parts[4],
                            }
                        )

        # Get diff stats
        diff_result = git_manager.get_diff(proposal_id)

        return jsonify(
            {
                "success": True,
                "branch_name": branch_name,
                "branch_exists": True,
                "commits": commits,
                "commit_count": len(commits),
                "last_commit_at": commits[0]["timestamp"] if commits else None,
                "files_changed": (diff_result.get("num_files", 0) if diff_result.get("success") else 0),
                "status": "in_progress" if commits else "ready",
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@cursor_bp.route("/branch/<int:proposal_id>", methods=["GET"])
@login_required
def get_branch_info(proposal_id):
    """
    Get Git branch information for a proposal

    Returns:
        {
            'success': True,
            'branch_name': str,
            'exists': bool,
            'diff_stats': dict
        }
    """
    try:
        from services.git_branch_manager import GitBranchManager

        git_manager = GitBranchManager()
        branch_name = f"sandbox-proposal-{proposal_id}"

        branch_exists = git_manager.branch_exists(branch_name)

        if not branch_exists:
            return jsonify({"success": True, "branch_name": branch_name, "exists": False})

        # Get diff
        diff_result = git_manager.get_diff(proposal_id)

        return jsonify(
            {
                "success": True,
                "branch_name": branch_name,
                "exists": True,
                "diff_stats": diff_result if diff_result.get("success") else None,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@cursor_bp.route("/instructions/<int:proposal_id>", methods=["GET"])
@login_required
def get_instructions(proposal_id):
    """
    Get setup instructions for Cursor IDE

    Returns: HTML formatted instructions
    """
    try:
        if CursorContextGenerator is None:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Cursor integration not available on this node",
                    }
                ),
                503,
            )
        generator = CursorContextGenerator()
        branch_name = f"sandbox-proposal-{proposal_id}"
        instructions = generator._generate_instructions(proposal_id, branch_name)

        return jsonify({"success": True, "instructions": instructions, "branch_name": branch_name})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@cursor_bp.route("/commit-webhook", methods=["POST"])
def commit_webhook():
    """
    Webhook called by Git post-commit hook
    Automatically triggers workflow when commit is detected

    Expected payload:
        {
            "proposal_id": int,
            "commit_hash": str,
            "commit_message": str,
            "author_name": str,
            "author_email": str,
            "branch": str,
            "timestamp": int
        }

    Returns:
        {
            "success": True,
            "message": "Workflow triggered",
            "workflow_id": str
        }
    """
    try:
        # Validate request comes from Git hook
        if not request.headers.get("X-Git-Hook"):
            return (
                jsonify({"success": False, "error": "Unauthorized: Not from Git hook"}),
                403,
            )

        # Get commit data
        data = request.get_json()

        required_fields = ["proposal_id", "commit_hash", "commit_message", "branch"]
        for field in required_fields:
            if field not in data:
                return (
                    jsonify({"success": False, "error": f"Missing required field: {field}"}),
                    400,
                )

        proposal_id = data["proposal_id"]
        commit_hash = data["commit_hash"]
        commit_message = data["commit_message"]
        author_name = data.get("author_name", "Unknown")
        author_email = data.get("author_email", "unknown@kytranempowerment.com")
        branch = data["branch"]
        timestamp = data.get("timestamp", int(__import__("time").time()))

        # Validate branch matches proposal
        expected_branch = f"sandbox-proposal-{proposal_id}"
        if branch != expected_branch:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Branch mismatch: expected {expected_branch}, got {branch}",
                    }
                ),
                400,
            )

        # Record commit in database
        from tools.database import db

        # Check if git_commits table exists, if not create it
        with db.engine.connect() as conn:
            # Try to insert commit record
            try:
                insert_query = """
                    INSERT INTO git_commits
                    (proposal_id, commit_hash, commit_message, author_name, author_email,
                     branch_name, committed_at, detected_at, workflow_triggered)
                    VALUES (%s, %s, %s, %s, %s, %s, to_timestamp(%s), NOW(), TRUE)
                    ON CONFLICT (commit_hash) DO NOTHING
                    RETURNING id
                """
                result = conn.execute(
                    __import__("sqlalchemy").text(insert_query),
                    (
                        proposal_id,
                        commit_hash,
                        commit_message,
                        author_name,
                        author_email,
                        branch,
                        timestamp,
                    ),
                )
                conn.commit()

                commit_id = result.scalar() if result.rowcount > 0 else None

                if not commit_id:
                    # Commit already recorded
                    return jsonify(
                        {
                            "success": True,
                            "message": "Commit already processed",
                            "duplicate": True,
                        }
                    )

            except Exception as db_error:
                # Table might not exist, log but continue
                print(f"[Commit Webhook] Database error (will continue): {db_error}")
                commit_id = None

        # Check if this is a test hook (don't trigger workflow for tests)
        is_test = request.headers.get("X-Git-Hook-Test") == "true"

        if is_test:
            return jsonify(
                {
                    "success": True,
                    "message": "Test webhook received successfully",
                    "test_mode": True,
                }
            )

        # Trigger background workflow
        try:
            from background_workflow_runner import BackgroundWorkflowRunner

            runner = BackgroundWorkflowRunner()
            workflow_id = runner.trigger_workflow(
                proposal_id=proposal_id,
                trigger_type="git_commit",
                metadata={
                    "commit_hash": commit_hash,
                    "commit_message": commit_message,
                    "author_name": author_name,
                    "author_email": author_email,
                    "branch": branch,
                    "commit_id": commit_id,
                },
            )

            return jsonify(
                {
                    "success": True,
                    "message": f"Workflow triggered for proposal #{proposal_id}",
                    "workflow_id": workflow_id,
                    "commit_hash": commit_hash[:8],
                    "proposal_id": proposal_id,
                }
            )

        except Exception as workflow_error:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Failed to trigger workflow: {str(workflow_error)}",
                        "commit_recorded": commit_id is not None,
                    }
                ),
                500,
            )

    except Exception as e:
        import traceback

        return (
            jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}),
            500,
        )


@cursor_bp.route("/poller/status", methods=["GET"])
@login_required
def get_poller_status_endpoint():
    """
    Get status of Git commit polling service

    Returns:
        {
            "success": True,
            "poller": {
                "running": bool,
                "enabled": bool,
                "poll_interval": int,
                "last_poll_time": str,
                "commits_detected": int,
                "webhooks_triggered": int,
                "thread_alive": bool
            }
        }
    """
    try:
        from services.git_commit_poller import get_poller_status

        status = get_poller_status()

        return jsonify({"success": True, "poller": status})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@cursor_bp.route("/commits/<int:proposal_id>", methods=["GET"])
@login_required
def get_proposal_commits(proposal_id):
    """
    Get all commits for a proposal

    Returns:
        {
            "success": True,
            "commits": [
                {
                    "id": int,
                    "commit_hash": str,
                    "commit_message": str,
                    "author_name": str,
                    "author_email": str,
                    "branch_name": str,
                    "committed_at": str,
                    "workflow_triggered": bool,
                    "workflow_status": str
                }
            ],
            "total": int
        }
    """
    try:
        from tools.database import db
        import sqlalchemy

        query = """
            SELECT
                id,
                commit_hash,
                commit_message,
                author_name,
                author_email,
                branch_name,
                committed_at,
                detected_at,
                workflow_triggered,
                workflow_id,
                workflow_status,
                workflow_completed_at
            FROM git_commits
            WHERE proposal_id = %s
            ORDER BY committed_at DESC
        """

        with db.engine.connect() as conn:
            result = conn.execute(sqlalchemy.text(query), (proposal_id,))

            commits = []
            for row in result:
                commits.append(
                    {
                        "id": row[0],
                        "commit_hash": row[1],
                        "commit_message": row[2],
                        "author_name": row[3],
                        "author_email": row[4],
                        "branch_name": row[5],
                        "committed_at": row[6].isoformat() if row[6] else None,
                        "detected_at": row[7].isoformat() if row[7] else None,
                        "workflow_triggered": row[8],
                        "workflow_id": row[9],
                        "workflow_status": row[10],
                        "workflow_completed_at": (row[11].isoformat() if row[11] else None),
                    }
                )

            return jsonify(
                {
                    "success": True,
                    "commits": commits,
                    "total": len(commits),
                    "proposal_id": proposal_id,
                }
            )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@cursor_bp.route("/workflow/stream/<int:proposal_id>", methods=["GET"])
@login_required
def workflow_stream(proposal_id):
    """
    Server-Sent Events stream for real-time workflow updates

    Returns:
        SSE stream of workflow events
    """
    from flask import Response, stream_with_context
    from workflow_sse_manager import get_sse_manager

    manager = get_sse_manager()

    # Register client and get message queue
    message_queue = manager.register_client(proposal_id)

    def event_stream():
        """Generator for SSE stream"""
        try:
            # Stream messages from queue
            for sse_message in manager.generate_sse_stream(message_queue):
                yield sse_message

        finally:
            # Clean up on disconnect
            manager.unregister_client(proposal_id, message_queue)

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Connection": "keep-alive",
        },
    )
