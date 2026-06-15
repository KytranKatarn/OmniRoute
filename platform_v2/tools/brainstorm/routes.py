"""
Brainstorm Module Routes (T2069)

Endpoints:
  GET  /                               — LCARS page
  GET  /api/status                     — health check
  GET  /api/sessions                   — list user sessions
  POST /api/sessions                   — create session
  GET  /api/sessions/<id>              — get session + ideas
  DELETE /api/sessions/<id>            — delete session
  PATCH  /api/sessions/<id>            — update title/goal/tags/status
  POST /api/sessions/<id>/ideas        — add idea
  PATCH  /api/ideas/<id>               — update idea (content, cluster, votes)
  DELETE /api/ideas/<id>               — delete idea
  POST /api/sessions/<id>/export-kb    — export session to KB as vault_note
  POST /api/sessions/<id>/ai-expand    — AI idea expansion via DHQ dispatcher
"""

from __future__ import annotations

import logging

from flask import Response, jsonify, render_template, request
from flask_login import current_user, login_required

from database import get_db_cursor

from . import brainstorm_bp
from .validators import (
    validate_cluster,
    validate_content,
    validate_goal,
    validate_tags,
    validate_title,
    validate_vote_delta,
)

logger = logging.getLogger(__name__)

JsonResponse = Response | tuple[Response, int]
PageResponse = str

SESSION_UPDATE_COLUMNS = {
    "title": "title",
    "goal": "goal",
    "tags": "tags",
    "status": "status",
}
IDEA_UPDATE_COLUMNS = {
    "content": "content",
    "cluster": "cluster",
}
ALLOWED_SESSION_UPDATE_FIELDS = frozenset(SESSION_UPDATE_COLUMNS)
ALLOWED_IDEA_UPDATE_FIELDS = frozenset((*IDEA_UPDATE_COLUMNS, "vote_delta"))


# ── Auth gate ─────────────────────────────────────────────────────────────────


@brainstorm_bp.before_request
@login_required
def _require_login() -> None:
    """Require authenticated access for every brainstorm route.

    Args:
        None.

    Returns:
        None. Flask-Login handles redirects or authorization failures before
        route execution.
    """
    pass


# ── Page ─────────────────────────────────────────────────────────────────────


@brainstorm_bp.route("/")
def index() -> PageResponse:
    """Render the brainstorm tool page.

    Args:
        None.

    Returns:
        Rendered brainstorm HTML page.
    """
    return render_template("tools/brainstorm.html")


# ── Health ────────────────────────────────────────────────────────────────────


@brainstorm_bp.route("/api/status")
def status() -> Response:
    """Return the brainstorm module health payload.

    Args:
        None.

    Returns:
        JSON response with the module name, active status, and health flag.
    """
    return jsonify({"module": "brainstorm", "status": "active", "healthy": True})


# ── Sessions ──────────────────────────────────────────────────────────────────


