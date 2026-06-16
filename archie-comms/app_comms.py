"""A.R.C.H.I.E. Comms — Independent Communication Layer.

Runs as archie_comms container on :3002. Provides:
- Chat UI and API
- Telegram send/receive with personality voice
- Platform health watchdog
- Outbound message queue processor
- Collaboration engine (Claude bridge)
"""

import hmac
import logging
import os

from flask import Flask, request, jsonify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("archie_comms")

app = Flask(__name__, template_folder="templates", static_folder="static")

# Session secret MUST be persistent + shared across gunicorn workers. A random
# per-worker key (the old default) was the root cause of OAuth "Invalid state
# parameter" errors: worker A set oauth_state, the callback hit worker B, and
# the session couldn't be decoded. Fail loud if SECRET_KEY is missing so the
# bug can't silently regress.
_secret_key = os.getenv("SECRET_KEY")
if not _secret_key:
    raise RuntimeError(
        "SECRET_KEY env var is not set. archie_comms needs a persistent secret "
        "so OAuth session cookies remain valid across workers. Set SECRET_KEY "
        "in docker-compose / .env before starting."
    )
app.secret_key = _secret_key

ARCHIE_SERVICE_TOKEN = os.getenv("ARCHIE_COMMS_SERVICE_TOKEN", "")

app.config["SESSION_COOKIE_DOMAIN"] = ".kytranempowerment.com"
app.config["SESSION_COOKIE_NAME"] = "archie_comms_session"
app.config["SESSION_COOKIE_SECURE"] = True  # subdomain is HTTPS
app.config["SESSION_COOKIE_HTTPONLY"] = True  # blocks JS cookie read
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # permit top-level OAuth redirect

# SSO — "Connect with Kytran Empowerment"
# Two OAuth clients: archie-comms (archie subdomain) + claude-terminal (claude subdomain)
from kytran_auth import KytranAuth

kytran_auth = KytranAuth()
kytran_auth.init_app(app)

# Override redirect URI based on hostname at request time
_original_kytran_login = None


def _setup_dynamic_oauth():
    """Patch the SSO login route to use the correct OAuth client per subdomain."""
    global _original_kytran_login

    @app.before_request
    def _set_oauth_client():
        host = request.host.lower()
        if "claude" in host:
            kytran_auth.client_id = os.getenv("CLAUDE_CLIENT_ID", "claude-terminal")
            kytran_auth.client_secret = os.getenv("CLAUDE_CLIENT_SECRET", "")
            kytran_auth.redirect_uri = os.getenv(
                "CLAUDE_REDIRECT_URI",
                "https://claude.kytranempowerment.com/auth/kytran/callback",
            )
        else:
            kytran_auth.client_id = os.getenv("KYTRAN_CLIENT_ID", "archie-comms")
            kytran_auth.client_secret = os.getenv("KYTRAN_CLIENT_SECRET", "")
            kytran_auth.redirect_uri = os.getenv(
                "KYTRAN_REDIRECT_URI",
                "https://archie.kytranempowerment.com/auth/kytran/callback",
            )


_setup_dynamic_oauth()


@kytran_auth.on_login
def on_sso_login(user_data):
    """Post-SSO gate — only admin-role Kytran accounts reach A.R.C.H.I.E. Comms.

    Access control lives on the Kytran Empowerment hub: staff get role='admin',
    subscribers stay role='user'/'premium'. If the user lacks admin, we discard
    the session so `kytran_user` is absent and /chat redirects back to /login.
    """
    from flask import session

    role = user_data.get("role", "")
    if role != "admin":
        session.pop("kytran_user", None)
        logger.warning(
            "SSO login rejected: %s has role=%s (admin required)",
            user_data.get("username"),
            role,
        )
        return
    # Cache SSO-derived identity for routes that read session["user_id"] directly
    # (chat_routes, conversation listing, etc. predate kytran_user and use these keys).
    session["user_id"] = user_data.get("sub")
    session["username"] = user_data.get("username")
    session["role"] = role
    logger.info("SSO login accepted: %s (admin)", user_data.get("username"))


