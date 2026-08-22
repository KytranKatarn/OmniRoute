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


def _read_secret(name: str, env_fallback: str) -> str:
    """Read a secret from /run/secrets/<name> (Docker secret) first, then fall back
    to the env var. Mirrors database._get_db_password (KB #268834). #4292/#4293: the
    archie-comms OAuth client secrets now live in Docker secrets; env stays as a
    graceful fallback (tests + any host without the secret file mounted)."""
    secret_path = f"/run/secrets/{name}"
    try:
        with open(secret_path) as fh:
            val = fh.read().strip()
            if val:
                return val
    except OSError:
        pass
    return os.getenv(env_fallback, "")


# OAuth client secrets — Docker-secret-first, env fallback. Resolved ONCE at import so
# the per-request _set_oauth_client hook never does file I/O. #4293.
_KYTRAN_CLIENT_SECRET = _read_secret("comms_kytran_client_secret", "KYTRAN_CLIENT_SECRET")
_CLAUDE_CLIENT_SECRET = _read_secret("comms_claude_client_secret", "CLAUDE_CLIENT_SECRET")

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

# Behind NPM for the padlocked https hostname (TLS terminated at the edge, plain http to
# this app). Trust the single proxy hop's X-Forwarded-Proto/Host so request.scheme is
# 'https' and external URL/redirect/cookie handling is correct — without this the app sees
# http and the OAuth session can break over the proxy. No-op for direct mesh/IP access
# (no X-Forwarded-* headers). One hop = NPM only.
from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: E402

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

ARCHIE_SERVICE_TOKEN = os.getenv("ARCHIE_COMMS_SERVICE_TOKEN", "")

# Mesh-only cockpit (2026-06-17): served over http on the WireGuard-encrypted mesh at a
# raw-IP host. A domain-scoped (.kytranempowerment.com) cookie can't bind to an IP host,
# and a Secure cookie isn't sent over http — either one drops the session, which broke the
# OAuth `state`/PKCE round-trip across the 2 gunicorn workers ("Session Expired"). Default
# to a host-only, non-Secure cookie; override via env if fronted by HTTPS again.
app.config["SESSION_COOKIE_DOMAIN"] = os.getenv("COMMS_COOKIE_DOMAIN", "").strip() or None
app.config["SESSION_COOKIE_NAME"] = "archie_comms_session"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("COMMS_COOKIE_SECURE", "false").lower() == "true"
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
            kytran_auth.client_secret = _CLAUDE_CLIENT_SECRET
            kytran_auth.redirect_uri = os.getenv(
                "CLAUDE_REDIRECT_URI",
                "https://claude.kytranempowerment.com/auth/kytran/callback",
            )
        else:
            kytran_auth.client_id = os.getenv("KYTRAN_CLIENT_ID", "archie-comms")
            kytran_auth.client_secret = _KYTRAN_CLIENT_SECRET
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


