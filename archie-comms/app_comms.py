"""A.R.C.H.I.E. Comms — Independent Communication Layer.

Runs as archie_comms container on :3002. Provides:
- Chat UI and API
- Telegram send/receive with personality voice
- Platform health watchdog
- Outbound message queue processor
- Collaboration engine (Claude bridge)
"""

import logging
import os

from flask import Flask, request, jsonify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("archie_comms")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", os.urandom(32).hex())
app.config["SESSION_COOKIE_DOMAIN"] = ".kytranempowerment.com"
app.config["SESSION_COOKIE_NAME"] = "archie_comms_session"

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


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "service": "archie_comms", "version": "1.0.0"})


@app.route("/api/send", methods=["POST"])
def api_send():
    """Platform calls this to send a message through A.R.C.H.I.E.'s voice."""
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


@app.route("/api/chat/send_message", methods=["POST"])
def api_chat_send():
    """Chat endpoint — routes through unified conversation service.

    All messages persisted to unified_conversations/unified_messages.
    Script match for instant responses, LLM for full personality.
    Conversation context carried across messages.
    """
    from flask import session

    if "user_id" not in session and "kytran_user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400

    user_id = session.get("user_id", 2)  # default to Kytran
    agent_target = data.get("agent_target")

    from services.conversation_service import send_message

    result = send_message(
        user_id=user_id,
        message=message,
        channel="platform",
        agent_target=agent_target,
    )
    return jsonify(result)


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