def _fetch_agent_status():
    """Return list of active AI agents. Called by /api/status."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT a.display_name, a.shift_state,
                       COALESCE(a.department, 'Unknown') AS department
                FROM agents a
                WHERE a.worker_type = 'ai'
                  AND a.shift_state NOT IN ('decommissioned', 'barracked', 'off_duty')
                ORDER BY a.shift_state, a.display_name
                LIMIT 15
                """,
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.error("_fetch_agent_status failed: %s", exc)
        return []


def _fetch_platform_health():
    """Return basic platform health dict. Called by /api/status."""
    health = {}
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT 1")
        health["db"] = "healthy"
    except Exception:
        health["db"] = "error"
    return health


def _call_platform_delegation_submit(capability, reason, args=None):
    """POST to platform internal delegation endpoint. Returns response dict.

    Extracted as a function so tests can monkeypatch without touching requests.
    Raises on HTTP error or network failure — caller handles.
    """
    import requests as _req
    import os as _os

    platform_url = _os.getenv("PLATFORM_INTERNAL_URL", "http://192.168.1.200:3000")
    api_key = _os.getenv("INTERNAL_API_KEY", "")
    resp = _req.post(
        f"{platform_url}/api/internal/delegation/submit",
        json={"capability": capability, "reason": reason, "args": args or {}},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _call_platform_delegation_status(task_id):
    """GET platform delegation status. Returns response dict."""
    import requests as _req
    import os as _os

    platform_url = _os.getenv("PLATFORM_INTERNAL_URL", "http://192.168.1.200:3000")
    api_key = _os.getenv("INTERNAL_API_KEY", "")
    resp = _req.get(
        f"{platform_url}/api/internal/delegation/{task_id}/status",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _call_platform_repair_count():
    """GET improvement_proposals count from platform."""
    import requests as _req
    import os as _os

    platform_url = _os.getenv("PLATFORM_INTERNAL_URL", "http://192.168.1.200:3000")
    api_key = _os.getenv("INTERNAL_API_KEY", "")
    resp = _req.get(
        f"{platform_url}/api/internal/repair/count",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()


def _tmux_capture_claude_code(lines=50):
    """Capture last N lines from the claude-code tmux session.

    Returns list of strings. Empty list if session not found or tmux unavailable.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", "claude-code", "-J"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []
        all_lines = result.stdout.splitlines()
        non_empty = [l for l in all_lines if l.strip()]
        return non_empty[-lines:]
    except Exception as exc:
        logger.error("_tmux_capture_claude_code failed: %s", exc)
        return []


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "service": "archie_comms", "version": "1.0.0"})


@app.route("/api/status")
def api_status():
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401

    return jsonify(
        {
            "agents": _fetch_agent_status(),
            "platform": _fetch_platform_health(),
            "anomaly_count": 0,
        }
    )


@app.route("/api/send", methods=["POST"])
def api_send():
    """Platform calls this to send a message through A.R.C.H.I.E.'s voice."""
    token = request.headers.get("X-Service-Token", "")
    if not ARCHIE_SERVICE_TOKEN or not hmac.compare_digest(token, ARCHIE_SERVICE_TOKEN):
        return jsonify({"error": "Unauthorized"}), 401
    from services.telegram_service import send

    data = request.get_json() or {}
    result = send(
        category=data.get("category", "info"),
        title=data.get("title", ""),
        message=data.get("message", ""),
        source_agent=data.get("source_agent"),
        source_department=data.get("source_department"),
        source_module=data.get("source_module"),
        force=data.get("force", False),
    )
    return jsonify(result)


@app.route("/")
def index():
    """Route based on subdomain — archie.* gets comms, claude.* gets terminal."""
    from flask import render_template

    host = request.host.lower()
    if "claude" in host:
        return render_template("claude_landing.html")
    return render_template("landing.html")


@app.route("/login")
def login():
    """SSO-only login. Local username/password is disabled — access is managed
    centrally via Kytran Empowerment accounts. Staff with role='admin' can enter;
    everyone else is rejected at the SSO callback.

    Respects ?next= param for redirect after login.
    """
    from flask import render_template, request, redirect, session

    next_url = request.args.get("next", "/chat")

    # Already authenticated via Kytran SSO → skip login page
    if "kytran_user" in session:
        return redirect(next_url)

    # Render SSO-only landing (hostname-branched)
    host = request.host.lower()
    if "claude" in host:
        return render_template("claude_login.html", next_url=next_url)
    return render_template("login.html", next_url=next_url)


@app.route("/logout")
def logout():
    """Clear session and redirect to landing page."""
    from flask import session, redirect

    session.clear()
    host = request.host.lower()
    if "claude" in host:
        return redirect("/claude")
    return redirect("/")


@app.route("/chat")
def chat():
    """A.R.C.H.I.E. chat interface — Kytran-SSO admins only."""
    from flask import render_template, session, redirect

    if "kytran_user" not in session:
        return redirect("/login")
    return render_template("chat.html")


@app.route("/api/director/report", methods=["POST"])
def api_director_report():
    """Agent loop jobs call this to submit director reports UP the hierarchy."""
    if not ARCHIE_SERVICE_TOKEN:
        return jsonify({"error": "Service token not configured"}), 503
    token = request.headers.get("X-Service-Token", "")
    if not token or not hmac.compare_digest(token, ARCHIE_SERVICE_TOKEN):
        return jsonify({"error": "Unauthorized"}), 401

    from services.briefing_service import submit_director_report

    data = request.get_json() or {}
    required = ["department", "director_agent", "severity", "category", "title", "summary"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    report_id = submit_director_report(
        department=data["department"],
        director_agent=data["director_agent"],
        severity=data["severity"],
        category=data["category"],
        title=data["title"],
        summary=data["summary"],
        details=data.get("details"),
    )

    if report_id:
        return jsonify({"success": True, "report_id": report_id})
    return jsonify({"error": "Failed to submit report"}), 500


@app.route("/api/internal/director-reports", methods=["GET"])
def api_internal_director_reports():
    """Return pending director_reports ordered by severity then age."""
    token = request.headers.get("X-Service-Token", "")
    if not ARCHIE_SERVICE_TOKEN or not hmac.compare_digest(token, ARCHIE_SERVICE_TOKEN):
        return jsonify({"error": "Unauthorized"}), 401

    from database import get_db_cursor

    limit = min(int(request.args.get("limit", 20)), 100)
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, department, director_agent, severity, category,
                   title, summary, details, created_at
            FROM director_reports
            WHERE triage_status = 'pending'
            ORDER BY
              CASE severity
                WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                WHEN 'medium'   THEN 2 ELSE 3
              END,
              created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]

    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
    return jsonify({"reports": rows, "count": len(rows)})


@app.route("/api/internal/director-reports/<int:report_id>/triage", methods=["POST"])
def api_internal_triage_report(report_id):
    """Apply a triage action to a pending director report."""
    token = request.headers.get("X-Service-Token", "")
    if not ARCHIE_SERVICE_TOKEN or not hmac.compare_digest(token, ARCHIE_SERVICE_TOKEN):
        return jsonify({"error": "Unauthorized"}), 401

    from database import get_db_cursor

    data = request.get_json() or {}
    action = data.get("action")
    if action not in ("resolve", "consolidate", "suppress", "escalate"):
        return jsonify({"error": "Invalid action"}), 400

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE director_reports
            SET triage_status      = %s,
                triage_action      = %s,
                triage_reason      = %s,
                triaged_at         = NOW(),
                escalated          = %s,
                escalation_channel = %s
            WHERE id = %s
            RETURNING id
            """,
            (
                action,
                action,
                data.get("reason", ""),
                action == "escalate",
                "telegram" if action == "escalate" else None,
                report_id,
            ),
        )
        row = cur.fetchone()

    if not row:
        return jsonify({"error": "Report not found"}), 404
    return jsonify({"success": True, "report_id": row["id"], "action": action})


@app.route("/api/internal/triage-policies", methods=["GET"])
def api_internal_triage_policies():
    """Return active triage policies ordered by priority."""
    token = request.headers.get("X-Service-Token", "")
    if not ARCHIE_SERVICE_TOKEN or not hmac.compare_digest(token, ARCHIE_SERVICE_TOKEN):
        return jsonify({"error": "Unauthorized"}), 401

    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, severity, category_prefix, director_agent_pattern,
                   action, reason, priority, active
            FROM triage_policies
            ORDER BY priority ASC
            """
        )
        rows = [dict(r) for r in cur.fetchall()]
    return jsonify({"policies": rows})


@app.route("/api/internal/triage-policies", methods=["POST"])
def api_internal_triage_policies_create():
    """Create a new triage policy."""
    token = request.headers.get("X-Service-Token", "")
    if not ARCHIE_SERVICE_TOKEN or not hmac.compare_digest(token, ARCHIE_SERVICE_TOKEN):
        return jsonify({"error": "Unauthorized"}), 401

    from database import get_db_cursor

    data = request.get_json() or {}
    action = data.get("action")
    reason = data.get("reason", "")
    if action not in ("escalate", "resolve", "consolidate", "suppress"):
        return jsonify({"error": "Invalid action"}), 400
    if not reason:
        return jsonify({"error": "reason is required"}), 400

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO triage_policies
              (severity, category_prefix, director_agent_pattern, action, reason, priority)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                data.get("severity") or None,
                data.get("category_prefix") or None,
                data.get("director_agent_pattern") or None,
                action,
                reason,
                int(data.get("priority", 50)),
            ),
        )
        row = cur.fetchone()
    return jsonify({"success": True, "id": row["id"] if row else None}), 201