def _call_platform_delegation_submit(capability, reason, args=None, delegation_source=None):
    """POST to platform internal delegation endpoint. Returns response dict.

    Extracted as a function so tests can monkeypatch without touching requests.
    Raises on HTTP error or network failure — caller handles.
    """
    import requests as _req
    import os as _os

    platform_url = _os.getenv("PLATFORM_INTERNAL_URL", "http://192.168.1.200:3000")
    api_key = _os.getenv("INTERNAL_API_KEY", "")
    payload = {"capability": capability, "reason": reason, "args": args or {}}
    # #5334: the source is OMITTED unless a caller asks for one, so the existing
    # chat path sends a byte-identical body and the hub keeps defaulting it to
    # 'web_chat'. Passing a source here unconditionally would retroactively
    # relabel every cockpit chat delegation in task_execution_log.
    if delegation_source:
        payload["delegation_source"] = delegation_source
    resp = _req.post(
        f"{platform_url}/api/internal/delegation/submit",
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _call_platform_invokable_skills():
    """#5334: the platform's GENERATED invokable-skills registry.

    Same registry archie-tui lists (#5333) — known-tool delegates plus every LLM
    capability in CAPABILITY_DEPARTMENT_MAP. Distinct from the curated
    {{ACTION:<key>}} rail, which is a hand-picked SAFE subset that A.R.C.H.I.E.
    emits herself and runs synchronously. This one is user-picked, async, and
    routed through DHQ.
    """
    import requests as _req
    import os as _os

    platform_url = _os.getenv("PLATFORM_INTERNAL_URL", "http://192.168.1.200:3000")
    api_key = _os.getenv("INTERNAL_API_KEY", "")
    resp = _req.get(
        f"{platform_url}/api/internal/delegation/invokable-skills",
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


@app.route("/api/public/stats")
def api_public_stats():
    """Public landing-page stats (no auth) — live active-agent + knowledge-base counts from
    the shared DB, so the marketing landing shows real numbers instead of '—'/stale hardcodes.
    Only aggregate marketing counts are exposed. Fail-soft: nulls for anything unavailable."""
    out = {
        "agents_active": None,
        "departments": None,
        "kb_entries": None,
        "kb_coverage_pct": None,
        "telegram_recency": None,
    }
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT COUNT(*) AS n, COUNT(DISTINCT department) AS depts
                FROM agents
                WHERE worker_type = 'ai'
                  AND shift_state NOT IN ('decommissioned', 'barracked', 'off_duty')
                """
            )
            r = cur.fetchone()
            if r:
                out["agents_active"] = r["n"]
                out["departments"] = r["depts"]
            cur.execute("SELECT COUNT(*) AS total, COUNT(embedding) AS emb FROM knowledge_base")
            r = cur.fetchone()
            if r and r["total"]:
                out["kb_entries"] = r["total"]
                out["kb_coverage_pct"] = round(r["emb"] / r["total"] * 100)
            # Telegram liveness — a COARSE recency bucket only (today / this week / earlier),
            # never a precise timestamp or content. This public, unauthenticated endpoint must
            # not leak exact internal ops-activity timing. Kept LAST so a failure here can't
            # poison the agent/KB values already set above.
            cur.execute("SELECT MAX(created_at) AS last FROM telegram_message_log")
            r = cur.fetchone()
            if r and r["last"]:
                from datetime import datetime, timezone

                last = r["last"]
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
                out["telegram_recency"] = "today" if age_h < 24 else ("this week" if age_h < 168 else "earlier")
    except Exception as exc:
        logger.error("api_public_stats failed: %s", exc)
    return jsonify(out)


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


@app.route("/api/approvals/pending", methods=["GET"])
def api_approvals_pending():
    """Owner-only: the pending Tier-2 approvals the cockpit right-rail renders.
    Session-auth (kytran_auth OIDC); execution stays on the platform behind the
    internal key. Read path is fail-soft (empty list on platform trouble)."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.approvals_proxy import list_pending

    return jsonify({"approvals": list_pending()})


@app.route("/api/approvals/<path:approval_id>/<verb>", methods=["POST"])
def api_approvals_act(approval_id, verb):
    """Owner-only approve/deny for one Tier-2 card. Session-auth; the logged-in
    user_id is forwarded to the platform. Fail-CLOSED: a non-ok proxy result ->
    502 so the UI keeps the row pending (never optimistic)."""
    from flask import session as flask_session

    uid = flask_session.get("user_id")
    if not uid:
        return jsonify({"error": "Not authenticated"}), 401
    if verb not in ("approve", "deny"):
        return jsonify({"error": "bad verb"}), 400
    from services.approvals_proxy import approve, deny

    if verb == "approve":
        out = approve(approval_id, uid)
    else:
        out = deny(approval_id, uid, (request.get_json(silent=True) or {}).get("reason", ""))
    return jsonify(out), (200 if out.get("ok") else 502)


_ATTACH_MAX_BYTES = 10 * 1024 * 1024  # 10 MB cockpit upload ceiling


@app.route("/api/chat/attach", methods=["POST"])
def api_chat_attach():
    """Owner-only: extract an uploaded file's text (sovereign, on the platform).
    Bytes are held in memory only and forwarded base64 to the platform extract
    endpoint. Fail-SOFT: an extraction failure still returns a block with a note
    so the chat message can send without the attachment context."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    raw = f.read()
    if len(raw) > _ATTACH_MAX_BYTES:
        return jsonify({"error": "file too large (max 10 MB)"}), 413
    from services.attachment_proxy import extract, format_attachment_block

    name = f.filename or "attachment"
    res = extract(name, raw, f.mimetype)
    if not res.get("ok"):
        block = format_attachment_block(name, "(could not read this file)", False, 0)
        return jsonify(
            {"ok": True, "filename": name, "chars": 0, "ocr_used": False,
             "truncated": False, "block": block, "note": res.get("error")}
        )
    text = res.get("text") or "(no readable text found)"
    chars = res.get("chars", len(text))
    block = format_attachment_block(name, text, res.get("ocr_used"), chars)
    return jsonify(
        {"ok": True, "filename": name, "chars": chars, "ocr_used": bool(res.get("ocr_used")),
         "truncated": bool(res.get("truncated")), "block": block}
    )


@app.route("/api/archie/avatar", methods=["GET"])
def api_archie_avatar():
    """A.R.C.H.I.E.'s avatar image (proxied from the platform). 404 -> the frontend
    falls back to a CSS monogram. Cached a day (her face rarely changes)."""
    from flask import Response
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.face_proxy import portrait

    got = portrait()
    if not got:
        return ("", 404)
    raw, mime = got
    return Response(raw, mimetype=mime, headers={"Cache-Control": "public, max-age=86400"})


@app.route("/api/coo/agents", methods=["GET"])
def api_coo_agents():
    """Consultable crew (department directors) for the cockpit switcher. Session-gated;
    the INTERNAL_API_KEY is applied server-side in the proxy. Slice 1 (COO command surface)."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.coo_consult import list_agents

    return jsonify(list_agents())


@app.route("/api/coms/overview", methods=["GET"])
def api_coms_overview():
    """COMs/Telegram hub read view for the cockpit COMs tab. Session-gated; the internal
    key is applied server-side in the proxy. Slice 2 (COO command surface)."""
    from flask import request as flask_request
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.coms_hub import overview

    return jsonify(
        overview(
            limit=int(flask_request.args.get("limit", 50) or 50),
            category=(flask_request.args.get("category") or "").strip() or None,
            source_agent=(flask_request.args.get("source_agent") or "").strip() or None,
            status=(flask_request.args.get("status") or "").strip() or None,
        )
    )


@app.route("/api/mail/inbox", methods=["GET"])
def api_mail_inbox():
    from flask import request as fr
    from flask import session as fs

    if not fs.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.mail_hq import inbox

    return jsonify(inbox(limit=int(fr.args.get("limit", 40) or 40)))


@app.route("/api/mail/message/<int:mid>", methods=["GET"])
def api_mail_message(mid):
    from flask import session as fs

    if not fs.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.mail_hq import message

    return jsonify(message(mid))


@app.route("/api/mail/draft-reply", methods=["POST"])
def api_mail_draft_reply():
    from flask import request as fr
    from flask import session as fs

    if not fs.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.mail_hq import draft_reply

    return jsonify(draft_reply(int((fr.get_json(silent=True) or {}).get("message_id") or 0)))


@app.route("/api/mail/queue-reply", methods=["POST"])
def api_mail_queue_reply():
    from flask import request as fr
    from flask import session as fs

    if not fs.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.mail_hq import queue_reply

    data = fr.get_json(silent=True) or {}
    return jsonify(queue_reply(int(data.get("message_id") or 0), data.get("body") or ""))


def _require_session(fn):
    """Cockpit session gate (owner-only browser session): 401 if no user_id, else run the
    handler. One definition — the action routes below share it instead of each re-inlining
    the check. The INTERNAL_API_KEY is applied server-side in the proxy, never client-side."""
    from functools import wraps

    @wraps(fn)
    def _wrapped(*a, **k):
        from flask import session as fs

        if not fs.get("user_id"):
            return jsonify({"error": "Not authenticated"}), 401
        return fn(*a, **k)

    return _wrapped


@app.route("/api/actions/catalog", methods=["GET"])
@_require_session
def api_actions_catalog():
    """Curated SAFE action catalog for the cockpit Tools & Actions bar. Slice 4 (COO
    command surface). Session-gated via @_require_session."""
    from services.coo_actions import catalog

    return jsonify(catalog())


@app.route("/api/actions/run", methods=["POST"])
@_require_session
def api_actions_run():
    """Run ONE curated SAFE action by key. Session-gated via @_require_session. The platform
    side runs only catalog keys (read-only diagnostics) — anything else is rejected there. Slice 4."""
    from flask import request as fr

    from services.coo_actions import run

    return jsonify(run((fr.get_json(silent=True) or {}).get("key") or ""))


@app.route("/api/voice/synthesize", methods=["POST"])
def api_voice_synthesize():
    """Owner-only TTS: speak a reply in A.R.C.H.I.E.'s Kokoro voice. Fail-soft
    (no audio -> the cockpit just shows text)."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text:
        return jsonify({"success": False, "error": "no text"}), 400
    from services.voice_proxy import synthesize

    return jsonify(synthesize(text, flask_session.get("user_id")))


@app.route("/api/voice/transcribe", methods=["POST"])
def api_voice_transcribe():
    """Owner-only STT: mic clip (multipart `audio`, or json `audio_b64`) -> the
    sovereign whisper sidecar. Fail-soft (no transcript -> owner types)."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    f = request.files.get("audio")
    if f:
        raw = f.read()
        mime = f.mimetype
    else:
        import base64

        data = request.get_json(silent=True) or {}
        try:
            raw = base64.b64decode(data.get("audio_b64") or "")
        except Exception:
            return jsonify({"text": "", "error": "bad audio"}), 400
        mime = data.get("mime")
    if len(raw) > 25 * 1024 * 1024:
        return jsonify({"text": "", "error": "audio too large"}), 413
    from services.voice_proxy import transcribe

    return jsonify(transcribe(raw, mime))


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

    try:
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
        # submit_director_report returns None ONLY on a genuine failure now (a
        # dedup collision returns the existing id). Log at the HTTP boundary so
        # the 500 is diagnosable instead of a bare "Failed to submit report".
        app.logger.error(
            "api_director_report: submit returned no id for [%s/%s] '%s' from %s",
            data.get("severity"), data.get("category"),
            data.get("title"), data.get("director_agent"),
        )
        return jsonify({"error": "Failed to submit report"}), 500
    except Exception as exc:
        app.logger.error("api_director_report: unhandled error — %s", exc, exc_info=True)
        return jsonify({"error": "internal error", "detail": str(exc)[:200]}), 500


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

    # CLI/API-key callers stream with a Bearer chat key (Track B: the CLI's
    # first-class entry point); browser sessions keep working unchanged.
    user_id = flask_session.get("user_id")
    if not user_id:
        from chat.auth_middleware import _check_bearer_token

        bearer_user = _check_bearer_token()
        user_id = (bearer_user or {}).get("id")
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
                elif isinstance(item, dict) and item.get("type") == "approvals_list_request":
                    # A.R.C.H.I.E. asked to show pending approvals -> fetch + render inline.
                    from services.approvals_proxy import list_pending

                    yield f"data: {_json.dumps({'type': 'approvals_list', 'approvals': list_pending()})}\n\n"
                elif isinstance(item, dict) and item.get("type") == "approval_action":
                    # Chat-native approve/deny. Owner user_id (bearer or session) forwarded;
                    # fail-CLOSED -> ok reflects the platform's real result.
                    from services.approvals_proxy import approve, deny

                    if item.get("verb") == "approve":
                        res = approve(item["approval_id"], user_id)
                    else:
                        res = deny(item["approval_id"], user_id, item.get("reason", ""))
                    yield f"data: {_json.dumps({'type': 'approval_done', 'approval_id': item['approval_id'], 'verb': item.get('verb'), 'ok': res.get('ok', False)})}\n\n"
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

    user_id = session.get("user_id")
    if not user_id:  # fail closed — never fall back to another user's (id 2) data
        return jsonify({"error": "Unauthorized"}), 401
    from services.conversation_service import escalate_to_claude

    result = escalate_to_claude(user_id=user_id, message=message)
    return jsonify(result)


@app.route("/api/claude/health")
def api_claude_health():
    """Check Claude bridge availability."""
    from collaboration.claude_bridge import get_claude_bridge

    bridge = get_claude_bridge()
    return jsonify(bridge.health_check())


@app.route("/api/collab/message", methods=["POST"])
def api_collab_message():
    """Collaboration tab — Kytran + A.R.C.H.I.E. + Claude trio session (#4285).

    A real-time scratchpad: returns three distinct voices (kytran / archie /
    claude) WITHOUT persisting to the main chat conversation. Ephemeral by
    design — the Claude bridge keeps in-memory continuity for the session, but
    nothing hits unified_conversations, so the Chat tab + History stay clean.
    """
    from flask import session

    if "user_id" not in session and "kytran_user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    # silent=True so a malformed/empty body yields {} (clean 400) instead of
    # raising an unhandled 400/415 HTML error.
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400

    from collaboration.claude_bridge import get_claude_bridge

    bridge = get_claude_bridge()
    health = bridge.health_check()
    if health.get("status") != "healthy":
        return jsonify({
            "available": False,
            "note": health.get("note", "Claude bridge offline"),
        })

    # A.R.C.H.I.E. frames the request for Claude (COO collaborating with the
    # CEO), mirroring escalate_to_claude() but without any DB writes.
    archie_line = "On it — bringing Claude in to think this through with us."
    framed = (
        "A.R.C.H.I.E. (COO) is collaborating with Kytran (CEO) and wants your "
        "take on this:\n\n"
        f"{message}"
    )
    try:
        claude_reply = bridge.send_message(framed)
    except Exception as exc:  # bridge call must never 500 the tab
        logger.error("collab message: bridge call failed: %s", exc)
        claude_reply = None

    if not claude_reply:
        return jsonify({
            "available": False,
            "note": "Claude was reachable but returned no response — try again.",
        })

    return jsonify({
        "available": True,
        "kytran": message,
        "archie": archie_line,
        "claude": claude_reply,
    })


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

    user_id = session.get("user_id")
    if not user_id:  # fail closed — never fall back to another user's (id 2) data
        return jsonify({"error": "Unauthorized"}), 401
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

    user_id = session.get("user_id")
    if not user_id:  # fail closed — never fall back to another user's (id 2) data
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    from services.conversation_service import new_conversation

    conv_id = new_conversation(user_id, topic=data.get("topic"))
    return jsonify({"conversation_id": conv_id})


@app.route("/api/chat/conversations/<int:conv_id>", methods=["DELETE"])
def api_chat_delete_conversation(conv_id):
    """Delete a conversation + its messages. Owner-scoped by user_id (IDOR-safe) —
    matches how the conversation LIST is scoped, so a user can only delete their own."""
    from flask import session

    if "user_id" not in session and "kytran_user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session.get("user_id")
    if not user_id:  # fail closed — never fall back to another user's (id 2) data
        return jsonify({"error": "Unauthorized"}), 401
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT 1 FROM unified_conversations WHERE id = %s AND user_id = %s",
            (conv_id, user_id),
        )
        if not cur.fetchone():
            return jsonify({"error": "Not found"}), 404
        cur.execute("DELETE FROM unified_messages WHERE conversation_id = %s", (conv_id,))
        cur.execute(
            "DELETE FROM unified_conversations WHERE id = %s AND user_id = %s",
            (conv_id, user_id),
        )

    return jsonify({"success": True, "deleted": conv_id})


@app.route("/api/chat/history", methods=["GET"])
def api_chat_history():
    """Full conversation archive for the History tab — ALL of the user's threads
    (incl. archived), each with a message count + first-message preview. Owner-scoped
    by user_id (read-only). The left sidebar list shows only active threads; this is
    the complete searchable history."""
    from flask import session

    if "user_id" not in session and "kytran_user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session.get("user_id")
    if not user_id:  # fail closed — never fall back to another user's (id 2) data
        return jsonify({"error": "Unauthorized"}), 401
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT c.id, c.title, c.topic, c.status, c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM unified_messages m
                      WHERE m.conversation_id = c.id) AS msg_count,
                   (SELECT m.content FROM unified_messages m
                      WHERE m.conversation_id = c.id AND m.direction = 'inbound'
                      ORDER BY m.id ASC LIMIT 1) AS first_msg
            FROM unified_conversations c
            WHERE c.user_id = %s
            ORDER BY c.updated_at DESC NULLS LAST, c.id DESC
            LIMIT 300
            """,
            (user_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]

    return jsonify({"conversations": rows})


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


@app.route("/api/skills")
def api_skills_registry():
    """#5334 Skills rail: the platform's invokable-skills registry. Session-gated.

    The rail is a THIN proxy — the hub owns the registry, so the cockpit never
    keeps a parallel list that goes stale when a capability is added.
    """
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    try:
        return jsonify(_call_platform_invokable_skills()), 200
    except Exception as exc:
        logger.error("api_skills_registry: platform call failed: %s", exc)
        return jsonify({"error": "Skills registry unavailable"}), 503


@app.route("/api/skills/invoke", methods=["POST"])
def api_skills_invoke():
    """#5334: fire one platform skill from the cockpit rail, attributed to 'cockpit'.

    Capability is NOT validated here: the hub owns the registry and rejects an
    unknown capability itself (400). A local allowlist would be a second source
    of truth that goes stale the moment a capability is added.
    """
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json(silent=True) or {}
    capability = (data.get("capability") or "").strip()
    if not capability:
        return jsonify({"error": "capability required"}), 400
    reason = (data.get("reason") or "").strip() or f"cockpit Skills rail: {capability}"

    try:
        result = _call_platform_delegation_submit(
            capability, reason, data.get("args") or {}, delegation_source="cockpit"
        )
        return jsonify(result), 200
    except Exception as exc:
        logger.error("api_skills_invoke(%s): platform call failed: %s", capability, exc)
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


# ── Building Machine bridge — drive the archie_engine "building machine" from
#    the cockpit. The engine speaks a request/reply WebSocket protocol on
#    archie_engine:9090 (container DNS). The browser can't reach it directly
#    (remote + container-internal), so archie_comms proxies one round-trip. ──

def _engine_ws_call(payload, timeout=45):
    """Open a short-lived ws to the archie_engine container, send one JSON
    message, return the single JSON reply (the engine is request/reply)."""
    import json as _json
    import os as _os
    from websocket import create_connection

    url = _os.getenv("ENGINE_WS_URL", "ws://archie_engine:9090")
    ws = create_connection(url, timeout=timeout)
    try:
        ws.send(_json.dumps(payload))
        return _json.loads(ws.recv())
    finally:
        try:
            ws.close()
        except Exception:
            pass


@app.route("/api/engine/status")
def api_engine_status():
    """Building Machine (archie_engine) status for the cockpit rail."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    try:
        hub = _engine_ws_call({"type": "hub_status"}, timeout=8)
        skills = _engine_ws_call({"type": "list_skills"}, timeout=8)
        return jsonify({
            "online": True,
            "hub_status": hub.get("hub_status"),
            "skills": [s.get("name") for s in (skills.get("skills") or []) if s.get("name")],
        })
    except Exception as exc:
        logger.warning("api_engine_status failed: %s", exc)
        return jsonify({"online": False, "hub_status": None, "skills": []})


@app.route("/api/engine/message", methods=["POST"])
def api_engine_message():
    """Send a task to the Building Machine. The engine classifies it and
    dispatches: LLM intents → DHQ (delegation to the team); tool ops → local
    file/git/shell tools. Returns the engine's single reply."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or data.get("message") or "").strip()
    if not content:
        return jsonify({"error": "Empty message"}), 400
    try:
        resp = _engine_ws_call({"type": "message", "content": content}, timeout=60)
        return jsonify({
            "response": resp.get("content") or resp.get("error") or "(no response)",
            "intent": resp.get("intent"),
            "dispatch_target": resp.get("dispatch_target"),
            "tool_calls": resp.get("tool_calls") or [],
        })
    except Exception as exc:
        logger.error("api_engine_message failed: %s", exc)
        return jsonify({"response": "Building Machine unreachable.", "error": str(exc)[:120]})


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