@brainstorm_bp.route("/api/sessions", methods=["GET"])
def list_sessions() -> JsonResponse:
    """List brainstorm sessions for the current user.

    Args:
        None.

    Returns:
        JSON response containing up to 100 sessions, ordered with active
        sessions first and then by most recent update. Returns an error tuple
        with HTTP 500 if the query fails.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, title, goal, status, tags, idea_count, created_at, updated_at
                FROM brainstorm_sessions
                WHERE user_id = %s
                ORDER BY
                    CASE status WHEN 'active' THEN 0 ELSE 1 END,
                    updated_at DESC
                LIMIT 100
                """,
                (current_user.id,),
            )
            rows = cur.fetchall()
        sessions = [
            {
                "id": r["id"],
                "title": r["title"],
                "goal": r["goal"],
                "status": r["status"],
                "tags": r["tags"] or [],
                "idea_count": r["idea_count"],
                "created_at": r["created_at"].isoformat(),
                "updated_at": r["updated_at"].isoformat(),
            }
            for r in rows
        ]
        return jsonify({"success": True, "sessions": sessions})
    except Exception as exc:
        logger.error("list_sessions error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@brainstorm_bp.route("/api/sessions", methods=["POST"])
def create_session() -> JsonResponse:
    """Create a brainstorm session for the current user.

    Args:
        None.

    Returns:
        JSON response tuple with the created session and HTTP 201 on success.
        Returns HTTP 400 for validation errors or HTTP 500 for database errors.
    """
    body = request.get_json(silent=True) or {}
    try:
        title = validate_title(body.get("title"))
        goal = validate_goal(body.get("goal"))
        tags = validate_tags(body.get("tags"))
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO brainstorm_sessions (user_id, title, goal, tags)
                VALUES (%s, %s, %s, %s)
                RETURNING id, title, goal, status, tags, idea_count, created_at, updated_at
                """,
                (current_user.id, title, goal, tags),
            )
            r = cur.fetchone()
        return (
            jsonify(
                {
                    "success": True,
                    "session": {
                        "id": r["id"],
                        "title": r["title"],
                        "goal": r["goal"],
                        "status": r["status"],
                        "tags": r["tags"] or [],
                        "idea_count": r["idea_count"],
                        "created_at": r["created_at"].isoformat(),
                        "updated_at": r["updated_at"].isoformat(),
                    },
                }
            ),
            201,
        )
    except Exception as exc:
        logger.error("create_session error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@brainstorm_bp.route("/api/sessions/<int:session_id>", methods=["GET"])
def get_session(session_id: int) -> JsonResponse:
    """Get a brainstorm session with its ideas.

    Args:
        session_id: Brainstorm session ID to fetch for the current user.

    Returns:
        JSON response with the session and ordered idea list. Returns HTTP 404
        if the session is not owned by the user, or HTTP 500 on query failure.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, title, goal, status, tags, idea_count, created_at, updated_at
                FROM brainstorm_sessions
                WHERE id = %s AND user_id = %s
                """,
                (session_id, current_user.id),
            )
            s = cur.fetchone()
            if not s:
                return jsonify({"success": False, "error": "Session not found"}), 404
            cur.execute(
                """
                SELECT id, content, cluster, votes, created_at
                FROM brainstorm_ideas
                WHERE session_id = %s
                ORDER BY cluster NULLS LAST, votes DESC, created_at
                """,
                (session_id,),
            )
            ideas = cur.fetchall()
        return jsonify(
            {
                "success": True,
                "session": {
                    "id": s["id"],
                    "title": s["title"],
                    "goal": s["goal"],
                    "status": s["status"],
                    "tags": s["tags"] or [],
                    "idea_count": s["idea_count"],
                    "created_at": s["created_at"].isoformat(),
                    "updated_at": s["updated_at"].isoformat(),
                },
                "ideas": [
                    {
                        "id": i["id"],
                        "content": i["content"],
                        "cluster": i["cluster"],
                        "votes": i["votes"],
                        "created_at": i["created_at"].isoformat(),
                    }
                    for i in ideas
                ],
            }
        )
    except Exception as exc:
        logger.error("get_session error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@brainstorm_bp.route("/api/sessions/<int:session_id>", methods=["PATCH"])
def update_session(session_id: int) -> JsonResponse:
    """Update brainstorm session metadata.

    Args:
        session_id: Brainstorm session ID to update for the current user.

    Returns:
        JSON success response when metadata changes are saved. Returns HTTP 400
        for unknown fields, invalid values, or empty updates; HTTP 404 when the
        session is not found; or HTTP 500 on database errors.
    """
    body = request.get_json(silent=True) or {}
    unknown_fields = sorted(set(body) - ALLOWED_SESSION_UPDATE_FIELDS)
    if unknown_fields:
        return jsonify({"success": False, "error": f"Unknown field(s): {', '.join(unknown_fields)}"}), 400
    fields = {}
    try:
        if "title" in body:
            try:
                fields["title"] = validate_title(body["title"])
            except ValueError as exc:
                if str(exc) == "title is required":
                    raise ValueError("title cannot be empty") from exc
                raise
        if "goal" in body:
            fields["goal"] = validate_goal(body["goal"])
        if "tags" in body:
            fields["tags"] = validate_tags(body["tags"])
        if "status" in body:
            if body["status"] not in ("active", "archived"):
                return jsonify({"success": False, "error": "status must be active or archived"}), 400
            fields["status"] = body["status"]
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    if not fields:
        return jsonify({"success": False, "error": "Nothing to update"}), 400
    set_clause = ", ".join(f"{SESSION_UPDATE_COLUMNS[k]} = %s" for k in fields)
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                f"""
                UPDATE brainstorm_sessions
                SET {set_clause}, updated_at = NOW()
                WHERE id = %s AND user_id = %s
                RETURNING id
                """,
                (*fields.values(), session_id, current_user.id),
            )
            if not cur.fetchone():
                return jsonify({"success": False, "error": "Session not found"}), 404
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("update_session error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@brainstorm_bp.route("/api/sessions/<int:session_id>", methods=["DELETE"])
def delete_session(session_id: int) -> JsonResponse:
    """Delete a brainstorm session and its ideas.

    Args:
        session_id: Brainstorm session ID to delete for the current user.

    Returns:
        JSON success response when the session is deleted. Returns HTTP 404 if
        the session is not found, or HTTP 500 on database errors.
    """
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "DELETE FROM brainstorm_sessions WHERE id = %s AND user_id = %s RETURNING id",
                (session_id, current_user.id),
            )
            if not cur.fetchone():
                return jsonify({"success": False, "error": "Session not found"}), 404
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("delete_session error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ── Ideas ─────────────────────────────────────────────────────────────────────


def _refresh_idea_count(cur, session_id: int) -> None:
    cur.execute(
        "UPDATE brainstorm_sessions SET idea_count = (SELECT COUNT(*) FROM brainstorm_ideas WHERE session_id = %s), updated_at = NOW() WHERE id = %s",
        (session_id, session_id),
    )


@brainstorm_bp.route("/api/sessions/<int:session_id>/ideas", methods=["POST"])
def add_idea(session_id: int) -> JsonResponse:
    """Add an idea to a brainstorm session.

    Args:
        session_id: Brainstorm session ID that will receive the new idea.

    Returns:
        JSON response tuple with the created idea and HTTP 201 on success.
        Returns HTTP 400 for validation errors, HTTP 404 if the session is not
        owned by the user, or HTTP 500 on database errors.
    """
    body = request.get_json(silent=True) or {}
    try:
        content = validate_content(body.get("content"))
        cluster = validate_cluster(body.get("cluster"))
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            # Verify ownership
            cur.execute(
                "SELECT id FROM brainstorm_sessions WHERE id = %s AND user_id = %s",
                (session_id, current_user.id),
            )
            if not cur.fetchone():
                return jsonify({"success": False, "error": "Session not found"}), 404
            cur.execute(
                """
                INSERT INTO brainstorm_ideas (session_id, content, cluster)
                VALUES (%s, %s, %s)
                RETURNING id, content, cluster, votes, created_at
                """,
                (session_id, content, cluster),
            )
            idea = cur.fetchone()
            _refresh_idea_count(cur, session_id)
        return (
            jsonify(
                {
                    "success": True,
                    "idea": {
                        "id": idea["id"],
                        "content": idea["content"],
                        "cluster": idea["cluster"],
                        "votes": idea["votes"],
                        "created_at": idea["created_at"].isoformat(),
                    },
                }
            ),
            201,
        )
    except Exception as exc:
        logger.error("add_idea error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@brainstorm_bp.route("/api/ideas/<int:idea_id>", methods=["PATCH"])
def update_idea(idea_id: int) -> JsonResponse:
    """Update idea content, cluster, or vote count.

    Args:
        idea_id: Brainstorm idea ID to update for the current user.

    Returns:
        JSON success response, including the new vote count for vote updates.
        Returns HTTP 400 for invalid input or empty updates, HTTP 404 when the
        idea is not found, or HTTP 500 on database errors.
    """
    body = request.get_json(silent=True) or {}
    unknown_fields = sorted(set(body) - ALLOWED_IDEA_UPDATE_FIELDS)
    if unknown_fields:
        return jsonify({"success": False, "error": f"Unknown field(s): {', '.join(unknown_fields)}"}), 400
    fields = {}
    try:
        if "content" in body:
            try:
                fields["content"] = validate_content(body["content"])
            except ValueError as exc:
                if str(exc) == "content is required":
                    raise ValueError("content cannot be empty") from exc
                raise
        if "cluster" in body:
            fields["cluster"] = validate_cluster(body["cluster"])
        if "vote_delta" in body:
            # +1 or -1 applied atomically
            delta = validate_vote_delta(body["vote_delta"])
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    if "vote_delta" in body:
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE brainstorm_ideas SET votes = GREATEST(0, votes + %s)
                    WHERE id = %s AND session_id IN (
                        SELECT id FROM brainstorm_sessions WHERE user_id = %s
                    )
                    RETURNING id, votes
                    """,
                    (delta, idea_id, current_user.id),
                )
                r = cur.fetchone()
            if not r:
                return jsonify({"success": False, "error": "Idea not found"}), 404
            return jsonify({"success": True, "votes": r["votes"]})
        except Exception as exc:
            logger.error("update_idea vote error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
    if not fields:
        return jsonify({"success": False, "error": "Nothing to update"}), 400
    set_clause = ", ".join(f"{IDEA_UPDATE_COLUMNS[k]} = %s" for k in fields)
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                f"""
                UPDATE brainstorm_ideas SET {set_clause}
                WHERE id = %s AND session_id IN (
                    SELECT id FROM brainstorm_sessions WHERE user_id = %s
                )
                RETURNING id
                """,
                (*fields.values(), idea_id, current_user.id),
            )
            if not cur.fetchone():
                return jsonify({"success": False, "error": "Idea not found"}), 404
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("update_idea error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@brainstorm_bp.route("/api/ideas/<int:idea_id>", methods=["DELETE"])
def delete_idea(idea_id: int) -> JsonResponse:
    """Delete an idea from a brainstorm session.

    Args:
        idea_id: Brainstorm idea ID to delete for the current user.

    Returns:
        JSON success response after deleting the idea and refreshing its
        session's idea count. Returns HTTP 404 if the idea is not found, or
        HTTP 500 on database errors.
    """
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                DELETE FROM brainstorm_ideas
                WHERE id = %s AND session_id IN (
                    SELECT id FROM brainstorm_sessions WHERE user_id = %s
                )
                RETURNING session_id
                """,
                (idea_id, current_user.id),
            )
            r = cur.fetchone()
            if not r:
                return jsonify({"success": False, "error": "Idea not found"}), 404
            _refresh_idea_count(cur, r["session_id"])
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("delete_idea error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ── KB Export ─────────────────────────────────────────────────────────────────


@brainstorm_bp.route("/api/sessions/<int:session_id>/export-kb", methods=["POST"])
def export_to_kb(session_id: int) -> JsonResponse:
    """Export a brainstorm session to the knowledge base.

    Args:
        session_id: Brainstorm session ID to export for the current user.

    Returns:
        JSON response with the created knowledge-base ID on success. Returns
        HTTP 404 when the session is not found, or HTTP 500 if fetching or
        storing the vault note fails.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT title, goal, tags FROM brainstorm_sessions WHERE id = %s AND user_id = %s",
                (session_id, current_user.id),
            )
            s = cur.fetchone()
            if not s:
                return jsonify({"success": False, "error": "Session not found"}), 404
            cur.execute(
                "SELECT content, cluster, votes FROM brainstorm_ideas WHERE session_id = %s ORDER BY cluster NULLS LAST, votes DESC, created_at",
                (session_id,),
            )
            ideas = cur.fetchall()
    except Exception as exc:
        logger.error("export_to_kb fetch error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500

    # Build markdown content
    lines = [f"# Brainstorm: {s['title']}", ""]
    if s["goal"]:
        lines += [f"**Goal**: {s['goal']}", ""]
    if not ideas:
        lines.append("*(no ideas)*")
    else:
        current_cluster = None
        for idea in ideas:
            cluster = idea["cluster"] or "Uncategorised"
            if cluster != current_cluster:
                lines += [f"\n## {cluster}", ""]
                current_cluster = cluster
            vote_str = f" ▲{idea['votes']}" if idea["votes"] > 0 else ""
            lines.append(f"- {idea['content']}{vote_str}")

    content = "\n".join(lines)

    try:
        from services.knowledge_service import store_knowledge

        kb_id = store_knowledge(
            title=f"Brainstorm: {s['title']}",
            content=content,
            knowledge_type="vault_note",
            category="brainstorm",
            tags=list(s["tags"] or []) + ["brainstorm", "export"],
            importance_score=0.80,
        )
        return jsonify({"success": True, "kb_id": kb_id, "message": "Session exported to Knowledge Base"})
    except ImportError:
        # Fallback: direct insert if knowledge_service not importable
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO knowledge_base (title, content, knowledge_type, category, tags, importance_score)
                    VALUES (%s, %s, 'vault_note', 'brainstorm', %s, 0.80)
                    RETURNING id
                    """,
                    (f"Brainstorm: {s['title']}", content, list(s["tags"] or []) + ["brainstorm", "export"]),
                )
                kb_id = cur.fetchone()["id"]
            return jsonify({"success": True, "kb_id": kb_id, "message": "Session exported to Knowledge Base"})
        except Exception as exc2:
            logger.error("export_to_kb insert error: %s", exc2)
            return jsonify({"success": False, "error": str(exc2)}), 500
    except Exception as exc:
        logger.error("export_to_kb store error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ── AI Assist ─────────────────────────────────────────────────────────────────


@brainstorm_bp.route("/api/sessions/<int:session_id>/ai-expand", methods=["POST"])
def ai_expand(session_id: int) -> JsonResponse:
    """Ask DHQ to expand and critique brainstorm ideas.

    Args:
        session_id: Brainstorm session ID to expand for the current user.

    Returns:
        JSON response with the dispatcher response and agent name on success.
        Returns HTTP 404 when the session is not found, HTTP 500 on fetch
        errors, dispatch failure, or unexpected dispatcher exceptions.
    """
    body = request.get_json(silent=True) or {}
    focus = (body.get("focus") or "").strip()

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT title, goal FROM brainstorm_sessions WHERE id = %s AND user_id = %s",
                (session_id, current_user.id),
            )
            s = cur.fetchone()
            if not s:
                return jsonify({"success": False, "error": "Session not found"}), 404
            cur.execute(
                "SELECT content, cluster FROM brainstorm_ideas WHERE session_id = %s ORDER BY votes DESC LIMIT 30",
                (session_id,),
            )
            ideas = cur.fetchall()
    except Exception as exc:
        logger.error("ai_expand fetch error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500

    idea_list = "\n".join(f"- [{i['cluster'] or 'General'}] {i['content']}" for i in ideas) or "(none yet)"
    prompt = (
        f"Brainstorm session: {s['title']}\n"
        f"Goal: {s['goal'] or 'Not specified'}\n\n"
        f"Existing ideas:\n{idea_list}\n\n"
        f"{'Focus: ' + focus + chr(10) if focus else ''}"
        "Please: (1) identify 3-5 promising themes across these ideas, "
        "(2) suggest 5 new ideas not yet listed, "
        "(3) flag any gaps or blind spots. Be concise and actionable."
    )

    try:
        from tools.department_hq.services.department_dispatcher import dispatch

        result = dispatch(
            capability="research",
            prompt=prompt,
            context={"source": "brainstorm", "session_id": session_id},
        )
        if result.success:
            return jsonify({"success": True, "response": result.response, "agent": result.agent})
        return jsonify({"success": False, "error": result.error or "Dispatch failed"}), 500
    except Exception as exc:
        logger.error("ai_expand dispatch error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500