@app.route("/api/internal/triage-policies/<int:policy_id>", methods=["DELETE"])
def api_internal_triage_policies_delete(policy_id):
    """Delete a triage policy by id."""
    token = request.headers.get("X-Service-Token", "")
    if not ARCHIE_SERVICE_TOKEN or not hmac.compare_digest(token, ARCHIE_SERVICE_TOKEN):
        return jsonify({"error": "Unauthorized"}), 401

    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM triage_policies WHERE id = %s", (policy_id,))
        deleted = cur.rowcount
    if not deleted:
        return jsonify({"error": "Policy not found"}), 404
    return jsonify({"success": True})


@app.route("/api/chat/send_message", methods=["POST"])
def api_chat_send_message():
    """SSE streaming endpoint. Emits token events then a done event."""
    import json as _json
    from flask import Response, session as flask_session, stream_with_context

    user_id = flask_session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    conversation_id = data.get("conversation_id")
    terminal_context = data.get("terminal_context") or None
    is_plan_request = bool(data.get("is_plan_request", False))

    if not message:
        return jsonify({"error": "Empty message"}), 400

    from services.conversation_service import stream_send_message

    def generate():
        try:
            for item in stream_send_message(user_id, message, "web", conversation_id, terminal_context=terminal_context, is_plan_request=is_plan_request):
                if isinstance(item, dict) and item.get("type") == "delegation_detected":
                    # Fire delegation to platform, emit delegation_queued
                    try:
                        result = _call_platform_delegation_submit(
                            item["capability"], item["reason"]
                        )
                        queued_evt = {
                            "type": "delegation_queued",
                            "task_id": result.get("task_id"),
                            "capability": item["capability"],
                            "reason": item["reason"],
                        }
                        yield f"data: {_json.dumps(queued_evt)}\n\n"
                    except Exception as exc:
                        logger.error("delegation fire failed: %s", exc)
                        yield f"data: {_json.dumps({'type': 'delegation_failed', 'reason': item.get('reason', '')})}\n\n"
                elif isinstance(item, dict):
                    yield f"data: {_json.dumps(item)}\n\n"
                else:
                    yield f"data: {_json.dumps({'type': 'token', 'content': item})}\n\n"
        except Exception as exc:
            logger.error("SSE generate failed: %s", exc)
            yield f"data: {_json.dumps({'type': 'error', 'message': 'Stream failed'})}\n\n"

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/chat/escalate", methods=["POST"])
def api_chat_escalate():
    """Escalate to Claude — A.R.C.H.I.E. brings him in when her team can't handle it."""
    from flask import session

    if "user_id" not in session and "kytran_user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400

    user_id = session.get("user_id", 2)
    from services.conversation_service import escalate_to_claude

    result = escalate_to_claude(user_id=user_id, message=message)
    return jsonify(result)


