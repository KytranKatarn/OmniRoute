"""Task Planner Routes — Kanban board, task CRUD, AI prioritize, Google Calendar."""

import logging

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from .services.planner_service import (
    ai_prioritize,
    create_board,
    create_task,
    delete_task,
    get_boards,
    get_stats,
    get_tasks,
    move_task,
    schedule_task,
    update_task,
)

logger = logging.getLogger(__name__)

task_planner_bp = Blueprint(
    "task_planner",
    __name__,
    url_prefix="/tools/task-planner",
    template_folder="templates",
)


# ---------------------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------------------


@task_planner_bp.route("/")
@login_required
def index():
    """Task Planner kanban board."""
    return render_template("task_planner.html")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@task_planner_bp.route("/api/status")
@login_required
def api_status():
    """Health check."""
    return jsonify({"status": "ok", "module": "task_planner"})


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@task_planner_bp.route("/api/tasks")
@login_required
def list_tasks():
    """GET /api/tasks?status=&category="""
    status = request.args.get("status")
    category = request.args.get("category")
    try:
        tasks = get_tasks(current_user.id, status=status, category=category)
        for t in tasks:
            for key in ("due_date", "completed_at", "created_at", "updated_at"):
                if t.get(key):
                    t[key] = t[key].isoformat()
        return jsonify({"success": True, "tasks": tasks})
    except Exception as exc:
        logger.error("list_tasks: %s", exc)
        return jsonify({"error": str(exc)}), 500


@task_planner_bp.route("/api/tasks", methods=["POST"])
@login_required
def api_create_task():
    """POST /api/tasks"""
    data = request.get_json() or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400
    try:
        task = create_task(
            user_id=current_user.id,
            title=title,
            description=data.get("description"),
            priority=int(data.get("priority", 5)),
            category=data.get("category"),
            due_date=data.get("due_date"),
            tags=data.get("tags", []),
        )
        for key in ("due_date", "completed_at", "created_at", "updated_at"):
            if task.get(key):
                task[key] = task[key].isoformat()
        return jsonify({"success": True, "task": task}), 201
    except Exception as exc:
        logger.error("create_task: %s", exc)
        return jsonify({"error": str(exc)}), 500


@task_planner_bp.route("/api/tasks/<int:task_id>", methods=["PUT"])
@login_required
def api_update_task(task_id):
    """PUT /api/tasks/<id>"""
    data = request.get_json() or {}
    try:
        task = update_task(task_id, current_user.id, data)
        if not task:
            return jsonify({"error": "Task not found or access denied"}), 404
        for key in ("due_date", "completed_at", "created_at", "updated_at"):
            if task.get(key):
                task[key] = task[key].isoformat()
        return jsonify({"success": True, "task": task})
    except Exception as exc:
        logger.error("update_task: %s", exc)
        return jsonify({"error": str(exc)}), 500


@task_planner_bp.route("/api/tasks/<int:task_id>", methods=["DELETE"])
@login_required
def api_delete_task(task_id):
    """DELETE /api/tasks/<id>"""
    try:
        deleted = delete_task(task_id, current_user.id)
        if not deleted:
            return jsonify({"error": "Task not found or access denied"}), 404
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("delete_task: %s", exc)
        return jsonify({"error": str(exc)}), 500


@task_planner_bp.route("/api/tasks/<int:task_id>/move", methods=["POST"])
@login_required
def api_move_task(task_id):
    """POST /api/tasks/<id>/move — kanban drag-and-drop."""
    data = request.get_json() or {}
    new_status = data.get("status")
    sort_order = int(data.get("sort_order", 0))
    if not new_status:
        return jsonify({"error": "status is required"}), 400
    try:
        task = move_task(task_id, current_user.id, new_status, sort_order)
        if not task:
            return jsonify({"error": "Task not found or access denied"}), 404
        for key in ("due_date", "completed_at", "created_at", "updated_at"):
            if task.get(key):
                task[key] = task[key].isoformat()
        return jsonify({"success": True, "task": task})
    except Exception as exc:
        logger.error("move_task: %s", exc)
        return jsonify({"error": str(exc)}), 500


@task_planner_bp.route("/api/tasks/<int:task_id>/schedule", methods=["POST"])
@login_required
def api_schedule_task(task_id):
    """POST /api/tasks/<id>/schedule — create Google Calendar event."""
    try:
        result = schedule_task(current_user.id, task_id)
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)
    except Exception as exc:
        logger.error("schedule_task route: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------


@task_planner_bp.route("/api/boards")
@login_required
def api_list_boards():
    """GET /api/boards"""
    try:
        boards = get_boards(current_user.id)
        for b in boards:
            if b.get("created_at"):
                b["created_at"] = b["created_at"].isoformat()
        return jsonify({"success": True, "boards": boards})
    except Exception as exc:
        logger.error("list_boards: %s", exc)
        return jsonify({"error": str(exc)}), 500


@task_planner_bp.route("/api/boards", methods=["POST"])
@login_required
def api_create_board():
    """POST /api/boards"""
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    try:
        board = create_board(current_user.id, name, data.get("columns"))
        if board.get("created_at"):
            board["created_at"] = board["created_at"].isoformat()
        return jsonify({"success": True, "board": board}), 201
    except Exception as exc:
        logger.error("create_board: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@task_planner_bp.route("/api/stats")
@login_required
def api_stats():
    """GET /api/stats"""
    try:
        stats = get_stats(current_user.id)
        return jsonify({"success": True, "stats": stats})
    except Exception as exc:
        logger.error("get_stats: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------


@task_planner_bp.route("/api/ai/prioritize", methods=["POST"])
@login_required
def api_ai_prioritize():
    """POST /api/ai/prioritize — reorder tasks via Bridge AI."""
    try:
        result = ai_prioritize(current_user.id)
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)
    except Exception as exc:
        logger.error("ai_prioritize route: %s", exc)
        return jsonify({"error": str(exc)}), 500