@app.route("/api/claude/health")
def api_claude_health():
    """Check Claude bridge availability."""
    from collaboration.claude_bridge import get_claude_bridge

    bridge = get_claude_bridge()
    return jsonify(bridge.health_check())


@app.route("/claude")
def claude_landing():
    """Claude TTY landing page — protected terminal access."""
    from flask import render_template

    return render_template("claude_landing.html")


@app.route("/claude/terminal")
def claude_terminal():
    """Claude TTY terminal — admin only, embeds TTYd."""
    from flask import render_template, session, redirect

    if "user_id" not in session and "kytran_user" not in session:
        return redirect("/claude")
    return render_template("claude_terminal.html")


@app.route("/api/chat/conversations", methods=["GET"])
def api_chat_conversations():
    """List conversations for the current user."""
    from flask import session

    if "user_id" not in session and "kytran_user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session.get("user_id", 2)
    from services.conversation_service import get_conversations

    result = get_conversations(user_id)
    convs = result["conversations"] if isinstance(result, dict) else result
    return jsonify({"conversations": [dict(c) if hasattr(c, 'keys') else c for c in convs]})


@app.route("/api/chat/messages")
def api_chat_messages():
    """Get messages for a conversation."""
    from flask import session

    if "user_id" not in session and "kytran_user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conv_id = request.args.get("conversation_id", type=int)
    if not conv_id:
        return jsonify({"messages": []})

    from services.conversation_service import get_conversation_messages

    msgs = get_conversation_messages(conv_id)
    return jsonify({"messages": [dict(m) if hasattr(m, 'keys') else m for m in msgs]})


@app.route("/api/chat/new", methods=["POST"])
def api_chat_new():
    """Start a new conversation."""
    from flask import session

    if "user_id" not in session and "kytran_user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session.get("user_id", 2)
    data = request.get_json() or {}
    from services.conversation_service import new_conversation

    conv_id = new_conversation(user_id, topic=data.get("topic"))
    return jsonify({"conversation_id": conv_id})


@app.route("/api/chat/sessions/<int:conv_id>/summarize", methods=["POST"])
def api_chat_summarize(conv_id):
    """Called via sendBeacon on session close. Stores KB summary."""
    from flask import session as flask_session

    user_id = flask_session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    # Verify conversation belongs to this user (prevent IDOR)
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id FROM unified_conversations WHERE id = %s AND user_id = %s",
                (conv_id, user_id),
            )
            if not cur.fetchone():
                return jsonify({"error": "Not found"}), 404
    except Exception as exc:
        logger.error("api_chat_summarize: ownership check failed: %s", exc)
        return jsonify({"success": False}), 500

    from services.conversation_service import summarize_conversation

    try:
        summarize_conversation(conv_id)
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("api_chat_summarize %d failed: %s", conv_id, exc)
        return jsonify({"success": False}), 500


@app.route("/api/terminal/token", methods=["POST"])
def api_terminal_token():
    """Mint a one-time token for ttyd auth proxy access."""
    import secrets
    from datetime import datetime, timezone, timedelta
    from flask import session as flask_session

    user_id = flask_session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO terminal_auth_tokens (token, user_id, expires_at)
                VALUES (%s, %s, %s)
                """,
                (token, user_id, expires_at),
            )
    except Exception as exc:
        logger.error("api_terminal_token: DB insert failed: %s", exc)
        return jsonify({"error": "Token generation failed"}), 500

    return jsonify({
        "token": token,
        "url": f"https://terminal.kytranempowerment.com?token={token}",
        "expires_in": 300,
    })


@app.route("/api/terminal/snapshot")
def api_terminal_snapshot():
    """Return last 50 lines from the claude-code tmux session."""
    from flask import session as flask_session
    from datetime import datetime, timezone

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401

    lines = _tmux_capture_claude_code()
    return jsonify({
        "lines": lines,
        "session": "claude-code",
        "captured_at": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/delegation/submit", methods=["POST"])
def api_delegation_submit():
    """Proxy delegation submission to platform. Auth: session cookie."""
    from flask import session as flask_session

    user_id = flask_session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json(silent=True) or {}
    capability = (data.get("capability") or "general").strip()
    reason = (data.get("reason") or "").strip()
    args = data.get("args") or {}

    if not reason:
        return jsonify({"error": "reason required"}), 400

    try:
        result = _call_platform_delegation_submit(capability, reason, args)
        return jsonify(result), 200
    except Exception as exc:
        logger.error("api_delegation_submit: platform call failed: %s", exc)
        return jsonify({"error": "Platform delegation unavailable"}), 503


@app.route("/api/delegation/<int:task_id>/status")
def api_delegation_status(task_id):
    """Proxy delegation status from platform. Auth: session cookie."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401

    try:
        result = _call_platform_delegation_status(task_id)
        return jsonify(result), 200
    except Exception as exc:
        logger.error("api_delegation_status %d: platform call failed: %s", task_id, exc)
        return jsonify({"error": "Status unavailable"}), 503


@app.route("/api/repair/count")
def api_repair_count():
    """Proxy repair proposal count from platform."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401

    try:
        result = _call_platform_repair_count()
        return jsonify(result)
    except Exception as exc:
        logger.error("api_repair_count failed: %s", exc)
        return jsonify({"count": 0})


# ── Header data endpoints (served locally; the shared lcars-header.js polls
#    these paths, which only exist on the platform — session-auth there, so we
#    can't proxy with the internal key. archie_comms reads the same hub `archie`
#    DB directly, so we serve real data here and kill the 404s. ──

@app.route("/tools/department-hq/api/dispatch/ops-summary")
def api_ops_summary():
    """Local DB-backed ops summary for the LCARS header elbow severity.
    Mirrors the platform endpoint's shape (approvals / active_jobs / errors_1h).
    """
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT
                       COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                       COUNT(*) FILTER (WHERE status = 'pending' AND expires_at < NOW()) AS expired
                   FROM autonomy_approval_queue"""
            )
            ar = dict(cur.fetchone())
            cur.execute(
                """SELECT
                       COUNT(*) FILTER (WHERE status = 'running') AS running,
                       COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                       COUNT(*) FILTER (
                           WHERE status = 'running' AND updated_at < NOW() - INTERVAL '15 minutes'
                       ) AS stalled
                   FROM bridge_jobs
                   WHERE status IN ('running', 'pending')"""
            )
            bj = dict(cur.fetchone())
            cur.execute(
                """SELECT COUNT(*) AS cnt FROM bridge_jobs
                   WHERE status = 'failed'
                   AND completed_at >= NOW() - INTERVAL '1 hour'
                   AND (metadata->>'reap_reason' IS NULL
                        OR metadata->>'reap_reason' NOT LIKE '%platform restarted%')"""
            )
            bridge_failed = cur.fetchone()["cnt"] or 0
            cur.execute(
                """SELECT COUNT(*) AS cnt FROM autonomy_loop_log
                   WHERE status != 'success' AND created_at >= NOW() - INTERVAL '1 hour'"""
            )
            loop_errors = cur.fetchone()["cnt"] or 0

        return jsonify(
            {
                "approvals": {"pending": ar.get("pending") or 0, "expired": ar.get("expired") or 0},
                "active_jobs": {
                    "bridge_running": bj.get("running") or 0,
                    "bridge_pending": bj.get("pending") or 0,
                    "bridge_stalled": bj.get("stalled") or 0,
                    # comms can't see the platform's in-process loop/scheduler objects;
                    # the header uses these only for non-severity display, so report up.
                    "agent_loop_running": True,
                    "scheduler_running": True,
                },
                "errors_1h": {"bridge_failed": bridge_failed, "loop_errors": loop_errors},
                "alerts": [],
            }
        )
    except Exception as exc:
        logger.error("api_ops_summary failed: %s", exc)
        return jsonify({"approvals": {}, "active_jobs": {}, "errors_1h": {}, "alerts": []})


def _empty_alerts():
    return {"success": True, "critical": [], "alerts": [], "categories": {}, "counts": {"total": 0, "unread": 0, "critical": 0}}


@app.route("/api/alerts/unified")
def api_alerts_unified_local():
    """Unified alerts for the header bell — sourced from director_reports
    (comms is the director-report hub). Unacknowledged, recent, actionable."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, department, director_agent, severity, category, title, summary, created_at
                   FROM director_reports
                   WHERE COALESCE(acknowledged, FALSE) = FALSE
                     AND severity IN ('critical', 'high', 'medium', 'warning')
                     AND created_at >= NOW() - INTERVAL '48 hours'
                   ORDER BY created_at DESC
                   LIMIT 50"""
            )
            rows = [dict(r) for r in cur.fetchall()]

        def _norm(sev):
            s = (sev or "").lower()
            if s in ("critical", "high"):
                return "critical"
            if s in ("medium", "warning"):
                return "warning"
            return "info"

        alerts = []
        for r in rows:
            alerts.append(
                {
                    "id": "director:%d" % r["id"],
                    "severity": _norm(r.get("severity")),
                    "title": r.get("title") or "Director Report",
                    "message": r.get("summary") or "",
                    "source": r.get("department") or r.get("director_agent") or "A.R.C.H.I.E.",
                    "category": r.get("category") or "operations",
                    "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                }
            )
        critical = [a for a in alerts if a["severity"] == "critical"]
        cats = {}
        for a in alerts:
            cats[a["category"]] = cats.get(a["category"], 0) + 1
        return jsonify(
            {
                "success": True,
                "critical": critical[:20],
                "alerts": alerts,
                "categories": cats,
                "counts": {"total": len(alerts), "unread": len(alerts), "critical": len(critical)},
            }
        )
    except Exception as exc:
        logger.error("api_alerts_unified_local failed: %s", exc)
        return jsonify(_empty_alerts())


@app.route("/api/alerts/unified/mark-read", methods=["POST"])
def api_alerts_mark_read_local():
    """Acknowledge a single director-report alert (key form 'director:<id>')."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    data = request.get_json(silent=True) or {}
    key = str(data.get("alert_key") or "")
    if key.startswith("director:"):
        try:
            rid = int(key.split(":", 1)[1])
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE director_reports SET acknowledged = TRUE, acknowledged_at = NOW() WHERE id = %s",
                    (rid,),
                )
        except Exception as exc:
            logger.error("api_alerts_mark_read_local failed: %s", exc)
    return jsonify({"success": True})


@app.route("/api/alerts/unified/mark-all-read", methods=["POST"])
def api_alerts_mark_all_read_local():
    """Acknowledge all currently-surfaced director-report alerts."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE director_reports SET acknowledged = TRUE, acknowledged_at = NOW()
                   WHERE COALESCE(acknowledged, FALSE) = FALSE
                     AND severity IN ('critical', 'high', 'medium', 'warning')
                     AND created_at >= NOW() - INTERVAL '48 hours'"""
            )
    except Exception as exc:
        logger.error("api_alerts_mark_all_read_local failed: %s", exc)
    return jsonify({"success": True})


@app.route("/api/dispatch/feed")
def api_dispatch_feed():
    """Live dispatch/trace feed — recent task_execution_log rows so the cockpit
    can show the agent team (and Claude/Codex) working in real time."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            # Bounded live feed: the newest 30 dispatches only. This is a
            # rolling recent-activity view polled every 10s, NOT a paginated
            # dataset — the LIMIT is the intended cap, not a TODO.
            cur.execute(
                """SELECT agent_name, capability, task_type, model_used, provider,
                          request_origin, module_source, duration_ms, tokens_used,
                          success, created_at
                   FROM task_execution_log
                   ORDER BY id DESC
                   LIMIT 30"""
            )
            rows = [dict(r) for r in cur.fetchall()]

        def _clip(v, n):
            s = "" if v is None else str(v)
            return s[:n]

        feed = []
        for r in rows:
            origin = (r.get("request_origin") or "").lower()
            name = r.get("agent_name") or "?"
            lname = name.lower()
            if "claude" in origin or "claude" in lname:
                tag = "claude"
            elif "codex" in origin or "codex" in lname:
                tag = "codex"
            else:
                tag = origin or "agent"
            feed.append(
                {
                    "agent": _clip(name, 40),
                    "capability": _clip(r.get("capability") or r.get("task_type") or "task", 48),
                    "model": _clip(r.get("model_used") or r.get("provider") or "", 32),
                    "module": _clip(r.get("module_source") or "", 32),
                    "origin": tag,
                    "duration_ms": r.get("duration_ms"),
                    "tokens": r.get("tokens_used"),
                    "success": bool(r.get("success")),
                    "ts": r["created_at"].isoformat() if r.get("created_at") else None,
                }
            )
        return jsonify({"feed": feed})
    except Exception as exc:
        logger.error("api_dispatch_feed failed: %s", exc)
        return jsonify({"feed": []})


def start_background_services():
    import threading
    from services.watchdog_service import PlatformWatchdog
    from services.queue_service import QueueProcessor

    watchdog = PlatformWatchdog()
    watchdog.start()

    queue = QueueProcessor()
    queue.start()

    # Director triage — every 5 minutes
    def _triage_loop():
        import time as _t

        _t.sleep(30)  # wait for startup
        while True:
            try:
                from services.briefing_service import run_triage

                run_triage()
            except Exception as e:
                logger.error("triage loop error: %s", e)
            _t.sleep(300)  # 5 minutes

    triage_thread = threading.Thread(target=_triage_loop, daemon=True, name="archie-triage")
    triage_thread.start()

    # Morning briefing — runs at configured hour (default 7:00 AM)
    def _briefing_loop():
        import time as _t
        from datetime import datetime

        _t.sleep(60)  # wait for startup
        briefing_hour = int(os.getenv("BRIEFING_HOUR", "7"))
        last_briefing_date = None
        while True:
            try:
                now = datetime.now()
                if now.hour == briefing_hour and now.date() != last_briefing_date:
                    from services.briefing_service import run_morning_briefing

                    run_morning_briefing()
                    last_briefing_date = now.date()
                    logger.info("Morning briefing sent for %s", now.date())
            except Exception as e:
                logger.error("briefing loop error: %s", e)
            _t.sleep(60)  # check every minute

    briefing_thread = threading.Thread(target=_briefing_loop, daemon=True, name="archie-briefing")
    briefing_thread.start()

    logger.info("Background services started (watchdog + queue + triage + briefing)")


start_background_services()

if __name__ == "__main__":
    port = int(os.getenv("COMMS_PORT", "3001"))
    app.run(host="0.0.0.0", port=port, debug=False)
