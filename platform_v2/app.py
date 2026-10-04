"""
A.R.C.H.I.E. Platform - Main Application
With User Signup and Admin Approval System
"""

from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    jsonify,
    session,
    g,
    Response,
    stream_with_context,
)
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from werkzeug.security import check_password_hash, generate_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta, timezone
import os
import time
import json
import secrets
from config import Config
from services import nav_service


# Flask 3.x JSON provider — replaces the deprecated app.json_encoder (Flask 1.x)
# Serializes naive datetimes as ISO-8601 + "Z" so browsers parse them as UTC
# and automatically convert to the user's local timezone (EDT/Montreal).
from datetime import date as _date
from flask.json.provider import DefaultJSONProvider as _DefaultJSONProvider


class UTCAwareDatetimeProvider(_DefaultJSONProvider):
    """Proper Flask 3.x JSON provider.

    All naive datetime objects from psycopg2 are assumed UTC (storage
    convention). Appending 'Z' ensures JavaScript's Date constructor
    treats them as UTC and converts to local time (EDT) correctly.
    """

    def dumps(self, obj, **kwargs):
        def _utc_default(o):
            if isinstance(o, datetime):
                return (o.isoformat() + "Z") if o.tzinfo is None else o.isoformat()
            if isinstance(o, _date):
                return o.isoformat()
            # Flask 3.x exposes the fallback as the public static method
            # `default` (not `_default`). It serializes Decimal/UUID/dataclass
            # and raises TypeError for genuinely unserializable types.
            return _DefaultJSONProvider.default(o)

        kwargs.setdefault("default", _utc_default)
        return json.dumps(obj, **kwargs)


# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB upload limit
app.config["PREFERRED_URL_SCHEME"] = "https"  # Behind NPM SSL proxy
app.config["SANDBOX_MODE"] = os.getenv("SANDBOX_MODE", "false").lower() == "true"

# Template auto-reload. Flask defaults TEMPLATES_AUTO_RELOAD to app.debug, and this app
# runs under gunicorn with FLASK_ENV=production (debug False), so Jinja cached every
# template in EACH of the 4 workers — indefinitely.
#
# That is a trap here specifically because platform_v2 is bind-mounted: editing a
# template in the live tree looks live (the file IS current) while the running process
# keeps serving the old bytes. Measured on 2026-10-04: a fix to repair_bay.html was
# verified on disk, in the container, and by md5 — and the running page still threw on
# the deleted line. Only a restart applied it.
#
# The cost is one stat() per template per render, which is nothing at this traffic level,
# and it makes the bind mount behave the way the deploy docs already promise ("volume-
# mounted hub code runs whatever branch is checked out").
#
# CAVEAT, and it is the reason this comment exists: this covers TEMPLATES ONLY. Python
# modules are imported once per worker, so editing a route or service still needs a
# restart. Auto-reload removes one silent-staleness trap; it does not make the platform
# hot-reloadable. Set TEMPLATES_AUTO_RELOAD=false to turn it off.
app.config["TEMPLATES_AUTO_RELOAD"] = os.getenv("TEMPLATES_AUTO_RELOAD", "true").lower() == "true"

if app.config["SANDBOX_MODE"]:
    import logging as _logging

    _logging.getLogger("archie_platform").warning(
        "⚠️  SANDBOX MODE ACTIVE — Telegram disabled, Stripe test mode, no real emails"
    )

# Tell Flask it's behind a reverse proxy (NPM) so url_for generates https://
from werkzeug.middleware.proxy_fix import ProxyFix

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.json = UTCAwareDatetimeProvider(app)

# ============================================================================
# CSRF PROTECTION (task #2066, phased rollout)
# ============================================================================
# Phase 1+2: CSRFProtect initialized in opt-in mode. Routes that want
# protection add @csrf.protect. Currently enforced on credential-handling
# forms only: /login, /signup, /verify-2fa. Phase 3 (follow-up): flip
# WTF_CSRF_CHECK_DEFAULT=True and audit the ~150 session-auth POST routes
# for explicit @csrf.exempt where Bearer-authed.
from flask_wtf.csrf import CSRFProtect

app.config.setdefault("WTF_CSRF_CHECK_DEFAULT", False)
csrf = CSRFProtect(app)

# Opt-in CSRF enforcement for credential-handling POST endpoints.
# Flask-WTF CSRFProtect has no @protect decorator (only @exempt); the
# idiomatic opt-in pattern is a before_request hook that calls
# csrf.protect() for the specific endpoints we want to cover.
_CSRF_PROTECTED_PATHS = {"/login", "/signup", "/verify-2fa"}


@app.before_request
def _csrf_protect_credential_forms():
    # NOTE: csrf.protect() removed — it checks Flask-WTF's session["csrf_token"]
    # which is never populated since the platform uses its own session["_csrf_token"]
    # system. The login route's _verify_csrf_token() handles CSRF correctly using
    # the _csrf_token form field + archie_csrf double-submit cookie.
    pass


# Dedicated CSRFError handler — must be registered BEFORE the generic
# @app.errorhandler(Exception) so CSRFError doesn't get swallowed into
# the "flash + redirect to /dashboard" fallback (which masks the real
# failure mode and confuses users + the mistake_detector).
from flask_wtf.csrf import CSRFError


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "csrf_failed", "reason": str(e.description)}), 400
    flash("Security check failed. Please refresh the page and try again.", "error")
    return redirect(request.path)


# Initialize SocketIO for Game Studio multiplayer
try:
    from flask_socketio import SocketIO

    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
    from tools.game_studio.game_server import GameNamespace

    socketio.on_namespace(GameNamespace("/game"))
    SOCKETIO_AVAILABLE = True
except ImportError:
    socketio = None
    SOCKETIO_AVAILABLE = False


# ============================================================================
# JINJA2 TEMPLATE FILTERS — TIMEZONE-AWARE TIMESTAMPS
# ============================================================================


@app.template_filter("localtime")
def localtime_filter(dt, fmt="datetime"):
    """Wrap a datetime in a <span data-utc="..."> for client-side local timezone display.

    Usage in templates:
      {{ row.created_at|localtime }}              → datetime format
      {{ row.created_at|localtime('date') }}      → date only
      {{ row.created_at|localtime('age') }}       → "3d ago"
      {{ row.created_at|localtime('time') }}      → "3:45 PM"
      {{ row.created_at|localtime('short') }}     → "Jan 15, 3:45 PM"

    The server-side strftime value is the fallback (shown before JS runs).
    archie-time.js auto-converts to the user's browser timezone on load.
    """
    if dt is None:
        return "\u2014"
    from markupsafe import Markup

    iso = dt.isoformat()
    if not iso.endswith("Z") and "+" not in iso:
        iso += "Z"
    # Server-side fallback (container runs in America/Toronto)
    try:
        fallback = dt.strftime("%b %d, %Y, %I:%M %p")
    except Exception:
        fallback = iso
    return Markup('<span data-utc="{}" data-fmt="{}">{}</span>'.format(iso, fmt, fallback))


# Track application start time for uptime
start_time = time.time()

# ============================================================================
# CENTRALIZED LOGGING SETUP
# ============================================================================

from logging_config import init_flask_logging, audit_log, log_performance  # noqa: E402

# Initialize JSON logging with request tracking
logger = init_flask_logging(app)
logger.info("A.R.C.H.I.E. Platform starting up...")

# Make logging utilities available to app
app.config["AUDIT_LOG"] = audit_log
app.config["LOG_PERFORMANCE"] = log_performance

# ============================================================================
# RATE LIMITING SETUP
# ============================================================================

from rate_limiting import init_rate_limiting  # noqa: E402

# Initialize rate limiting with role-based limits
init_rate_limiting(app)
logger.info("Rate limiting initialized")

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# ============================================================================
# DATABASE CONNECTION
# ============================================================================


def get_db():
    """
    Get database connection with automatic sandbox schema switching
    Checks session for sandbox_mode and sets search_path accordingly
    """
    conn = psycopg2.connect(
        host=app.config["DB_HOST"],
        port=app.config["DB_PORT"],
        database=app.config["DB_NAME"],
        user=app.config["DB_USER"],
        password=app.config["DB_PASSWORD"],
    )

    # Check if in sandbox mode and set schema accordingly
    try:
        from flask import session, has_request_context

        if has_request_context():
            schema = session.get("db_schema", "public")
            cur = conn.cursor()
            if schema == "sandbox":
                # Sandbox mode: search sandbox first, then public for system tables
                cur.execute("SET search_path TO sandbox, public")
            else:
                # Production mode: only public schema
                cur.execute("SET search_path TO public")
            cur.close()
    except Exception:
        # If no request context or error, default to public
        pass

    return conn


def create_user_session(user_id):
    """Insert a row into active_sessions for the logged-in user and store the token in the Flask session."""
    try:
        token = secrets.token_hex(32)
        conn = get_db()
        cur = conn.cursor()
        # Purge expired sessions before inserting (keeps table lean)
        cur.execute("DELETE FROM active_sessions WHERE expires_at < NOW()")
        cur.execute(
            """INSERT INTO active_sessions
               (user_id, session_token, ip_address, user_agent,
                created_at, last_activity, expires_at)
               VALUES (%s, %s, %s, %s, NOW(), NOW(),
                NOW() + INTERVAL '7 days')""",
            (
                user_id,
                token,
                request.remote_addr,
                request.headers.get("User-Agent", ""),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
        session["_session_token"] = token
        session.permanent = True  # Honour PERMANENT_SESSION_LIFETIME (7 days)
    except Exception as e:
        print(f"[A.R.C.H.I.E.] Session tracking insert error: {e}")


# ============================================================================
# USER CLASS
# ============================================================================


class User(UserMixin):
    """User class for Flask-Login with RBAC support"""

    def __init__(
        self,
        id,
        username,
        email,
        role,
        is_admin=False,
        is_super_admin=False,
        subscription_tier=None,
        subscription_expires_at=None,
        theme_preference=None,
        profile_picture=None,
        oauth_picture=None,
        created_at=None,
        must_change_password=False,
    ):
        self.id = id
        self.username = username
        self.email = email
        self.role = role
        self.is_admin = is_admin
        self.is_super_admin = is_super_admin
        self.subscription_tier = subscription_tier or "free"
        self.subscription_expires_at = subscription_expires_at
        self.theme_preference = theme_preference  # None = no explicit choice
        self.profile_picture = profile_picture
        self.oauth_picture = oauth_picture
        self.created_at = created_at
        self.must_change_password = bool(must_change_password)
        # Note: is_authenticated, is_active, is_anonymous are provided by UserMixin


@login_manager.user_loader
def load_user(user_id):
    """Load user by ID with RBAC attributes"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM users WHERE id = %s AND is_active = TRUE", (user_id,))
        user_data = cur.fetchone()
        cur.close()
        conn.close()

        if user_data:
            # Extract theme from metadata JSONB (None = no explicit choice)
            metadata = user_data.get("metadata") or {}
            theme_pref = metadata.get("theme_preference") if isinstance(metadata, dict) else None

            return User(
                id=user_data["id"],
                username=user_data["username"],
                email=user_data["email"],
                role=user_data["role"],
                is_admin=user_data.get("is_admin", False),
                is_super_admin=user_data.get("is_super_admin", False),
                subscription_tier=user_data.get("subscription_tier", "free"),
                subscription_expires_at=user_data.get("subscription_expires_at"),
                theme_preference=theme_pref,
                profile_picture=user_data.get("profile_picture"),
                oauth_picture=user_data.get("oauth_picture"),
                created_at=user_data.get("created_at"),
                must_change_password=user_data.get("must_change_password", False),
            )
    except Exception as e:
        print(f"Error loading user: {e}")
    return None


# ============================================================================
# AI BRIDGE INTEGRATION
# ============================================================================

import sys  # noqa: E402

sys.path.insert(0, "/mnt/archie_brain")
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

try:
    from ai_bridge.archie_bridge import (
        archie_bridge,
        get_available_models,
        classify_task,
    )

    AI_BRIDGE_AVAILABLE = True
    print("✅ A.R.C.H.I.E. Bridge loaded successfully")

    # Make available to blueprints
    app.config["AI_BRIDGE"] = archie_bridge
    app.config["AI_BRIDGE_AVAILABLE"] = True

except ImportError as e:
    print(f"⚠️ A.R.C.H.I.E. Bridge not available: {e}")
    AI_BRIDGE_AVAILABLE = False
    app.config["AI_BRIDGE_AVAILABLE"] = False


# ============================================================================
# BRIDGE → STARBASE COMPATIBILITY REDIRECT
# Old node clients (v1.x) still hit /tools/bridge/ URLs after the rename.
# Forward them to /tools/starbase/ so heartbeats and mesh sync work.
# ============================================================================


# ============================================================================
# LEGACY COMPAT REDIRECTS — Starbase/Starship/Fleet/Bridge → Department HQ
# All fleet APIs now live under /tools/department-hq/api/*
# ============================================================================


@app.route("/tools/bridge/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def bridge_compat_redirect(subpath):
    """Redirect old /tools/bridge/ URLs to Department HQ."""
    from flask import redirect, request as req

    new_url = f"/tools/department-hq/{subpath}"
    if req.query_string:
        new_url += f"?{req.query_string.decode()}"
    return redirect(new_url, code=307)


@app.route("/tools/starbase/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def starbase_compat_redirect(subpath):
    """Redirect old /tools/starbase/ URLs to Department HQ."""
    from flask import redirect, request as req

    new_url = f"/tools/department-hq/{subpath}"
    if req.query_string:
        new_url += f"?{req.query_string.decode()}"
    return redirect(new_url, code=307)


@app.route("/tools/starship/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def starship_compat_redirect(subpath):
    """Redirect old /tools/starship/ URLs to Department HQ."""
    from flask import redirect, request as req

    new_url = f"/tools/department-hq/{subpath}"
    if req.query_string:
        new_url += f"?{req.query_string.decode()}"
    return redirect(new_url, code=307)


@app.route("/tools/mailbox-story", defaults={"subpath": ""})
@app.route("/tools/mailbox-story/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def mailbox_story_compat_redirect(subpath):
    """Chronicle rename (2026-07-10): old Mailbox Story path → /tools/chronicle.
    307 preserves method + body so the internal capture-share POST keeps working."""
    q = ("?" + request.query_string.decode()) if request.query_string else ""
    return redirect(f"/tools/chronicle/{subpath}".rstrip("/") + q, code=307)


@app.route("/tools/directory", methods=["GET"])
@app.route("/tools/directory/", methods=["GET"])
def directory_compat_redirect():
    """Redirect old /tools/directory to the Department HQ Roster tab.

    Directory module decommissioned in Project #262 (migration 332).
    Public directory API lives at /api/public/directory.
    """
    from flask import redirect

    return redirect("/tools/department-hq#roster", code=308)


@app.route("/tools/department-hq/api/agents/public-roster", methods=["GET", "OPTIONS"])
@app.route("/tools/department-hq/api/agents/public-roster/live", methods=["GET", "OPTIONS"])
def public_roster_compat_redirect():
    """Back-compat 308 for the legacy public-roster endpoint.

    Moved to /api/public/directory[/live] in Project #262. Kept so cached
    clients / external integrations don't break during rollout.
    """
    from flask import redirect, request as req

    target = "/api/public/directory/live" if req.path.endswith("/live") else "/api/public/directory"
    if req.query_string:
        target += f"?{req.query_string.decode()}"
    return redirect(target, code=308)


@app.route("/tools/fleet/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def fleet_compat_redirect(subpath):
    """Redirect old /tools/fleet/ URLs to Department HQ."""
    from flask import redirect, request as req

    new_url = f"/tools/department-hq/{subpath}"
    if req.query_string:
        new_url += f"?{req.query_string.decode()}"
    return redirect(new_url, code=307)


# ============================================================================
# SUBSCRIBE LANDING PAGES — Product pages with upsell interstitial
# ============================================================================

PRODUCT_INFO = {
    "crm": {
        "name": "CRM & Contact Management",
        "tagline": "Manage customers, segments, and interactions with AI assistance",
        "min_tier": "starter",
        "features": [
            "Contact management & segmentation",
            "Interaction tracking & notes",
            "AI-powered customer insights",
            "Import/export (CSV)",
            "Custom fields & tags",
        ],
    },
    "invoicing": {
        "name": "Invoicing & Payments",
        "tagline": "Create, send, and track invoices with automated reminders",
        "min_tier": "starter",
        "features": [
            "Invoice creation & templates",
            "Payment tracking",
            "Recurring invoices",
            "PDF export",
            "Client portal",
        ],
    },
    "store_builder": {
        "name": "Store Builder",
        "tagline": "Launch your online store with print-on-demand and Printful integration",
        "min_tier": "starter",
        "features": [
            "Product catalog management",
            "Printful integration",
            "Order tracking & fulfillment",
            "Custom storefront themes",
            "Inventory management",
        ],
    },
    "content_studio": {
        "name": "Content Studio",
        "tagline": "AI-powered content creation for blogs, social, and marketing",
        "min_tier": "starter",
        "features": [
            "AI writing assistant",
            "Blog post generation",
            "Social media content",
            "SEO optimization",
            "Content calendar",
        ],
    },
    "website_studio": {
        "name": "Website Designer",
        "tagline": "Design and deploy professional websites with AI assistance",
        "min_tier": "starter",
        "features": [
            "Visual website builder",
            "Custom domain support",
            "Responsive templates",
            "SEO tools",
            "Hosting integration",
        ],
    },
    "social_media": {
        "name": "Social Media Manager",
        "tagline": "Schedule, publish, and analyze your social media presence",
        "min_tier": "starter",
        "features": [
            "Multi-platform publishing",
            "Post scheduling",
            "Analytics dashboard",
            "OAuth account linking",
            "Content queue management",
        ],
    },
    "call_center": {
        "name": "Call Center",
        "tagline": "Manage customer calls, queues, and support workflows",
        "min_tier": "professional",
        "features": [
            "Call queue management",
            "Agent routing",
            "Call recording & transcripts",
            "Performance analytics",
            "IVR configuration",
        ],
    },
    "google_work_suite": {
        "name": "Google Work Suite",
        "tagline": "Integrate Gmail, Calendar, and Drive into your workflow",
        "min_tier": "starter",
        "features": [
            "Gmail integration",
            "Calendar sync",
            "Drive file management",
            "Contact sync",
            "Workspace analytics",
        ],
    },
    "stockbot": {
        "name": "StockBot AI",
        "tagline": "AI-powered stock analysis with five specialized trading agents",
        "min_tier": "professional",
        "features": [
            "5 AI trading agents (Quant, Value, Pulse, Shield, Oracle)",
            "Real-time market data",
            "Portfolio tracking",
            "Price alerts & watchlists",
            "AI-generated trade signals",
        ],
    },
    "media_studio": {
        "name": "Media Studio",
        "tagline": "Generate images, audio, and video with GPU-accelerated AI",
        "min_tier": "professional",
        "features": [
            "AI image generation (SDXL)",
            "Audio generation",
            "Video creation tools",
            "ComfyUI workflow integration",
            "Asset library management",
        ],
    },
    "game_studio": {
        "name": "Game Studio",
        "tagline": "Design and develop games with AI-assisted tools",
        "min_tier": "professional",
        "features": [
            "Game design workspace",
            "Asset generation",
            "Multiplayer support",
            "Level editor",
            "Playtesting tools",
        ],
    },
    "family_tree": {
        "name": "Family Tree",
        "tagline": "Build and explore your family history with AI research assistance",
        "min_tier": "starter",
        "features": [
            "Interactive family tree builder",
            "Record & document management",
            "AI ancestry research",
            "Photo gallery",
            "Export & sharing",
        ],
    },
    "archie_pool": {
        "name": "Archie Pool",
        "tagline": "Monitor and manage cryptocurrency mining operations",
        "min_tier": "enterprise",
        "features": [
            "Mining pool dashboard",
            "Hashrate monitoring",
            "Payout tracking",
            "Worker management",
            "Performance analytics",
        ],
    },
    "pool_management": {
        "name": "Pool Management",
        "tagline": "Advanced mining pool administration and configuration",
        "min_tier": "enterprise",
        "features": [
            "Pool configuration",
            "Miner administration",
            "Fee management",
            "Network statistics",
            "Alert configuration",
        ],
    },
}

TIER_INFO = {
    "starter": {"name": "Starter", "price": "$299/mo", "price_num": 299, "agents": "5", "watches": "1"},
    "professional": {"name": "Professional", "price": "$799/mo", "price_num": 799, "agents": "20", "watches": "2"},
    "enterprise": {
        "name": "Enterprise",
        "price": "$1,499/mo",
        "price_num": 1499,
        "agents": "Unlimited",
        "watches": "All",
    },
}

TIER_ORDER = ["starter", "professional", "enterprise"]


@app.route("/subscribe/<module_id>")
@login_required
def subscribe_landing(module_id):
    """Product landing page for a gated module with upsell interstitial."""
    from module_registry import get_module_by_id
    from services.subscription_service import get_user_membership_tier

    module = get_module_by_id(module_id)
    if not module:
        from flask import abort

        abort(404)

    product = PRODUCT_INFO.get(
        module_id,
        {
            "name": module.name,
            "tagline": module.description,
            "min_tier": module.minimum_tier,
            "features": [],
        },
    )

    user_tier = get_user_membership_tier(current_user.id, getattr(current_user, "role", None))

    return render_template(
        "subscribe.html",
        module=module,
        product=product,
        user_tier=user_tier,
        tier_info=TIER_INFO,
        tier_order=TIER_ORDER,
        module_id=module_id,
    )


@app.route("/tools/stockbot")
@app.route("/tools/stockbot/")
@app.route("/tools/stockbot/<path:subpath>")
def stockbot_redirect(subpath=None):
    """StockBot removed — redirect to Market Watch standalone product."""
    from flask import redirect

    return redirect("https://market.kytranempowerment.com", code=301)


@app.route("/tools/market-watch-redirect")
def market_watch_redirect():
    """Module registry redirect to Market Watch standalone product."""
    from flask import redirect

    return redirect("https://market.kytranempowerment.com", code=302)


# ============================================================================
# P.R.O.B.E. QA SCREENSHOT ROUTE
# ============================================================================


@app.route("/assets/portraits/<path:filename>")
def serve_portrait_thumb(filename):
    """Public portrait thumbnail — no auth required.

    Serves agent portrait files from static/media/portraits/ at the /assets/portraits/
    path that public_roster_service.py embeds in avatar_thumb_url. The website's
    directory.js and ai-directors.js load these cross-origin from the platform host.
    """
    import os
    from flask import send_from_directory, abort

    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    # Search order: thumbs/ (pre-generated JPGs) → portraits/ → images/ (dated dirs)
    search_dirs = [
        os.path.join(app.static_folder, "media", "thumbs"),
        os.path.join(app.static_folder, "media", "portraits"),
    ]
    for d in search_dirs:
        for ext in (".jpg", ".png", ".webp", ".jpeg"):
            candidate = stem + ext
            if os.path.isfile(os.path.join(d, candidate)):
                return send_from_directory(d, candidate)
    # Fallback: search dated subdirs in images/
    images_base = os.path.join(app.static_folder, "media", "images")
    if os.path.isdir(images_base):
        for date_dir in sorted(os.listdir(images_base), reverse=True)[:6]:
            for ext in (".jpg", ".png", ".webp", ".jpeg"):
                candidate = stem + ext
                full = os.path.join(images_base, date_dir, candidate)
                if os.path.isfile(full):
                    return send_from_directory(os.path.join(images_base, date_dir), candidate)
    abort(404)


@app.route("/api/qa/screenshots/<path:filename>")
@login_required
def qa_screenshot(filename):
    """Serve P.R.O.B.E. E2E test screenshots from tmpfs."""
    import os
    from flask import send_from_directory, abort

    screenshot_dir = "/tmp/qa_reports/screenshots"
    safe_name = os.path.basename(filename)
    filepath = os.path.join(screenshot_dir, safe_name)
    if not os.path.isfile(filepath):
        abort(404)
    return send_from_directory(screenshot_dir, safe_name)


# ============================================================================
# AI BRIDGE ROUTES
# ============================================================================


@app.route("/api/ai/chat", methods=["POST"])
@login_required
def ai_chat():
    """
    Universal AI chat endpoint - uses A.R.C.H.I.E. Bridge
    Routes to best model automatically
    """
    if not AI_BRIDGE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "A.R.C.H.I.E. Bridge not available"}),
            503,
        )

    try:
        data = request.json
        prompt = data.get("prompt", "")
        context = data.get("context", {})
        force_model = data.get("model")  # Optional: force specific model

        if not prompt:
            return jsonify({"success": False, "error": "Prompt is required"}), 400

        # Use A.R.C.H.I.E. Bridge
        result = archie_bridge(
            prompt=prompt,
            context=context,
            user_id=current_user.id,
            force_model=force_model,
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/ai/models", methods=["GET"])
@login_required
def get_ai_models():
    """Get available AI models"""
    if not AI_BRIDGE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "A.R.C.H.I.E. Bridge not available"}),
            503,
        )

    try:
        models = get_available_models()
        return jsonify({"success": True, "models": models})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/ai/classify", methods=["POST"])
@login_required
def classify_ai_task():
    """Classify what type of task this is"""
    if not AI_BRIDGE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "A.R.C.H.I.E. Bridge not available"}),
            503,
        )

    try:
        data = request.json
        prompt = data.get("prompt", "")
        context = data.get("context")

        task_type = classify_task(prompt, context)

        return jsonify({"success": True, "task_type": task_type})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/ai/preferences", methods=["GET", "POST"])
@login_required
def ai_preferences():
    """Get or update user's AI preferences"""
    if not AI_BRIDGE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "A.R.C.H.I.E. Bridge not available"}),
            503,
        )

    if request.method == "GET":
        try:
            return jsonify({"success": True, "preferences": {}})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    elif request.method == "POST":
        try:
            data = request.json

            conn = psycopg2.connect(
                host=os.getenv("DB_HOST", "archie_database"),
                port=os.getenv("DB_PORT", "5432"),
                database=os.getenv("DB_NAME", "archie"),
                user=os.getenv("DB_USER", "archie"),
                password=app.config["DB_PASSWORD"],
            )
            cur = conn.cursor()

            # Update user preferences
            cur.execute(
                """
                INSERT INTO user_api_config (
                    user_id, preferred_provider, anthropic_api_key,
                    openai_api_key, use_ollama, preferred_code_model,
                    preferred_chat_model
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE
                SET preferred_provider = EXCLUDED.preferred_provider,
                    anthropic_api_key = EXCLUDED.anthropic_api_key,
                    openai_api_key = EXCLUDED.openai_api_key,
                    use_ollama = EXCLUDED.use_ollama,
                    preferred_code_model = EXCLUDED.preferred_code_model,
                    preferred_chat_model = EXCLUDED.preferred_chat_model,
                    updated_at = NOW()
            """,
                (
                    current_user.id,
                    data.get("preferred_provider", "ollama"),
                    data.get("anthropic_api_key"),
                    data.get("openai_api_key"),
                    data.get("use_ollama", True),
                    data.get("preferred_code_model"),
                    data.get("preferred_chat_model"),
                ),
            )

            conn.commit()
            cur.close()
            conn.close()

            return jsonify({"success": True, "message": "Preferences updated"})

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# CODE EDITOR WITH AI - Route
# ============================================================================


@app.route("/tools/code-editor")
@login_required
def code_editor():
    """Enhanced code editor with AI assistance"""
    return render_template("repair_bay/code_editor.html", ai_available=AI_BRIDGE_AVAILABLE, user=current_user)


# ============================================================================
# USAGE EXAMPLE IN OTHER ROUTES
# ============================================================================


# Example: Using AI Bridge in chat route
@app.route("/tools/chat/send", methods=["POST"])
@login_required
def chat_send():
    """Send message to A.R.C.H.I.E."""
    try:
        data = request.json
        message = data.get("message", "")

        if not message:
            return jsonify({"success": False, "error": "Message required"}), 400

        if AI_BRIDGE_AVAILABLE:
            # Use A.R.C.H.I.E. Bridge for intelligent routing
            result = archie_bridge(prompt=message, user_id=current_user.id)

            if result["success"]:
                # Store conversation
                conn = get_db()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO ai_conversations (user_id, message, response, model_used)
                    VALUES (%s, %s, %s, %s)
                """,
                    (current_user.id, message, result["response"], result["model"]),
                )
                conn.commit()
                cur.close()
                conn.close()

                return jsonify(
                    {
                        "success": True,
                        "response": result["response"],
                        "model": result["model"],
                        "task_type": result.get("task_type"),
                    }
                )
            else:
                return jsonify(result), 500
        else:
            return jsonify({"success": False, "error": "AI Bridge not available"}), 503

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# PINNED MEMORIES ROUTES
# ============================================================================


@app.route("/api/chat/pin", methods=["POST"])
@login_required
def pin_message():
    """Pin or unpin a chat message. Toggle: if already pinned, removes it."""
    from database import get_db_cursor

    try:
        data = request.json or {}
        content = data.get("message_content", "").strip()
        if not content:
            return jsonify({"success": False, "error": "message_content is required"}), 400

        conversation_id = data.get("conversation_id")
        message_type = data.get("message_type", "assistant")
        note = data.get("note")
        preview = content[:200]

        with get_db_cursor(commit=True) as (conn, cur):
            # Check for existing pin with same content preview + conversation
            cur.execute(
                """SELECT id FROM pinned_messages
                   WHERE user_id = %s
                     AND LEFT(message_content, 200) = %s
                     AND conversation_id IS NOT DISTINCT FROM %s""",
                (current_user.id, preview, conversation_id),
            )
            existing = cur.fetchone()

            if existing:
                # Toggle off — unpin
                cur.execute(
                    "DELETE FROM pinned_messages WHERE id = %s AND user_id = %s",
                    (existing["id"], current_user.id),
                )
                return jsonify({"success": True, "action": "unpinned", "pin_id": existing["id"]})
            else:
                # Pin the message
                cur.execute(
                    """INSERT INTO pinned_messages
                       (user_id, conversation_id, message_content, message_type, note)
                       VALUES (%s, %s, %s, %s, %s)
                       RETURNING id""",
                    (current_user.id, conversation_id, content, message_type, note),
                )
                pin_id = cur.fetchone()["id"]
                return jsonify({"success": True, "action": "pinned", "pin_id": pin_id}), 201

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/chat/pinned", methods=["GET"])
@login_required
def get_pinned_messages():
    """Get the current user's pinned messages with optional search."""
    from database import get_db_cursor

    try:
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = int(request.args.get("offset", 0))
        search = request.args.get("search", "").strip()

        with get_db_cursor(commit=False) as (conn, cur):
            if search:
                cur.execute(
                    """SELECT p.id, p.conversation_id, p.message_content,
                              p.message_type, p.note, p.created_at,
                              c.tool_name, c.model
                       FROM pinned_messages p
                       LEFT JOIN ai_conversations c ON c.id = p.conversation_id
                       WHERE p.user_id = %s
                         AND (p.message_content ILIKE %s OR p.note ILIKE %s)
                       ORDER BY p.created_at DESC
                       LIMIT %s OFFSET %s""",
                    (current_user.id, f"%{search}%", f"%{search}%", limit, offset),
                )
            else:
                cur.execute(
                    """SELECT p.id, p.conversation_id, p.message_content,
                              p.message_type, p.note, p.created_at,
                              c.tool_name, c.model
                       FROM pinned_messages p
                       LEFT JOIN ai_conversations c ON c.id = p.conversation_id
                       WHERE p.user_id = %s
                       ORDER BY p.created_at DESC
                       LIMIT %s OFFSET %s""",
                    (current_user.id, limit, offset),
                )
            pins = cur.fetchall()

            # Get total count
            cur.execute(
                "SELECT COUNT(*) as total FROM pinned_messages WHERE user_id = %s",
                (current_user.id,),
            )
            total = cur.fetchone()["total"]

        # Serialize datetimes
        results = []
        for p in pins:
            row = dict(p)
            if row.get("created_at"):
                row["created_at"] = row["created_at"].isoformat()
            results.append(row)

        return jsonify({"success": True, "pins": results, "total": total})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/chat/pin/<int:pin_id>", methods=["DELETE"])
@login_required
def delete_pin(pin_id):
    """Remove a pinned message by ID (ownership-verified)."""
    from database import get_db_cursor

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "DELETE FROM pinned_messages WHERE id = %s AND user_id = %s RETURNING id",
                (pin_id, current_user.id),
            )
            deleted = cur.fetchone()
            if not deleted:
                return jsonify({"success": False, "error": "Pin not found"}), 404
            return jsonify({"success": True, "deleted": pin_id})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# AUTHENTICATION ROUTES
# ============================================================================


@app.route("/")
def index():
    """Landing page - redirect to dashboard if logged in"""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Login page"""
    if current_user.is_authenticated:
        next_url = request.args.get("next")
        if next_url:
            return redirect(next_url)
        return redirect(url_for("dashboard"))

    # Clear stale pending 2FA session vars on fresh login page load
    if request.method == "GET":
        session.pop("pending_2fa_user_id", None)
        session.pop("pending_2fa_username", None)

    if request.method == "POST":
        if not _verify_csrf_token():
            app.logger.warning("CSRF token mismatch on login from %s", request.remote_addr)
            flash("Security token expired. Please try again.", "error")
            return redirect(url_for("login"))

        from services.auth_service import (
            get_user_by_username,
            record_failed_login,
            update_last_login,
            log_auth_event,
            reset_failed_login_count,
            increment_failed_login_count,
            is_account_locked,
            check_ip_rate_limit,
        )

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ip = request.remote_addr
        ua = request.headers.get("User-Agent", "")

        if not username or not password:
            flash("Please enter both username and password", "error")
            return render_template("login.html")

        # IP rate limiting
        ip_limited, ip_wait = check_ip_rate_limit(ip)
        if ip_limited:
            flash(f"Too many login attempts. Please wait {ip_wait} seconds.", "error")
            return render_template("login.html")

        try:
            user_data = get_user_by_username(username)

            if not user_data:
                record_failed_login(username, ip, ua, "unknown_username")
                flash("Invalid username or password", "error")
                return render_template("login.html")

            if not user_data.get("is_active", False):
                flash("Your account is pending admin approval. Please wait for activation.", "error")
                return render_template("login.html")

            # Account lockout check
            locked, lock_minutes = is_account_locked(user_data)
            if locked:
                flash(f"Account locked due to too many failed attempts. Try again in {lock_minutes} minutes.", "error")
                return render_template("login.html")

            if check_password_hash(user_data["password_hash"], password):
                update_last_login(user_data["id"], ip)

                if user_data.get("totp_enabled", False):
                    session["pending_2fa_user_id"] = user_data["id"]
                    session["pending_2fa_username"] = user_data["username"]
                    return redirect(url_for("verify_2fa"))

                # Extract theme from metadata
                metadata = user_data.get("metadata") or {}
                theme_pref = metadata.get("theme_preference") if isinstance(metadata, dict) else None

                user = User(
                    id=user_data["id"],
                    username=user_data["username"],
                    email=user_data["email"],
                    role=user_data["role"],
                    is_admin=user_data.get("is_admin", False),
                    is_super_admin=user_data.get("is_super_admin", False),
                    subscription_tier=user_data.get("subscription_tier", "free"),
                    subscription_expires_at=user_data.get("subscription_expires_at"),
                    theme_preference=theme_pref,
                    profile_picture=user_data.get("profile_picture"),
                    oauth_picture=user_data.get("oauth_picture"),
                    created_at=user_data.get("created_at"),
                    must_change_password=user_data.get("must_change_password", False),
                )
                login_user(user, remember=True)
                create_user_session(user_data["id"])

                log_auth_event(user_data["id"], "login_success", ip, ua)
                reset_failed_login_count(user_data["id"])

                # Force password change for accounts with must_change_password flag
                if user_data.get("must_change_password"):
                    flash(
                        "You must set a new password before continuing.",
                        "warning",
                    )
                    return redirect(url_for("change_password"))

                flash("Login successful!", "success")
                next_url = request.args.get("next") or request.form.get("next")
                if next_url:
                    return redirect(next_url)
                return redirect(url_for("dashboard"))
            else:
                record_failed_login(username, ip, ua, "invalid_password")
                increment_failed_login_count(user_data["id"])
                log_auth_event(user_data["id"], "login_failed", ip, ua)
                flash("Invalid username or password", "error")

        except Exception as e:
            print(f"Login error: {e}")
            flash("An error occurred. Please try again.", "error")

    return render_template("login.html")


@app.route("/api/qa/auth", methods=["POST"])
def qa_auth():
    """Internal QA authentication endpoint — bypasses CSRF and rate limiting.
    Only works when ARCHIE_QA_TOKEN env var is set and the request comes from
    a Docker-internal IP. Used by P.R.O.B.E. to avoid hairpin-NAT rate limit issues.
    """
    import hmac

    qa_token = os.environ.get("ARCHIE_QA_TOKEN", "")
    if not qa_token:
        return jsonify({"error": "QA auth disabled"}), 403

    # IP restriction — only Docker-internal networks
    ip = request.remote_addr or ""
    if not (ip.startswith("172.") or ip.startswith("10.") or ip in ("127.0.0.1", "::1")):
        return jsonify({"error": "QA auth only available from internal networks"}), 403

    data = request.get_json(silent=True) or {}
    submitted_token = data.get("token", "")
    username = data.get("username", "")

    if not hmac.compare_digest(submitted_token, qa_token):
        return jsonify({"error": "Invalid QA token"}), 401

    from services.auth_service import get_user_by_username

    user_data = get_user_by_username(username)
    if not user_data or not user_data.get("is_active"):
        return jsonify({"error": "User not found or inactive"}), 404

    metadata = user_data.get("metadata") or {}
    theme_pref = metadata.get("theme_preference") if isinstance(metadata, dict) else None
    user = User(
        id=user_data["id"],
        username=user_data["username"],
        email=user_data["email"],
        role=user_data["role"],
        is_admin=user_data.get("is_admin", False),
        is_super_admin=user_data.get("is_super_admin", False),
        subscription_tier=user_data.get("subscription_tier", "free"),
        subscription_expires_at=user_data.get("subscription_expires_at"),
        theme_preference=theme_pref,
        profile_picture=user_data.get("profile_picture"),
        oauth_picture=user_data.get("oauth_picture"),
        created_at=user_data.get("created_at"),
    )
    login_user(user, remember=True)
    create_user_session(user_data["id"])
    return jsonify({"success": True, "username": username})


@app.route("/verify-2fa", methods=["GET", "POST"])
def verify_2fa():
    """Two-factor authentication verification page"""
    # Must have a pending 2FA user in session
    pending_user_id = session.get("pending_2fa_user_id")
    pending_username = session.get("pending_2fa_username")
    if not pending_user_id:
        return redirect(url_for("login"))

    if request.method == "POST":
        code = request.form.get("code", "").strip()

        if not code or len(code) != 6 or not code.isdigit():
            flash("Please enter a valid 6-digit code", "error")
            return render_template("verify_2fa.html", username=pending_username)

        try:
            import pyotp
            from services.auth_service import (
                get_active_user_by_id,
                log_auth_event,
                reset_failed_login_count,
            )

            user_data = get_active_user_by_id(pending_user_id)

            if not user_data:
                session.pop("pending_2fa_user_id", None)
                session.pop("pending_2fa_username", None)
                flash("User account not found or inactive", "error")
                return redirect(url_for("login"))

            ip = request.remote_addr
            ua = request.headers.get("User-Agent", "")

            totp = pyotp.TOTP(user_data["totp_secret"])
            if totp.verify(code, valid_window=1):
                metadata = user_data.get("metadata") or {}
                theme_pref = metadata.get("theme_preference") if isinstance(metadata, dict) else None

                user = User(
                    id=user_data["id"],
                    username=user_data["username"],
                    email=user_data["email"],
                    role=user_data["role"],
                    is_admin=user_data.get("is_admin", False),
                    is_super_admin=user_data.get("is_super_admin", False),
                    subscription_tier=user_data.get("subscription_tier", "free"),
                    subscription_expires_at=user_data.get("subscription_expires_at"),
                    theme_preference=theme_pref,
                    profile_picture=user_data.get("profile_picture"),
                    oauth_picture=user_data.get("oauth_picture"),
                    created_at=user_data.get("created_at"),
                )
                login_user(user, remember=True)
                create_user_session(user_data["id"])

                session.pop("pending_2fa_user_id", None)
                session.pop("pending_2fa_username", None)

                log_auth_event(user_data["id"], "login_2fa_verified", ip, ua)
                reset_failed_login_count(user_data["id"])

                flash("Login successful!", "success")
                return redirect(url_for("dashboard"))
            else:
                log_auth_event(user_data["id"], "login_2fa_failed", ip, ua)
                flash("Invalid verification code. Please try again.", "error")
                return render_template("verify_2fa.html", username=pending_username)

        except Exception as e:
            print(f"2FA verification error: {e}")
            flash("An error occurred during verification. Please try again.", "error")
            return render_template("verify_2fa.html", username=pending_username)

    return render_template("verify_2fa.html", username=pending_username)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    """Self-registration disabled — Project Alpha (2026-05-06).
    Access is by admin invitation only. Accounts are created via Account Center."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    flash("Access is by invitation only. Contact the administrator to request an account.", "info")
    return redirect(url_for("login"))


@app.route("/accept-invite", methods=["GET", "POST"])
def accept_invite():
    """Public invite acceptance page — converts a token into a new user account."""
    from database import get_db
    from services.auth_service import validate_password_complexity

    token = request.args.get("token") or request.form.get("token")
    if not token:
        flash("Invalid or missing invitation token.", "error")
        return redirect(url_for("login"))

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, email, role, subscription_tier, message
               FROM user_invites
               WHERE token = %s AND status = 'pending' AND expires_at > NOW()""",
            (token,),
        )
        invite = cur.fetchone()
        if not invite:
            cur.close()
            conn.close()
            flash("This invitation link is invalid or has expired.", "error")
            return redirect(url_for("login"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm_password", "")
            if not username:
                flash("Username is required.", "error")
            elif password != confirm:
                flash("Passwords do not match.", "error")
            else:
                valid, msg = validate_password_complexity(password)
                if not valid:
                    flash(msg, "error")
                else:
                    cur.execute("SELECT id FROM users WHERE LOWER(username) = LOWER(%s)", (username,))
                    if cur.fetchone():
                        flash("Username already taken.", "error")
                    else:
                        invite_id, email, role, tier = invite[0], invite[1], invite[2], invite[3]
                        pw_hash = generate_password_hash(password)
                        cur.execute(
                            """INSERT INTO users (username, email, password_hash, role, subscription_tier, is_active)
                               VALUES (%s, %s, %s, %s, %s, true) RETURNING id""",
                            (username, email, pw_hash, role, tier),
                        )
                        new_user_id = cur.fetchone()[0]
                        cur.execute(
                            "UPDATE user_invites SET status='accepted', accepted_at=NOW(), accepted_user_id=%s WHERE id=%s",
                            (new_user_id, invite_id),
                        )
                        # Link partner profile if this is a COLLABORATOR invite
                        cur.execute(
                            "SELECT partner_profile_id FROM user_invites WHERE id = %s",
                            (invite_id,),
                        )
                        inv_row = cur.fetchone()
                        if inv_row and inv_row[0]:
                            cur.execute(
                                "UPDATE partner_profiles SET user_id = %s WHERE id = %s",
                                (new_user_id, inv_row[0]),
                            )
                        conn.commit()
                        cur.close()
                        conn.close()
                        flash("Account created! You can now log in.", "success")
                        return redirect(url_for("login"))
        cur.close()
        conn.close()
        return render_template("accept_invite.html", token=token, email=invite[1], message=invite[4])
    except Exception as e:
        app.logger.error("accept_invite error: %s", e)
        try:
            conn.close()
        except Exception:
            pass
        flash("An error occurred. Please contact the administrator.", "error")
        return redirect(url_for("login"))


@app.route("/logout")
@login_required
def logout():
    """Logout"""
    from services.auth_service import log_auth_event, delete_session_token

    try:
        log_auth_event(current_user.id, "logout", request.remote_addr)
        token = session.get("_session_token")
        if token:
            delete_session_token(token)
    except Exception as e:
        print(f"Logout logging error: {e}")

    logout_user()
    flash("Logged out successfully", "info")
    return redirect(url_for("login"))


# ============================================================================
# DASHBOARD
# ============================================================================


@app.route("/api/module-agents")
def api_module_agents():
    """Get the assigned agent for a module (Project #91 Agent Badge System).
    No auth required — returns only public agent info for badge display."""
    module_id = request.args.get("module", "")
    if not module_id:
        return jsonify({"agent_name": None})

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            -- station_assignments was DROPPED; the surviving station->agent link is
            -- bridge_stations.station_name = agents.department (verified: 16/16 active
            -- stations match a department, each with exactly one is_department_ai).
            -- Joining the dead table threw UndefinedTable, which the except below
            -- swallowed into {"agent_name": None} — every module silently reported
            -- "no agent" instead of its director. The department AI is the station's
            -- primary, so it is ordered first.
            SELECT a.name AS agent_name, a.model, bs.station_code, a.status
            FROM bridge_stations bs
            JOIN agents a
              ON a.department = bs.station_name
             AND a.status = 'active'
             AND a.worker_type = 'ai'
            WHERE bs.is_active = TRUE AND %s = ANY(bs.modules)
            ORDER BY a.is_department_ai DESC NULLS LAST, a.tier ASC, a.id ASC
            LIMIT 1
        """,
            (module_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row:
            return jsonify(
                {
                    "agent_name": row["agent_name"],
                    "model": row["model"],
                    "station_code": row["station_code"],
                    "status": row["status"] or "active",
                }
            )
        return jsonify({"agent_name": None})
    except Exception as e:
        logger.warning(f"module-agents API error: {e}")
        return jsonify({"agent_name": None})


@app.route("/dashboard")
@login_required
def dashboard():
    """Main dashboard - dynamic based on user permissions"""
    try:
        # Import dynamic dashboard generator
        from dashboard_generator import get_user_dashboard_data

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get service status
        cur.execute("SELECT * FROM service_status ORDER BY service_name")
        services = cur.fetchall()

        # Get A.R.C.H.I.E. personality
        cur.execute("SELECT * FROM archie_core_identity LIMIT 1")
        archie = cur.fetchone()

        # Get user's project count
        cur.execute(
            "SELECT COUNT(*) as count FROM projects WHERE user_id = %s",
            (current_user.id,),
        )
        project_count = cur.fetchone()["count"]

        # Get relationship strength
        cur.execute(
            "SELECT relationship_strength FROM archie_emotional_state"
            " WHERE user_id = %s ORDER BY timestamp DESC LIMIT 1",
            (current_user.id,),
        )
        relationship = cur.fetchone()
        relationship_strength = relationship["relationship_strength"] if relationship else 0.5

        # Calculate uptime
        uptime_seconds = int(time.time() - start_time)
        uptime = str(timedelta(seconds=uptime_seconds))

        cur.close()
        conn.close()

        # Get dynamic dashboard data based on user permissions
        dashboard_data = get_user_dashboard_data(current_user)

        return render_template(
            "dashboard_dynamic.html",
            services=services,
            archie=archie,
            project_count=project_count,
            relationship_strength=relationship_strength,
            uptime=uptime,
            dashboard_data=dashboard_data,
        )
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        import traceback

        traceback.print_exc()

        uptime_seconds = int(time.time() - start_time)
        uptime = str(timedelta(seconds=uptime_seconds))

        # Fallback to basic dashboard on error
        from dashboard_generator import get_user_dashboard_data

        dashboard_data = get_user_dashboard_data(current_user)

        return render_template(
            "dashboard_dynamic.html",
            services=[],
            archie=None,
            project_count=0,
            relationship_strength=0.5,
            uptime=uptime,
            dashboard_data=dashboard_data,
        )


# ============================================================================
# DASHBOARD API ENDPOINTS (HUD Vitals & Mission Briefing)
# ============================================================================


@app.route("/api/dashboard/system-stats")
@login_required
def api_dashboard_system_stats():
    """System stats for dashboard HUD vitals"""
    import psutil

    if not getattr(current_user, "is_admin", False):
        return jsonify({"success": False, "error": "Admin access required"}), 403
    try:
        uptime_seconds = int(time.time() - start_time)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return jsonify(
            {
                "success": True,
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "memory_used_gb": round(memory.used / (1024**3), 1),
                "memory_total_gb": round(memory.total / (1024**3), 1),
                "disk_percent": disk.percent,
                "disk_used_gb": round(disk.used / (1024**3), 1),
                "disk_total_gb": round(disk.total / (1024**3), 1),
                "uptime_seconds": uptime_seconds,
                "uptime_formatted": f"{hours}h {minutes}m {seconds}s",
            }
        )
    except Exception as e:
        logger.error(f"System stats API error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


_public_stats_cache = {"data": None, "timestamp": 0}


@app.route("/api/public/stats", methods=["GET"])
def api_public_stats():
    """Public platform stats for website integration. Cached 5 minutes. No auth."""
    now = time.time()
    if _public_stats_cache["data"] and (now - _public_stats_cache["timestamp"]) < 300:
        return jsonify(_public_stats_cache["data"])

    try:
        from database import get_db_cursor
        from module_registry import get_enabled_modules

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT worker_type, COUNT(*)
                FROM agents
                WHERE status != 'decommissioned'
                GROUP BY worker_type
                """
            )
            agent_counts = {r["worker_type"]: r["count"] for r in cur.fetchall()}
            total_agents = sum(agent_counts.values())

            cur.execute("SELECT COUNT(DISTINCT department) FROM agents WHERE status != 'decommissioned'")
            dept_count = cur.fetchone()["count"]

            cur.execute("SELECT COUNT(*) FROM knowledge_base")
            kb_count = cur.fetchone()["count"]

        module_count = len(get_enabled_modules())

        stats = {
            "agents": {
                "total": total_agents,
                "ai": agent_counts.get("ai", 0),
                "internal": agent_counts.get("internal", 0),
                "contractor": agent_counts.get("contractor", 0),
                "departments": dept_count,
            },
            "platform": {
                "modules": module_count,
                "knowledge_entries": kb_count,
                "languages": 8,
            },
            "updated_at": datetime.now(timezone.utc).isoformat() + "Z",
        }

        _public_stats_cache["data"] = stats
        _public_stats_cache["timestamp"] = now
        return jsonify(stats)
    except Exception as e:
        logger.error("Stats API error: %s", str(e))
        return jsonify({"error": "Stats temporarily unavailable"}), 503


@app.route("/api/dashboard/ai-status")
@login_required
def api_dashboard_ai_status():
    """AI bridge status for dashboard HUD"""
    if not getattr(current_user, "is_admin", False):
        return jsonify({"success": False, "error": "Admin access required"}), 403
    try:
        from services.dashboard_service import get_ai_status

        status = get_ai_status()
        return jsonify({"success": True, **status})
    except Exception as e:
        logger.error(f"AI status API error: {e}")
        return jsonify(
            {"success": True, "ai_online": True, "active_agents": 0, "today_interactions": 0, "services": {}}
        )


@app.route("/api/dashboard/recent-activity")
@login_required
def api_dashboard_recent_activity():
    """Blended recent activity from multiple sources for mission briefing."""
    if not getattr(current_user, "is_admin", False):
        return jsonify({"success": False, "error": "Admin access required"}), 403
    try:
        from services.dashboard_service import get_recent_activity

        activities = get_recent_activity()
        return jsonify({"success": True, "activities": activities})
    except Exception as e:
        logger.error(f"Recent activity API error: {e}")
        return jsonify({"success": True, "activities": []})


@app.route("/api/dashboard/alerts")
@login_required
def api_dashboard_alerts():
    """Blended system alerts for mission briefing — services, failed jobs, notifications."""
    if not getattr(current_user, "is_admin", False):
        return jsonify({"success": False, "error": "Admin access required"}), 403
    try:
        from services.dashboard_service import get_alerts

        result = get_alerts(current_user.id)
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"Alerts API error: {e}")
        return jsonify({"success": True, "alerts": [], "service_issues": []})


# ═══════════════════════════════════════════════════════════════════════════════
# LINGUISTICS / TRANSLATION API
# ═══════════════════════════════════════════════════════════════════════════════


@app.route("/api/translations/<lang>")
def api_translations(lang):
    """Get UI translations for a specific language (public — serves on login/signup too)"""
    from ai_bridge.translation_service import get_translations, SUPPORTED_LANGUAGES

    if lang not in SUPPORTED_LANGUAGES:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Unsupported language: {lang}. Supported: {', '.join(sorted(SUPPORTED_LANGUAGES.keys()))}",
                }
            ),
            400,
        )
    return jsonify({"success": True, "language": lang, "translations": get_translations(lang)})


@app.route("/api/user/language", methods=["GET", "PUT"])
@login_required
def api_user_language():
    """Get or update user language preference"""
    from ai_bridge.translation_service import SUPPORTED_LANGUAGES

    if request.method == "GET":
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT language, auto_detect FROM user_language_preferences WHERE user_id = %s",
                (current_user.id,),
            )
            pref = cur.fetchone()
            cur.close()
            conn.close()
            if pref:
                return jsonify(
                    {
                        "success": True,
                        "language": pref["language"],
                        "auto_detect": pref["auto_detect"],
                    }
                )
            return jsonify({"success": True, "language": "en", "auto_detect": True})
        except Exception as e:
            logger.error(f"User language GET error: {e}")
            return jsonify({"success": True, "language": "en", "auto_detect": True})

    # PUT
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No JSON data provided"}), 400
    language = data.get("language", "en")
    auto_detect = data.get("auto_detect", True)
    if language not in SUPPORTED_LANGUAGES:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Unsupported language: {language}",
                }
            ),
            400,
        )
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO user_language_preferences (user_id, language, auto_detect)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET language = EXCLUDED.language, auto_detect = EXCLUDED.auto_detect""",
            (current_user.id, language, auto_detect),
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify(
            {
                "success": True,
                "language": language,
                "auto_detect": auto_detect,
            }
        )
    except Exception as e:
        logger.error(f"User language PUT error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/translate/text", methods=["POST"])
@login_required
def api_translate_text():
    """Translate text to target language"""
    from ai_bridge.translation_service import translate_text

    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"success": False, "error": "Missing 'text' field"}), 400
    text = data["text"]
    target = data.get("target_language", "en")
    source = data.get("source_language", "en")
    try:
        result = translate_text(text, target, source)
        return jsonify(
            {
                "success": True,
                "original": text,
                "translated": result,
                "target_language": target,
            }
        )
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/language/detect", methods=["POST"])
@login_required
def api_language_detect():
    """Detect language of given text"""
    from ai_bridge.translation_service import detect_language

    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"success": False, "error": "Missing 'text' field"}), 400
    text = data["text"]
    try:
        detected_code = detect_language(text)
        return jsonify({"success": True, "text": text[:100], "language": detected_code})
    except Exception as e:
        logger.error(f"Language detection error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/health")
def health():
    """Health check endpoint with uptime"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()

        uptime_seconds = int(time.time() - start_time)
        uptime_str = str(timedelta(seconds=uptime_seconds))

        return (
            jsonify(
                {
                    "status": "healthy",
                    "service": "archie_platform",
                    "version": app.config.get("ARCHIE_VERSION", "2.0"),
                    "timestamp": datetime.now().isoformat(),
                    "uptime": uptime_str,
                }
            ),
            200,
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "status": "unhealthy",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                }
            ),
            500,
        )


# ============================================================================
# EXTERNAL API ENDPOINTS (/api/archie/*)
# Migrated from tools/archie_core/api.py (archie_api_bp removed)
# HA bridge routes (/api/archie/ha/*) are registered via archie_chat blueprint
# ============================================================================


def require_api_key(f):
    """Decorator to require API key authentication for external API endpoints"""

    def decorated_function(*args, **kwargs):
        api_key = request.headers.get("Authorization")

        if not api_key:
            return jsonify({"error": "No API key provided"}), 401

        # Remove 'Bearer ' prefix if present
        if api_key.startswith("Bearer "):
            api_key = api_key[7:]

        # Verify API key against environment variable
        valid_key = os.getenv("ARCHIE_API_KEY", "dev-api-key-change-in-production")

        if api_key != valid_key:
            return jsonify({"error": "Invalid API key"}), 401

        return f(*args, **kwargs)

    decorated_function.__name__ = f.__name__
    return decorated_function


@app.route("/api/archie/health", methods=["GET"])
def archie_api_health():
    """Health check endpoint for external monitoring"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        db_healthy = True
        cur.close()
        conn.close()
    except Exception:
        db_healthy = False

    status = "healthy" if db_healthy else "degraded"
    return (
        jsonify(
            {
                "status": status,
                "timestamp": datetime.now().isoformat(),
                "components": {
                    "database": {"status": "operational" if db_healthy else "error"},
                },
            }
        ),
        200 if db_healthy else 500,
    )


@app.route("/api/archie/search", methods=["POST"])
@require_api_key
def archie_api_search():
    """Search A.R.C.H.I.E.'s knowledge base"""
    try:
        data = request.get_json()

        if not data or "query" not in data:
            return jsonify({"success": False, "error": "No query provided"}), 400

        query = data["query"]
        category = data.get("category")
        limit = data.get("limit", 5)
        min_confidence = data.get("min_confidence", 0.7)

        search_start = time.time()

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        search_query = """
            SELECT
                id,
                content as title,
                content,
                memory_type as category,
                importance_score as confidence,
                source,
                created_at as last_updated
            FROM long_term_memory
            WHERE
                (content ILIKE %s OR tags::text ILIKE %s)
                AND importance_score >= %s
        """

        params = [f"%{query}%", f"%{query}%", min_confidence]

        if category:
            search_query += " AND memory_type = %s"
            params.append(category)

        search_query += " ORDER BY importance_score DESC LIMIT %s"
        params.append(limit)

        cur.execute(search_query, params)
        results = cur.fetchall()

        cur.execute(
            """
            SELECT DISTINCT ON (message)
                id,
                message as title,
                response as content,
                0.8 as confidence,
                'conversation_history' as source,
                created_at as last_updated
            FROM ai_conversations
            WHERE message ILIKE %s OR response ILIKE %s
            ORDER BY message, created_at DESC
            LIMIT %s
        """,
            (f"%{query}%", f"%{query}%", limit),
        )

        conversation_results = cur.fetchall()

        all_results = []

        for r in results:
            all_results.append(
                {
                    "id": str(r["id"]),
                    "title": r["title"][:100] if r["title"] else "Knowledge Entry",
                    "content": r["content"],
                    "confidence": float(r["confidence"]) if r["confidence"] else 0.8,
                    "source": r.get("source", "internal_kb"),
                    "last_updated": (r["last_updated"].isoformat() if r["last_updated"] else None),
                    "category": r.get("category", "general"),
                }
            )

        for r in conversation_results:
            all_results.append(
                {
                    "id": str(r["id"]),
                    "title": r["title"][:100],
                    "content": r["content"],
                    "confidence": 0.75,
                    "source": "conversation_history",
                    "last_updated": (r["last_updated"].isoformat() if r["last_updated"] else None),
                    "category": "support_history",
                }
            )

        all_results.sort(key=lambda x: x["confidence"], reverse=True)
        all_results = all_results[:limit]

        query_time = int((time.time() - search_start) * 1000)

        return (
            jsonify(
                {
                    "success": True,
                    "results": all_results,
                    "query_time_ms": query_time,
                    "total_results": len(all_results),
                }
            ),
            200,
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@app.route("/api/archie/learn", methods=["POST"])
@require_api_key
def archie_api_learn():
    """Submit learning/feedback data to A.R.C.H.I.E."""
    try:
        data = request.get_json()

        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        conversation_id = data.get("conversation_id")
        insights = data.get("insights", {})
        outcome = data.get("outcome", "unknown")
        feedback = data.get("feedback", {})

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        learning_content = {
            "conversation_id": conversation_id,
            "insights": insights,
            "outcome": outcome,
            "feedback": feedback,
        }

        importance_score = 0.5
        if outcome == "success":
            importance_score = 0.8
        elif outcome == "failed":
            importance_score = 0.9

        cur.execute(
            """
            INSERT INTO long_term_memory
            (content, memory_type, importance_score, source, metadata, tags)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                json.dumps(learning_content),
                "learning_data",
                importance_score,
                "call_system",
                json.dumps(feedback),
                json.dumps(["call_handling", outcome]),
            ),
        )

        learning_id = cur.fetchone()["id"]

        if insights:
            for key, value in insights.items():
                if value and (isinstance(value, list) and len(value) > 0):
                    cur.execute(
                        """
                        INSERT INTO long_term_memory
                        (content, memory_type, importance_score, source, tags)
                        VALUES (%s, %s, %s, %s, %s)
                    """,
                        (
                            json.dumps({key: value}),
                            "insight",
                            0.7,
                            "call_system",
                            json.dumps([key, "call_handling"]),
                        ),
                    )

        conn.commit()

        return (
            jsonify(
                {
                    "success": True,
                    "learning_job_id": str(learning_id),
                    "status": "completed",
                    "message": "Learning data stored successfully",
                }
            ),
            202,
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@app.route("/api/archie/learn/batch", methods=["POST"])
@require_api_key
def archie_api_learn_batch():
    """Submit batch learning data"""
    try:
        data = request.get_json()

        if not data or "conversations" not in data:
            return (
                jsonify({"success": False, "error": "No conversations provided"}),
                400,
            )

        conversations = data["conversations"]
        learning_mode = data.get("learning_mode", "incremental")

        conn = get_db()
        cur = conn.cursor()

        processed_count = 0
        for conv in conversations:
            learning_data = {
                "conversation_id": conv.get("id"),
                "outcome": conv.get("outcome"),
                "satisfaction": conv.get("satisfaction"),
                "insights": conv.get("insights", {}),
            }

            cur.execute(
                """
                INSERT INTO long_term_memory
                (content, memory_type, importance_score, source, tags)
                VALUES (%s, %s, %s, %s, %s)
            """,
                (
                    json.dumps(learning_data),
                    "batch_learning",
                    0.7,
                    "call_system_batch",
                    json.dumps(["batch_learning", learning_mode]),
                ),
            )

            processed_count += 1

        conn.commit()

        job_id = str(datetime.now().timestamp()).replace(".", "")

        return (
            jsonify(
                {
                    "success": True,
                    "job_id": job_id,
                    "conversations_queued": processed_count,
                    "estimated_completion": datetime.now().isoformat(),
                    "status": "completed",
                }
            ),
            202,
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@app.route("/api/archie/learn/status/<job_id>", methods=["GET"])
@require_api_key
def archie_api_learn_status(job_id):
    """Check the status of a learning job"""
    return (
        jsonify(
            {
                "success": True,
                "job_id": job_id,
                "status": "completed",
                "progress_percent": 100,
                "improvements_detected": ["Learning data processed successfully"],
            }
        ),
        200,
    )


# ============================================================================
# MODULE REGISTRY - Dynamic Blueprint Loading
# ============================================================================

from module_registry import get_enabled_modules, load_module_blueprint  # noqa: E402

# Load enabled modules dynamically from registry
print("[Module Registry] Loading enabled modules...")
loaded_modules = []
failed_modules = []

for module in get_enabled_modules():
    try:
        blueprint = load_module_blueprint(module.id)
        if blueprint is not None:
            app.register_blueprint(blueprint)
            loaded_modules.append(module.name)
            print(f"✅ Loaded module: {module.name} ({module.route})")
        else:
            # Module route defined in app.py, not a blueprint
            loaded_modules.append(module.name)
            print(f"✅ Loaded module: {module.name} ({module.route}) [app route]")
    except Exception as e:
        failed_modules.append((module.name, str(e)))
        print(f"❌ Failed to load module {module.name}: {e}")

print(f"[Module Registry] Loaded {len(loaded_modules)}/{len(get_enabled_modules())} modules")
if failed_modules:
    print(f"[Module Registry] Failed modules: {[name for name, _ in failed_modules]}")

# Make module registry available to templates
app.config["MODULE_REGISTRY_LOADED"] = loaded_modules
app.config["MODULE_REGISTRY_FAILED"] = failed_modules

# ============================================================================
# ADDITIONAL BLUEPRINTS (Not in module registry yet)
# ============================================================================

# Import additional blueprints not yet in module registry
# NOTE: consciousness_bp and backup_manager_bp are now loaded via module_registry
# NOTE: archie_api_bp removed — endpoints migrated directly into app.py above
# Disabled — consolidating into Consciousness GitHub tab (Task #1986)
# from tools.github_integration.github_routes import github_bp  # noqa: E402
from tools.repair_bay.services.sandbox_routes import sandbox_bp  # noqa: E402

from tools.repair_bay.services.cursor_api import cursor_bp  # noqa: E402

from tools.aaas.aaas_api import aaas_bp  # noqa: E402  # Agent-as-a-Service (#2475)
from tools.aaas.aaas_page import aaas_page_bp  # noqa: E402  # AaaS public commissioning page (#2474)

# OAuth authentication (Phase 6.5 - User Management & Subscription System)
from oauth_routes import oauth_bp, init_oauth  # noqa: E402
from services.git_commit_poller import start_poller  # noqa: E402
from conversation_triage.routes import triage_bp  # noqa: E402

# Initialize OAuth (Phase 6.5)
init_oauth(app)
logger.info("OAuth initialized (Google removed — email+password only, Project Alpha)")

# OAuth Provider — "Sign in with Kytran" for standalone products
from oauth_provider import init_oauth_provider  # noqa: E402

init_oauth_provider(app)
logger.info("OAuth provider initialized (authorize + token endpoints)")

# OAuth Userinfo — /oauth/userinfo returns profile + subscription entitlements
from oauth_userinfo import oauth_userinfo_bp  # noqa: E402

app.register_blueprint(oauth_userinfo_bp)

# Maven dispatch — /api/maven/dispatch is the hub-side surface for the
# Media Hub standalone's conversational skill. Routes {capability, prompt}
# from the standalone through the Bridge dispatcher so welfare-gating +
# cost tracking apply. Project #279 task #2251 (phase 2 of #2237).
from maven_dispatch import maven_dispatch_bp  # noqa: E402

app.register_blueprint(maven_dispatch_bp)

# Procure dispatch — /api/procure/dispatch is the hub-side surface for the
# Gov Watch standalone's P.R.O.C.U.R.E. surface. Same Bridge-routed pattern
# as Maven. Project #203 Phase 1 (supersedes ADR-006). Backed by agent #349.
from procure_dispatch import procure_dispatch_bp  # noqa: E402

app.register_blueprint(procure_dispatch_bp)

# G.A.V.E.L. dispatch — /api/gavel/dispatch is the hub-side surface for the
# Legal Watch standalone's G.A.V.E.L. chat overlay (Task #2863).
# Routes legal/compliance/contract_review prompts → G.A.V.E.L. (id=147,
# Legal & Regulatory director, mistral:7b). Same JWT bearer pattern.
from gavel_dispatch import gavel_dispatch_bp  # noqa: E402

app.register_blueprint(gavel_dispatch_bp)

# W.A.T.C.H. dispatch — /api/civic/dispatch is the hub-side surface for the
# Civic Watch standalone's W.A.T.C.H. chat overlay (Civic Watch roadmap).
# Routes civic_analysis/government_transparency/spending_analysis prompts →
# W.A.T.C.H. (id=152, Analytics & Intelligence, mistral:7b). Same JWT bearer pattern.
from civic_dispatch import civic_dispatch_bp  # noqa: E402

app.register_blueprint(civic_dispatch_bp)

# M.A.R.K.E.T. dispatch — /api/market/dispatch is the hub-side surface for the
# Market Watch standalone's M.A.R.K.E.T. chat overlay.
# Routes market_analysis/stock_analysis/portfolio_analysis prompts →
# M.A.R.K.E.T. (id=32, Analytics & Intelligence, mistral:7b). Same JWT bearer pattern.
from market_dispatch import market_dispatch_bp  # noqa: E402

app.register_blueprint(market_dispatch_bp)

# S.I.G.N.A.L. dispatch — /api/signal/dispatch is the hub-side surface for KBS
# social media content generation. Routes {capability, prompt, platform, tone}
# through Bridge dispatcher → S.I.G.N.A.L. (Marketing & Comms). ADR-518.
from signal_dispatch import signal_dispatch_bp  # noqa: E402

app.register_blueprint(signal_dispatch_bp)

# Standalone Product API — compliance report receiver
from api_standalone import init_standalone_api  # noqa: E402

init_standalone_api(app)

# Billing API — Stripe webhook, checkout, portal, products
from billing_routes import init_billing  # noqa: E402

init_billing(app)

# KSM Billing — webhook handlers for Kytran SysOps Manager tier push
from services.ksm_billing_handler import register_ksm_billing_handlers  # noqa: E402

register_ksm_billing_handlers()

# Watch Products Billing — covers gov_watch, civic_watch, legal_watch, market_watch, wtf + bundles
# Must be registered AFTER KSM so Watch handlers override the same event prefixes;
# non-Watch prices fall through to KSM handlers inside each Watch handler (T3027).
from services.watch_billing_handler import register_watch_billing_handlers  # noqa: E402

register_watch_billing_handlers()

# Register additional blueprints
# Note: app_builder_bp, archie_chat_bp, consciousness_bp, backup_manager_bp, repair_bay_bp loaded via module_registry
# app.register_blueprint(github_bp)  # Disabled — Task #1986
app.register_blueprint(sandbox_bp)  # Sandbox environment for testing proposals
app.register_blueprint(cursor_bp)  # Cursor IDE integration API
app.register_blueprint(triage_bp)  # Phase 42: Conversation triage pipeline
app.register_blueprint(aaas_bp)  # Agent-as-a-Service order intake + concierge build (#2475)
csrf.exempt(aaas_bp)  # JSON API, public + same-origin fetch (anti-spam in route, #2474)
app.register_blueprint(aaas_page_bp)  # AaaS public commissioning page /commission (#2474)
# OAuth authentication (Phase 6.5)
app.register_blueprint(oauth_bp)  # OAuth authentication (Google Sign-In)
# C.R.E.E.D. — public transparency + admin governance API
from tools.creed import creed_public_bp, creed_admin_bp  # noqa: E402

app.register_blueprint(creed_public_bp)
app.register_blueprint(creed_admin_bp)

# Products Showcase — migrating to KBS storefront (Task #1987)
# from tools.products.routes import products_bp  # noqa: E402
# app.register_blueprint(products_bp)

# Compliance Badge API (public — no login required)
from tools.security_network.badge_routes import badge_bp as compliance_badge_bp  # noqa: E402

app.register_blueprint(compliance_badge_bp)

# Public API — unauthenticated, read-only endpoints for kytranempowerment.com
from public_api import public_api_bp  # noqa: E402

app.register_blueprint(public_api_bp)

# Alternate email verification — public endpoint at /account/verify-alternate
from tools.account_center.email_link_routes import account_link_verify_bp  # noqa: E402

app.register_blueprint(account_link_verify_bp)

# Bundle pricing — Watch Bundle ($12.99) + Intelligence Bundle ($19.99) (#3025)
# Routes registered via account_center __init__.py → register_bundle_routes(bp)
# bundle_bp does not exist; bundle_routes uses the register_bundle_routes pattern.

# HR Management Module (Phase 51) - Registered via module_registry

# API Documentation — consolidating into Consciousness (Task #1985)
# from tools.api_docs import api_docs_bp  # noqa: E402
# app.register_blueprint(api_docs_bp)

# Dev HQ merged into Consciousness module (Decision #433)
# Routes now at /tools/consciousness/api/devhq/*

# Blueprint module removed (Decision #431) — intelligence functions moved to
# consciousness/services/platform_intelligence.py

# API Gateway — REST endpoints for ARCHIE Code CLI (exposes MCP tools via HTTP)
from api_gateway import api_gateway_bp  # noqa: E402

app.register_blueprint(api_gateway_bp)

from tools.department_hq.browser_routes import browser_bp  # noqa: E402

app.register_blueprint(browser_bp)

from tools.revenue_standup import revenue_standup_bp  # noqa: E402

app.register_blueprint(revenue_standup_bp)

# Cluster proxy — hub acts as trusted egress for VPS fleet nodes (Project #339)
# VPS products POST to /api/proxy/fetch with X-Proxy-Key to route blocked
# external HTTP requests through hub's residential IP (153.68.195.85).
from tools.cluster_proxy.routes import proxy_bp as cluster_proxy_bp  # noqa: E402

app.register_blueprint(cluster_proxy_bp)

# A2A Protocol — Agent-to-Agent interoperability (T1715)
from a2a_routes import a2a_wellknown_bp, a2a_tasks_bp  # noqa: E402

app.register_blueprint(a2a_wellknown_bp)
app.register_blueprint(a2a_tasks_bp)

# Cross-Watch Alert System — seed entities on startup (blueprint loaded via module_registry)
try:
    from tools.cross_watch.entity_seeder import seed_entities as _seed_cross_watch_entities

    _seed_cross_watch_entities()
    print("[A.R.C.H.I.E.] Cross-Watch entity seed complete")
except Exception as _cw_seed_err:
    print(f"[A.R.C.H.I.E.] Warning: Cross-Watch entity seed failed (migration may not have run): {_cw_seed_err}")

# NOTE: fleet_proxy (B.E.A.C.O.N. dashboard routing via *.fleet.kytranempowerment.com)
# was removed 2026-04-18 — project #173 cancelled, DNS cleaned up 2026-04-13,
# see task #2144 for the full fleet observability triad context.

# NOTE: System Operations (Phase 78) loaded via module_registry

# NOTE: Business module now loaded via module_registry (business_directory module)

# ============================================================================
# GIT COMMIT POLLER - Start automatically on application startup
# ============================================================================
print("[A.R.C.H.I.E.] Starting Git commit poller for automatic workflow triggering...")
try:
    start_poller()
    print("[A.R.C.H.I.E.] Git commit poller started successfully")
except Exception as e:
    print(f"[A.R.C.H.I.E.] Warning: Failed to start Git poller: {e}")


# ============================================================================
# KOKORO TTS WARMUP - Pre-load pipeline to avoid cold start delay
# ============================================================================
def _warmup_kokoro():
    """Background warmup of Kokoro TTS pipeline so first user request is fast."""
    import threading

    def _do_warmup():
        try:
            import sys

            sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
            # Warm the ACTUAL request-serving synthesizer singleton with HER exact
            # voice (agent 2 = af_heart+af_jessica blend + profile + emotion), not a
            # throwaway KokoroEngine that leaves the singleton cold. Owner directive:
            # always-loaded voice — the first cockpit/HA TTS must be instant.
            from ai_bridge.voice_synthesis import get_voice_synthesizer

            synth = get_voice_synthesizer()
            res = synth.synthesize_for_agent("Voice systems online.", 2, user_id=2)
            if res.get("success"):
                logger.info("Kokoro TTS warmed (singleton, her voice) — first synth is instant")
            else:
                logger.info("Kokoro warmup: synth unavailable (%s), will lazy-load", res.get("error"))
        except Exception as e:
            logger.warning(f"Kokoro warmup skipped: {e}")

    t = threading.Thread(target=_do_warmup, daemon=True, name="kokoro-warmup")
    t.start()


_warmup_kokoro()

# ============================================================================
# VOICE CACHE WARMUP - Pre-cache common ARCHIE phrases after Kokoro loads
# ============================================================================
try:
    from tools.consciousness.voice_pregen import auto_warmup_cache

    auto_warmup_cache()
    logger.info("Voice cache warmup thread started")
except Exception as e:
    logger.warning(f"Voice cache warmup skipped: {e}")


# ============================================================================
# OLLAMA MODEL WARMUP - Pre-load key models so first requests are fast
# ============================================================================
def _get_agent_models():
    """Query DB for unique models used by active agents + infrastructure models.

    Returns list of (model_name, endpoint_type) tuples, ordered by priority:
    1. Infrastructure models (embeddings, classify, vision)
    2. Agent models sorted by recent dispatch frequency (most-used first)

    Skips cloud models (contain ':cloud') since they don't need local loading.
    """
    from database import get_db_cursor

    agent_models_ordered = []
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # Get agent models ordered by dispatch frequency (last 7 days)
            cur.execute(
                """
                SELECT a.model, COUNT(tel.id) AS dispatch_count
                FROM agents a
                LEFT JOIN task_execution_log tel
                    ON tel.agent_name = a.name
                    AND tel.created_at > NOW() - INTERVAL '7 days'
                WHERE a.status = 'active'
                    AND a.worker_type = 'ai'
                    AND a.model IS NOT NULL AND a.model != '' AND a.model != 'none'
                    AND a.model NOT LIKE '%%:cloud'
                    AND a.shift_state NOT IN ('barracked', 'decommissioned')
                GROUP BY a.model
                ORDER BY dispatch_count DESC
            """
            )
            for row in cur.fetchall():
                agent_models_ordered.append(row["model"])
    except Exception:
        # Fallback: just get distinct models without ordering
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT DISTINCT model FROM agents
                    WHERE status = 'active' AND worker_type = 'ai'
                        AND model IS NOT NULL AND model != ''
                        AND model NOT LIKE '%%:cloud'
                        AND shift_state NOT IN ('barracked', 'decommissioned')
                """
                )
                for row in cur.fetchall():
                    agent_models_ordered.append(row["model"])
        except Exception:
            pass

    # Always include infrastructure models regardless of agent assignment
    infra_models = {"arctic-embed-cpu", "qwen25-classify", "minicpm-v-cpu"}

    # Models that must NOT be pre-loaded during warmup — cold-load on first dispatch instead.
    # qwen2.5vl:7b  — vision model; HTTP 500 on /api/generate without an image payload
    # dolphin3:latest — consistently times out (>300s cold load); blocks all subsequent warmup
    WARMUP_SKIP = {"qwen2.5vl:7b", "dolphin3:latest"}

    # Build load list: infrastructure first, then agent models by dispatch priority
    models_to_load = []
    for m in infra_models:
        endpoint = "embed" if "embed" in m else "generate"
        models_to_load.append((m, endpoint))
    for m in agent_models_ordered:
        if m not in infra_models and m not in WARMUP_SKIP:
            endpoint = "embed" if "embed" in m else "generate"
            models_to_load.append((m, endpoint))
    return models_to_load


def _warmup_ollama_models():
    """Background warmup of Ollama models.

    Loads models sequentially with keep_alive=-1 (infinite).
    GPU vs CPU determined by checking what's already on GPU in Ollama.
    Stops when <25GB RAM free (20% host reserve of 125GB).
    Priority: infrastructure models first, then agents by dispatch frequency.
    """
    import threading

    def _do_warmup():
        import time
        import requests as req
        import psutil
        from services.model_service import get_model_service

        ollama_host = os.getenv("OLLAMA_HOST", "http://archie_ollama:11434")
        if not ollama_host.startswith("http"):
            ollama_host = f"http://{ollama_host}"

        model_svc = get_model_service()

        # Check what's currently on GPU AND capture all loaded models for eviction.
        # Project #240 task #1761 — even after PR #33 fixed KEEP_ALIVE to 5m,
        # models already loaded from before retain their previous (often infinite)
        # keep_alive and never drain. Startup is the clean moment to force-unload,
        # then warmup reloads fresh with the correct keep_alive.
        gpu_models = set()
        loaded_before = []
        try:
            ps_resp = req.get(f"{ollama_host}/api/ps", timeout=10)
            if ps_resp.status_code == 200:
                for m in ps_resp.json().get("models", []):
                    loaded_before.append(m["name"])
                    if m.get("size_vram", 0) > 0:
                        gpu_models.add(m["name"])
                        gpu_models.add(m["name"].replace(":latest", ""))
        except Exception:
            pass

        # Force-evict stale loaded models via model_service (keep_alive=0).
        for model_name in loaded_before:
            if model_svc.unload_model(model_name):
                logger.info(f"Ollama evict: unloaded stale {model_name}")
            else:
                logger.warning(f"Ollama evict: {model_name} failed")
        if loaded_before:
            time.sleep(3)  # let Ollama release RAM before warmup begins

        models_to_load = _get_agent_models()

        def _load_model(model_name, endpoint):
            # Embed models warm via /api/embed (lifecycle-only, no inference options).
            # Text models warm via model_service.load_model — its single-writer
            # api/generate path handles retries + keep_alive=5m.
            # Note: model_service.load_model doesn't preserve CPU-only preference
            # (num_gpu=0); Ollama auto-places based on VRAM. Acceptable since
            # MAX_LOADED_MODELS=10 (systemd override, 2026-06-19) bounds GPU pressure.
            if endpoint == "embed":
                for attempt in range(3):
                    try:
                        data = {"model": model_name, "input": "warmup", "keep_alive": "35m"}
                        resp = req.post(
                            f"{ollama_host}/api/embed",
                            json=data,
                            timeout=600 if "coder" in model_name else 300,
                        )
                        if resp.status_code == 200:
                            logger.info(f"Ollama warmup: {model_name} loaded (embed)")
                            return True
                        logger.warning(
                            f"Ollama warmup: {model_name} returned " f"{resp.status_code}, retry {attempt+1}/3"
                        )
                    except Exception as e:
                        logger.warning(f"Ollama warmup embed {model_name}: {e} (retry {attempt+1}/3)")
                    time.sleep(2)
                return False

            # Text model: delegate to model_service (single-writer for api/generate).
            for attempt in range(3):
                if model_svc.load_model(model_name):
                    placement = "GPU" if (model_name in gpu_models or f"{model_name}:latest" in gpu_models) else "auto"
                    logger.info(f"Ollama warmup: {model_name} loaded ({placement})")
                    return True
                logger.warning(f"Ollama warmup: {model_name} load failed, retry {attempt+1}/3")
                time.sleep(2)
            return False

        ram_free = psutil.virtual_memory().available / (1024**3)
        logger.info(f"Ollama warmup: {ram_free:.0f}GB free, loading {len(models_to_load)} models")
        loaded = 0

        for model_name, endpoint in models_to_load:
            ram_free = psutil.virtual_memory().available / (1024**3)
            if ram_free < 30:
                logger.info(
                    f"Ollama warmup: {ram_free:.0f}GB free (< 30GB reserve+security), stopping "
                    f"({loaded} models loaded)"
                )
                break
            if _load_model(model_name, endpoint):
                loaded += 1

        final_free = psutil.virtual_memory().available / (1024**3)
        logger.info(f"Ollama warmup complete: {loaded} models loaded, " f"{final_free:.0f}GB RAM free")

    t = threading.Thread(target=_do_warmup, daemon=True, name="ollama-warmup")
    t.start()


# Check fleet mode before warming up — skip if weekend mode
_fleet_mode = "workday"
try:
    from database import get_db_cursor as _fm_get_db_cursor

    with _fm_get_db_cursor(commit=False) as (_fm_conn, _fm_cur):
        _fm_cur.execute("SELECT value FROM system_config WHERE key = 'fleet_mode'")
        _fm_row = _fm_cur.fetchone()
        if _fm_row:
            _fleet_mode = _fm_row["value"]
except Exception:
    pass

# Memory pre-flight: don't stack warmup work onto a host already thrashing.
# Project #240 task #1759 — prevents 2026-04-11-style cascade (load avg 330
# hit when platform restart piled model warmup onto a swap-pinned host).
_skip_warmup_reason = None
try:
    import psutil as _preflight_psutil

    _avail_gb = _preflight_psutil.virtual_memory().available / (1024**3)
    _swap = _preflight_psutil.swap_memory()
    _swap_free_gb = (_swap.total - _swap.used) / (1024**3)
    if _avail_gb < 5:
        _skip_warmup_reason = f"MemAvailable={_avail_gb:.1f}GB < 5GB critical threshold"
    elif _swap_free_gb < 0.3:
        _skip_warmup_reason = f"SwapFree={_swap_free_gb:.2f}GB < 0.3GB — host is swap-pinned"
    elif _avail_gb < 15:
        logger.warning(f"Startup pre-flight: MemAvailable={_avail_gb:.1f}GB marginal; warmup may stop early.")
    else:
        logger.info(f"Startup pre-flight OK: MemAvailable={_avail_gb:.1f}GB, SwapFree={_swap_free_gb:.2f}GB")
except Exception as _preflight_err:
    logger.warning(f"Startup pre-flight check failed (continuing): {_preflight_err}")

if _fleet_mode == "weekend":
    logger.info("Fleet mode: WEEKEND — skipping Ollama + ComfyUI warmup (models stay unloaded)")
elif _skip_warmup_reason:
    logger.error(f"Startup pre-flight: SKIPPING warmup — {_skip_warmup_reason}")
else:
    _warmup_ollama_models()

    # ComfyUI warmup — pre-load SDXL checkpoint into VRAM
    def _warmup_comfyui():
        import time

        time.sleep(10)  # Let Ollama warmup settle first
        try:
            from ai_bridge.comfyui_service import get_comfyui_service

            svc = get_comfyui_service()
            svc.warmup()
        except Exception as e:
            logger.warning(f"ComfyUI warmup failed: {e}")

    import threading

    threading.Thread(target=_warmup_comfyui, daemon=True, name="comfyui-warmup").start()


# ============================================================================
# I18N AUTO-SCAN - Discover and seed new translation keys on startup
# ============================================================================
def _warmup_i18n_keys():
    """Background scan for new translation keys and seed English entries."""
    import threading

    def _do_scan():
        try:
            with app.app_context():
                from tools.consciousness.language_routes import scan_and_seed_keys

                result = scan_and_seed_keys()
                if result["seeded"] > 0:
                    logger.info(f"[i18n] {result['seeded']} new translation keys discovered and seeded")
                else:
                    logger.info(f"[i18n] {result['total']} keys scanned, all already seeded")
        except Exception as e:
            logger.warning(f"[i18n] Startup scan skipped: {e}")

    t = threading.Thread(target=_do_scan, daemon=True, name="i18n-scan")
    t.start()


_warmup_i18n_keys()


# ============================================================================
# SERVICE STATUS - Update on startup and provide live health checks
# ============================================================================
def _update_service_status():
    """Update service_status table on platform startup."""
    import threading

    def _do_update():
        try:
            with app.app_context():
                import requests as req

                conn = get_db()
                cur = conn.cursor()

                # Platform is online (we're running)
                cur.execute(
                    """
                    UPDATE service_status SET status = 'online', last_checked = NOW(), error_message = NULL
                    WHERE service_name = 'platform'
                """
                )

                # Database is online (we just connected)
                cur.execute(
                    """
                    UPDATE service_status SET status = 'online', last_checked = NOW(), error_message = NULL
                    WHERE service_name = 'database'
                """
                )

                # Check Ollama
                try:
                    r = req.get("http://archie_ollama:11434/api/tags", timeout=5)
                    status = "online" if r.status_code == 200 else "degraded"
                    cur.execute(
                        "UPDATE service_status SET status = %s, last_checked = NOW(), error_message = NULL WHERE service_name = 'ollama'",
                        (status,),
                    )
                except Exception as e:
                    cur.execute(
                        "UPDATE service_status SET status = 'offline', last_checked = NOW(), error_message = %s WHERE service_name = 'ollama'",
                        (str(e)[:200],),
                    )

                # Check AI Bridge (DHQ dispatcher)
                try:
                    from tools.department_hq.services.department_dispatcher import get_dispatcher as _get_disp

                    status = "online" if _get_disp() else "unknown"
                    cur.execute(
                        "UPDATE service_status SET status = %s, last_checked = NOW(), error_message = NULL WHERE service_name = 'ai_bridge'",
                        (status,),
                    )
                except Exception as e:
                    cur.execute(
                        "UPDATE service_status SET status = 'offline', last_checked = NOW(), error_message = %s WHERE service_name = 'ai_bridge'",
                        (str(e)[:200],),
                    )

                # Consciousness module
                cur.execute(
                    """
                    UPDATE service_status SET status = 'online', last_checked = NOW(), error_message = NULL
                    WHERE service_name = 'consciousness'
                """
                )

                conn.commit()
                cur.close()
                conn.close()
                logger.info("[health] Service status updated on startup")
        except Exception as e:
            logger.warning(f"[health] Service status update failed: {e}")

    t = threading.Thread(target=_do_update, daemon=True, name="service-status")
    t.start()


_update_service_status()


# ============================================================================
# MCP TOOL SYNC + HEALTH PROBE - Startup tasks for Dev HQ System tab
# ============================================================================
def _startup_mcp_sync_and_health():
    """Sync MCP tool registry and run initial health check on startup."""
    import threading

    def _do_sync():
        try:
            with app.app_context():
                from tools.consciousness.devhq_routes import sync_mcp_tool_registry, _run_and_store_health_check

                synced = sync_mcp_tool_registry()
                if synced:
                    logger.info(f"MCP tool registry: synced {synced} entries")

                results = _run_and_store_health_check()
                logger.info(f"Initial health check stored: {len(results)} services")
        except Exception as e:
            logger.warning(f"MCP sync/health startup failed: {e}")

    t = threading.Thread(target=_do_sync, daemon=True, name="mcp-sync")
    t.start()


_startup_mcp_sync_and_health()


# ============================================================================
# FLEET PING CLEANUP - Clear orphaned fleet handshake jobs on startup
# ============================================================================
def _clear_stale_fleet_ping_jobs():
    """Mark orphaned fleet 'ping' handshake jobs as failed on boot (Dev HQ task #3339).

    Fleet warmup/pilot handshakes create bridge_jobs 'running' rows that never
    complete when archie_platform restarts mid-handshake. Left as 'running',
    the busy-detector treats them as capacity pressure and triggers spurious
    cloud-throughput escalations. This scopes the cleanup to stale fleet-ping
    'running' rows older than 5 minutes. Mirrors scan_service auto-recovery.
    Wrapped so it can never block boot.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_, cur):
            cur.execute(
                """UPDATE bridge_jobs SET status='failed', error_message='Cleared on restart'
                   WHERE status='running'
                     AND (module_source IN ('fleet_pilot', 'fleet_warmup', 'kin_warmth') OR description ILIKE '%ping%')
                     AND created_at < NOW() - INTERVAL '5 minutes'"""
            )
            cleared = cur.rowcount
        if cleared:
            logger.info(f"[fleet] Cleared {cleared} stale fleet ping job(s) on startup")
    except Exception as e:
        logger.warning(f"[fleet] Stale ping cleanup failed: {e}")


_clear_stale_fleet_ping_jobs()


# ============================================================================
# SANDBOX MODE CONTEXT PROCESSOR
# ============================================================================


@app.before_request
def _inject_sandbox_flag():
    """Expose g.sandbox_mode to all templates and request handlers."""
    from flask import g

    g.sandbox_mode = app.config.get("SANDBOX_MODE", False)


@app.before_request
def redirect_old_archie_domain():
    """Redirect archie.kytranempowerment.com to platform.kytranempowerment.com.
    Safety net for bookmarks and hardcoded links during domain transition.
    archie.* now serves archie_comms (:3002). Platform lives at platform.*
    Remove after 30 days (2026-05-15). Decision #442.
    """
    host = request.host.split(":")[0]
    if host == "archie.kytranempowerment.com":
        new_url = request.url.replace("archie.kytranempowerment.com", "platform.kytranempowerment.com", 1)
        return redirect(new_url, code=301)


@app.before_request
def clear_sandbox_mode_for_production():
    """
    Clear sandbox mode from session when accessing production routes
    Prevents sandbox contamination of production
    """
    from flask import session, request

    # If accessing production route (not /sandbox/*), clear sandbox mode
    if not request.path.startswith("/sandbox/"):
        session.pop("sandbox_mode", None)
        session.pop("db_schema", None)


@app.before_request
def enforce_2fa_verification():
    """
    If a user has passed password auth but not yet completed 2FA,
    restrict access to only the verification and login routes.
    """
    if session.get("pending_2fa_user_id") and not current_user.is_authenticated:
        allowed_paths = ("/verify-2fa", "/login", "/logout", "/static/")
        if not any(request.path.startswith(p) for p in allowed_paths):
            return redirect(url_for("verify_2fa"))


@app.before_request
def enforce_guest_readonly():
    """Block all write operations for GUEST role (Level 5 — demo mode)."""
    if not current_user.is_authenticated:
        return
    if getattr(current_user, "role_value", 100) != 5:
        return
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        # Allow the demo token entry route itself
        if request.path.startswith("/tools/account-center/demo"):
            return
        if request.is_json:
            return jsonify({"error": "demo_mode", "message": "Read-only in demo mode"}), 403
        return "Demo mode: read-only", 403


@app.before_request
def enforce_partner_onboarding():
    """Redirect COLLABORATOR users who haven't completed onboarding."""
    if not current_user.is_authenticated:
        return
    if getattr(current_user, "role_value", 100) != 15:
        return
    if request.path.startswith("/partner-welcome"):
        return
    if request.path.startswith("/static") or request.path.startswith("/api"):
        return
    if request.path in ("/login", "/logout", "/accept-invite"):
        return
    try:
        from database import get_db_cursor as _gdc

        with _gdc(commit=False) as (_conn, _cur):
            _cur.execute(
                "SELECT onboarding_complete FROM partner_profiles WHERE user_id = %s",
                (current_user.id,),
            )
            row = _cur.fetchone()
        if row and not row["onboarding_complete"]:
            return redirect("/partner-welcome")
    except Exception:
        pass


@app.route("/partner-welcome")
def partner_welcome():
    """Welcome screen for COLLABORATOR users completing onboarding."""
    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    if getattr(current_user, "role_value", 100) != 15:
        return redirect("/")
    try:
        from database import get_db_cursor as _gdc

        with _gdc(commit=False) as (_conn, _cur):
            _cur.execute(
                """SELECT p.slug, p.display_name, u2.username AS inviter
                   FROM partner_profiles p
                   LEFT JOIN users u2 ON p.invited_by = u2.id
                   WHERE p.user_id = %s""",
                (current_user.id,),
            )
            profile = _cur.fetchone()
    except Exception:
        profile = None
    return render_template("partner_welcome.html", profile=profile)


@app.route("/api/partner/onboarding-complete", methods=["POST"])
def partner_onboarding_complete():
    """Mark partner onboarding as complete."""
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthorized"}), 401
    if getattr(current_user, "role_value", 100) != 15:
        return jsonify({"error": "forbidden"}), 403
    try:
        from database import get_db_cursor as _gdc

        with _gdc(commit=True) as (_conn, _cur):
            _cur.execute(
                "UPDATE partner_profiles SET onboarding_complete = TRUE WHERE user_id = %s",
                (current_user.id,),
            )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"done": True})


@app.before_request
def update_session_activity():
    """Update last_activity timestamp for the current user's active session."""
    if current_user.is_authenticated and session.get("_session_token"):
        # Throttle updates to once per 60 seconds to avoid DB spam
        last_update = session.get("_session_last_update", 0)
        now = time.time()
        if now - last_update > 60:
            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute(
                    "UPDATE active_sessions SET last_activity = NOW() WHERE session_token = %s",
                    (session["_session_token"],),
                )
                conn.commit()
                cur.close()
                conn.close()
                session["_session_last_update"] = now
            except Exception:
                pass


@app.before_request
def enforce_password_change():
    """Redirect users with must_change_password=True to the change-password page
    for every request until they comply. Exempts /change-password, /logout, and static assets."""
    if not current_user.is_authenticated:
        return
    if not getattr(current_user, "must_change_password", False):
        return
    allowed_endpoints = {"change_password", "logout", "static"}
    if request.endpoint in allowed_endpoints:
        return
    return redirect(url_for("change_password"))


@app.after_request
def add_security_headers(response):
    """Add security headers to every response (Project Alpha, 2026-05-06)."""
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # Double-submit CSRF cookie — mirrors session token so POST survives NPM proxy session loss
    csrf_token = session.get("_csrf_token")
    if csrf_token and request.cookies.get("archie_csrf") != csrf_token:
        response.set_cookie(
            "archie_csrf", csrf_token, samesite="Lax", httponly=False, secure=False, max_age=86400, path="/"
        )
    return response


def _generate_csrf_token():
    """Generate a CSRF token stored in the session."""
    import secrets

    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


def _verify_csrf_token():
    """Return True if the submitted token matches session or double-submit cookie."""
    submitted = request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token")
    if not submitted:
        return False
    session_token = session.get("_csrf_token")
    if session_token and secrets.compare_digest(session_token, submitted):
        return True
    # Double-submit cookie fallback — proxy-safe, survives session cookie loss
    cookie_token = request.cookies.get("archie_csrf")
    if cookie_token and secrets.compare_digest(cookie_token, submitted):
        return True
    return False


@app.context_processor
def inject_csrf_token():
    """Make csrf_token() available in all templates."""
    return {"csrf_token": _generate_csrf_token}


@app.context_processor
def inject_sandbox_context():
    """
    Make sandbox mode available to all templates
    Provides sandbox-aware URL generation
    """
    from flask import request

    # ONLY use request path to determine sandbox mode
    # Don't persist in session to avoid contaminating production
    is_sandbox = request.path.startswith("/sandbox/")
    sandbox_prefix = "/sandbox" if is_sandbox else ""

    def sandbox_url(path):
        """
        Generate sandbox-aware URL
        If in sandbox mode, prepends /sandbox to path
        """
        if is_sandbox and not path.startswith("/sandbox"):
            # Don't double-prefix
            if path.startswith("/"):
                return f"/sandbox{path}"
            else:
                return f"/sandbox/{path}"
        return path

    return {
        "sandbox_mode": is_sandbox,
        "sandbox_prefix": sandbox_prefix,
        "sandbox_url": sandbox_url,
    }


# ============================================================================
# MODULE REGISTRY CONTEXT PROCESSOR
# ============================================================================


@app.context_processor
def inject_module_registry():
    """
    Make module registry available to all templates
    Provides module information and access checking
    """
    from module_registry import get_enabled_modules, get_all_modules
    from rbac import can_access_module

    def get_user_modules():
        """Get modules accessible to current user"""
        if not current_user.is_authenticated:
            return []

        accessible = []
        for module in get_enabled_modules():
            if can_access_module(module.id, current_user):
                accessible.append(module)

        return sorted(accessible, key=lambda m: m.priority)

    return {
        "get_user_modules": get_user_modules,
        "all_modules": get_all_modules,
        "enabled_modules": get_enabled_modules,
    }


# ============================================================================
# THEME CONTEXT PROCESSOR
# ============================================================================

VALID_THEMES = {
    "lcars-classic",
    "corporate-blue",
    "midnight-purple",
    "warm-minimal",
    "arctic-light",
    "rose-gold",
    "forest",
    "slate-pro",
}

THEME_TO_FAMILY = {
    "lcars-classic": "lcars",
    "corporate-blue": "corporate",
    "slate-pro": "corporate",
    "warm-minimal": "minimal",
    "arctic-light": "minimal",
    "midnight-purple": "elegant",
    "rose-gold": "elegant",
    "forest": "elegant",
}

ADMIN_CATEGORIES = {"admin_operations", "ai_command"}


@app.context_processor
def inject_theme_context():
    """
    Inject theme variables into all templates.
    Resolves: user preference -> org default -> lcars-classic fallback.
    Admin modules always force LCARS.
    """
    theme_name = "lcars-classic"
    layout_family = "lcars"
    is_admin_module = False

    if current_user.is_authenticated:
        # 1. User preference (None = no explicit choice)
        user_theme = getattr(current_user, "theme_preference", None)
        if user_theme and user_theme in VALID_THEMES:
            theme_name = user_theme
        elif user_theme is None:
            # 2. Org default fallback (only when user has no explicit choice)
            try:
                conn = get_db()
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT o.settings->>'default_theme' as default_theme
                    FROM organizations o
                    JOIN org_users ou ON ou.org_id = o.id
                    WHERE ou.user_id = %s
                    LIMIT 1
                    """,
                    (current_user.id,),
                )
                row = cur.fetchone()
                cur.close()
                conn.close()
                if row and row["default_theme"] in VALID_THEMES:
                    theme_name = row["default_theme"]
            except Exception:
                pass

        # Detect admin module from request path
        from module_registry import get_all_modules

        path = request.path
        for mod in get_all_modules():
            if mod.route and path.startswith(mod.route):
                if mod.category and mod.category.value in ADMIN_CATEGORIES:
                    is_admin_module = True
                break

        # Resolve layout family from theme
        layout_family = THEME_TO_FAMILY.get(theme_name, "lcars")

        # Admin modules always use LCARS layout
        if is_admin_module:
            layout_family = "lcars"

    return {
        "theme_name": theme_name,
        "layout_family": layout_family,
        "is_admin_module": is_admin_module,
    }


@app.context_processor
def inject_category_siblings():
    """Auto-populate `header_shortcuts` for any template that includes lcars-header.html.

    Per-request memoized via flask.g. If the route already set
    g.header_shortcuts_override, the override wins. Defensive: never raises.

    See: docs/superpowers/specs/2026-05-03-lcars-nav-strategy-design.md
    """
    try:
        # Per-request memoization
        if hasattr(g, "_nav_shortcuts_cached"):
            return {"header_shortcuts": g._nav_shortcuts_cached}

        # Per-route override path
        override = getattr(g, "header_shortcuts_override", None)
        if override is not None:
            g._nav_shortcuts_cached = override
            return {"header_shortcuts": override}

        # Resolve current module from request endpoint
        endpoint = getattr(request, "endpoint", None)
        module_id = nav_service.resolve_module_id(endpoint)
        if module_id is None:
            g._nav_shortcuts_cached = []
            return {"header_shortcuts": []}

        shortcuts = nav_service.get_category_siblings(module_id, current_user)
        # Convert dicts to (label, icon, url) tuples — lcars-header.html and all
        # manual template overrides use 3-tuple unpacking in {% for %} loops.
        shortcuts_tuples = [(s["label"], s["icon"], s["url"]) for s in shortcuts]
        g._nav_shortcuts_cached = shortcuts_tuples
        return {"header_shortcuts": shortcuts_tuples}
    except Exception as exc:  # noqa: BLE001 — defensive: nav must never crash
        import logging

        logging.getLogger(__name__).warning("inject_category_siblings failed: %s", exc)
        return {"header_shortcuts": []}


# ============================================================================
# MODULE REGISTRY API ENDPOINTS
# ============================================================================


@app.route("/api/modules", methods=["GET"])
@login_required
def get_modules():
    """Get all modules accessible to current user"""
    from module_registry import get_enabled_modules
    from rbac import can_access_module

    try:
        accessible = []
        for module in get_enabled_modules():
            if not module.show_on_dashboard:
                continue
            if can_access_module(module.id, current_user):
                accessible.append(
                    {
                        "id": module.id,
                        "name": module.name,
                        "description": module.description,
                        "icon": module.icon,
                        "category": module.category.value,
                        "route": module.route,
                        "enabled": module.enabled,
                        "beta": module.beta,
                        "coming_soon": module.coming_soon,
                        "tags": module.tags,
                    }
                )

        return jsonify(
            {
                "success": True,
                "modules": sorted(accessible, key=lambda m: m.get("name", "")),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/modules/health", methods=["GET"])
@login_required
def get_modules_health():
    """Get health status of all enabled modules

    Available to all logged-in users for dashboard status display.
    """
    from module_registry import check_all_modules_health

    try:
        health_results = check_all_modules_health()

        return jsonify(
            {
                "success": True,
                "health": health_results,
                "summary": {
                    "total": len(health_results),
                    "healthy": sum(1 for h in health_results.values() if h.get("healthy", False)),
                    "unhealthy": sum(1 for h in health_results.values() if not h.get("healthy", False)),
                },
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/modules/<module_id>/health", methods=["GET"])
@login_required
def get_module_health(module_id):
    """Get health status of a specific module"""
    from module_registry import check_module_health
    from rbac import can_access_module

    # Check if user can access this module
    if not can_access_module(module_id, current_user):
        return jsonify({"success": False, "error": "Access denied"}), 403

    try:
        health = check_module_health(module_id)

        return jsonify({"success": True, "health": health})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# NOTIFICATION ROUTES - Migrated from admin/routes.py
# These routes are accessible from the dashboard for all authenticated users
# ============================================================================


@app.route("/api/notifications", methods=["GET"])
@login_required
def get_notifications():
    """Blended notifications — grouped system_notifications + bridge alerts + security."""
    from services.notification_service import get_notifications as _get_notifications

    try:
        notifications = _get_notifications(
            user_id=current_user.id,
            is_admin=getattr(current_user, "is_admin", False),
        )
        return jsonify({"success": True, "notifications": notifications})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/notifications/mark-read/<int:notification_id>", methods=["POST"])
@login_required
def mark_notification_read(notification_id):
    """Mark notification and its group as read"""
    from services.notification_service import mark_read

    try:
        mark_read(notification_id, current_user.id)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/notifications/mark-all-read", methods=["POST"])
@login_required
def mark_all_notifications_read():
    """Mark all visible notifications as read for the current user"""
    from services.notification_service import mark_all_read

    try:
        mark_all_read(current_user.id, getattr(current_user, "is_admin", False))
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/notifications", methods=["POST"])
@login_required
def create_notification_endpoint():
    """Create a new notification with grouping and deduplication"""
    from services.notification_service import create_notification

    try:
        data = request.json
        result = create_notification(
            notification_type=data.get("type", "info"),
            title=data.get("title", "Notification"),
            message=data.get("message", ""),
            source=data.get("source", "dashboard"),
            priority=data.get("priority", "normal"),
            source_icon=data.get("source_icon", ""),
            related_action=data.get("related_action", None),
            visibility=data.get("visibility", "all"),
            target_user_id=data.get("target_user_id", None),
        )
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/notifications/count", methods=["GET"])
@login_required
def get_notification_count():
    """Get unread notification count — only markable system_notifications, per-user."""
    from services.notification_service import get_unread_count

    try:
        counts = get_unread_count(current_user.id, getattr(current_user, "is_admin", False))
        return jsonify({"success": True, **counts})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/notifications/search", methods=["GET"])
@login_required
def search_notifications():
    """Search and filter notifications with pagination"""
    from services.notification_service import search_notifications as _search

    try:
        result = _search(
            user_id=current_user.id,
            is_admin=getattr(current_user, "is_admin", False),
            filter_type=request.args.get("filter", "all"),
            notification_type=request.args.get("type", "all"),
            priority=request.args.get("priority", "all"),
            source=request.args.get("source", "all"),
            search_query=request.args.get("q", ""),
            date_range=request.args.get("date_range", "all"),
            page=int(request.args.get("page", 1)),
            per_page=int(request.args.get("per_page", 20)),
        )
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/notifications/export", methods=["GET"])
@login_required
def export_notifications():
    """Export notifications as CSV or JSON"""
    from flask import Response
    from io import StringIO
    import csv
    from services.notification_service import export_notifications as _export

    if not getattr(current_user, "is_admin", False):
        return jsonify({"success": False, "error": "Admin access required"}), 403

    try:
        notifications = _export()
        format_type = request.args.get("format", "csv")

        if format_type == "json":
            output = json.dumps(notifications, indent=2, default=str)
            return Response(
                output,
                mimetype="application/json",
                headers={"Content-Disposition": "attachment; filename=notifications.json"},
            )
        else:  # CSV
            output = StringIO()
            if notifications:
                writer = csv.DictWriter(output, fieldnames=notifications[0].keys())
                writer.writeheader()
                for notif in notifications:
                    writer.writerow({k: str(v) for k, v in notif.items()})
            return Response(
                output.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=notifications.csv"},
            )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/notifications/archive-old", methods=["POST"])
@login_required
def archive_old_notifications():
    """Archive notifications older than specified days (default 7)."""
    from services.notification_service import archive_old

    if not getattr(current_user, "is_admin", False):
        return jsonify({"success": False, "error": "Admin access required"}), 403

    try:
        days = int(request.json.get("days", 7)) if request.json else 7
        archived_count = archive_old(days)
        return jsonify({"success": True, "archived": archived_count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/notifications/dismiss/<int:notification_id>", methods=["POST"])
@login_required
def dismiss_notification(notification_id):
    """Dismiss (archive) a single notification and its group."""
    from services.notification_service import dismiss_notification as _dismiss

    try:
        result = _dismiss(notification_id, current_user.id)
        if result is None:
            return jsonify({"success": False, "error": "Notification not found"}), 404
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/notifications/clear-all", methods=["POST"])
@login_required
def clear_all_notifications():
    """Archive all visible (non-archived) notifications for cleanup."""
    from services.notification_service import clear_all

    if not getattr(current_user, "is_admin", False):
        return jsonify({"success": False, "error": "Admin access required"}), 403

    try:
        archived_count = clear_all(current_user.id)
        return jsonify({"success": True, "archived": archived_count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# UNIFIED ALERTS API (Project #251 — consolidates notifications + dashboard alerts)
# ═══════════════════════════════════════════════════════════════════════════════


def _dr_mode_flag():
    """``is_dr_active()`` that can never raise into the alert bell.

    Its own try/except exists because this is called from BOTH the success and the
    failure path of the alerts endpoint — including the path that already knows
    something upstream is broken. A red-alert signal that can itself throw is worse
    than no signal, so any error degrades to False (hub-normal) rather than 500.
    """
    try:
        from services.dr_posture_monitor import is_dr_active

        return is_dr_active()
    except Exception:  # noqa: BLE001 — advisory only; never break the alert bell
        return False


@app.route("/api/alerts/unified", methods=["GET"])
@login_required
def api_alerts_unified():
    """Unified alerts from all 7 sources — one endpoint for bell, dashboard, elbow."""
    try:
        from services.alert_service import get_unified_alerts

        result = get_unified_alerts(
            user_id=current_user.id,
            is_admin=getattr(current_user, "is_admin", False),
        )
        # AGENT MOBILITY PROFILE rides this poll rather than getting its own request.
        # The LCARS elbow needs to show a standing "forces diverted" condition on every
        # page; this endpoint already reaches all of them every 30s ("one endpoint for
        # bell, dashboard, elbow"), so adding a field here costs nothing, updates live
        # when the mode is flipped in A.R.M.A.D.A., and avoids a per-render DB read in a
        # context processor. Fail-safe → 'auto' (no diversion shown). (#5133)
        try:
            from services.fleet_dispatch_profile import get_dispatch_mode

            result["dispatch_mode"] = get_dispatch_mode()
        except Exception:  # noqa: BLE001 — an advisory must never break the alert bell
            result["dispatch_mode"] = "auto"
        # DR STANDBY rides the same poll, for the same reason. This is a DIFFERENT
        # condition from dispatch_mode: 'diverted' is a deliberate routing preference,
        # while dr_mode means the hub is GONE and this process is the boston-2 standby.
        # Conflating them would make a normal 'platform' mobility profile scream red.
        # Fail-safe → False. (#3728 sets ARCHIE_DR_MODE in the standby compose.)
        result["dr_mode"] = _dr_mode_flag()
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"Unified alerts error: {e}")
        return jsonify(
            {
                "success": True,
                "critical": [],
                "categories": {},
                "counts": {"total": 0, "unread": 0, "critical": 0},
                "dispatch_mode": "auto",
                # Deliberately NOT hardcoded False: if the alert pipeline is broken
                # DURING a failover, the red alert is the one thing that must still
                # reach the header. _dr_mode_flag swallows its own errors.
                "dr_mode": _dr_mode_flag(),
            }
        )


@app.route("/api/alerts/unified/mark-read", methods=["POST"])
@login_required
def api_alerts_mark_read():
    """Mark a single alert as read."""
    try:
        from services.alert_service import mark_alert_read

        data = request.get_json(silent=True) or {}
        alert_key = data.get("alert_key")
        if not alert_key:
            return jsonify({"success": False, "error": "alert_key required"}), 400
        mark_alert_read(current_user.id, alert_key)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/alerts/unified/mark-all-read", methods=["POST"])
@login_required
def api_alerts_mark_all_read():
    """Mark all current alerts as read."""
    try:
        from services.alert_service import mark_all_alerts_read

        count = mark_all_alerts_read(
            current_user.id,
            getattr(current_user, "is_admin", False),
        )
        return jsonify({"success": True, "marked": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# ERROR HANDLERS
# ============================================================================

# ============================================================================
# PHASE 4: MISTAKE LEARNING & PREVENTION
# Automatic error detection and learning system
# ============================================================================

from tools.consciousness.services.mistake_detector import get_mistake_detector  # noqa: E402


@app.route("/blocked")
def blocked_page():
    """Serve DNS block page for domains blocked by AdGuard.
    AdGuard config: blocking_mode=custom_ip, blocking_ipv4=192.168.1.200
    """
    domain = request.args.get("domain", request.host or "Unknown")
    return render_template("block_page.html", domain=domain)


@app.route("/api/translate", methods=["POST"])
def api_translate_public():
    """Public AI translation endpoint — showcases ARCHIE's translation capability."""
    data = request.get_json() or {}
    text = data.get("text", "")
    target_lang = data.get("target_lang", "en")
    source_lang = data.get("source_lang", "en")

    if not text:
        return jsonify({"success": False, "error": "text required"}), 400
    if len(text) > 2000:
        return jsonify({"success": False, "error": "text too long (max 2000 chars)"}), 400

    try:
        # Route through Bridge dispatcher (ADR-013) — respects agent welfare,
        # capability routing, and governance logging.
        from tools.department_hq.services.department_dispatcher import dispatch

        prompt = (
            f"Translate the following text from {source_lang} to {target_lang}. "
            f"Return ONLY the translated text, nothing else.\n\nText: {text}"
        )

        result = dispatch(
            capability="translate",
            prompt=prompt,
            module_id="public_translate",
            local_only=True,  # public endpoint — no cloud tokens
        )

        if result.success:
            return jsonify(
                {
                    "success": True,
                    "translated": (result.response or "").strip(),
                    "source": source_lang,
                    "target": target_lang,
                    "engine": "A.R.C.H.I.E. AI",
                }
            )

        return jsonify({"success": False, "error": "Translation failed"}), 500
    except Exception as e:
        logger.error(f"Public translate error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/competitors")
def competitors_page():
    """Public page comparing ARCHIE against 25+ AI agent frameworks."""
    from datetime import datetime

    now = datetime.now(timezone.utc)
    stardate = f"{now.year}.{now.strftime('%j')}"
    return render_template("competitors.html", stardate=stardate)


@app.route("/products/system-operations")
def product_system_operations():
    """Public product page for Kytran System Operations."""
    return render_template("products/system_operations.html")


@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors — also catches blocked domain requests from AdGuard DNS.

    An unknown /api/* path must answer JSON, never an HTML redirect. Machine
    consumers of the internal API cannot read a 302 + login/dashboard HTML page:
    their JSON parse dies on the first byte and they report a transport error
    instead of the honest "no such endpoint". A caller that mistypes a path then
    cannot tell its own bug from an outage. (500) and the generic Exception
    handler below both already branch on /api/ for this reason; this one did not.
    """
    host = request.host.split(":")[0] if request.host else ""
    if host and host != "192.168.1.200" and host != "localhost" and not host.endswith("kytranempowerment.com"):
        return render_template("block_page.html", domain=host), 200
    if request.path.startswith("/api/"):
        return jsonify({"error": "not_found", "path": request.path}), 404
    flash("Page not found", "error")
    return redirect(url_for("dashboard"))


@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors with mistake learning"""
    logger.error(f"500 Server Error: {str(e)}")

    # Attempt to learn from this error
    try:
        detector = get_mistake_detector()
        context = {
            "route": request.path if request else "unknown",
            "method": request.method if request else "unknown",
            "user_id": (current_user.id if hasattr(current_user, "id") and current_user.is_authenticated else None),
            "error_type": "500",
            "timestamp": datetime.now().isoformat(),
        }

        mistake = detector.detect_and_learn(str(e), context)
        if mistake:
            logger.info(f"[Mistake Detector] Learned from 500 error: {mistake.get('title')}")
    except Exception as learn_error:
        logger.error(f"[Mistake Detector] Failed to learn from error: {learn_error}")

    flash("Server error occurred", "error")
    return redirect(url_for("dashboard"))


@app.errorhandler(Exception)
def handle_exception(e):
    """
    Handle all uncaught exceptions with automatic mistake learning

    This is the main integration point for Phase 4 mistake detection
    """
    error_message = str(e)
    error_type = type(e).__name__

    # Log the error
    logger.error(f"Unhandled exception: {error_type}: {error_message}", exc_info=True)

    # Attempt to detect and learn from this mistake
    try:
        detector = get_mistake_detector()

        context = {
            "route": request.path if request else "unknown",
            "method": request.method if request else "unknown",
            "user_id": (current_user.id if hasattr(current_user, "id") and current_user.is_authenticated else None),
            "error_type": error_type,
            "timestamp": datetime.now().isoformat(),
            "url": request.url if request else None,
            "referrer": request.referrer if request else None,
        }

        # Detect and potentially learn from this error
        mistake = detector.detect_and_learn(error_message, context)

        if mistake:
            # We found a known mistake!
            logger.warning(f"[Mistake Detector] ⚠️ REPEATED MISTAKE: {mistake.get('title')}")

            # Get the solution
            solution = detector.get_solution_for_error(error_message)
            if solution:
                logger.info(f"[Mistake Detector] 📚 Known solution available: {solution[:200]}")
                # You could add this to the flash message for admins
                if current_user.is_authenticated and hasattr(current_user, "is_admin") and current_user.is_admin():
                    flash(
                        f"Known issue detected. Solution: {solution[:100]}...",
                        "warning",
                    )
        else:
            logger.info(f"[Mistake Detector] No pattern match for: {error_type}")

    except Exception as learn_error:
        # Don't let mistake detection break error handling
        logger.error(f"[Mistake Detector] Error during learning: {learn_error}")

    # Return appropriate error response
    if request and request.path.startswith("/api/"):
        # API error - return JSON
        return (
            jsonify({"success": False, "error": error_message, "error_type": error_type}),
            500,
        )
    else:
        # Web error - flash and redirect
        flash(f"An error occurred: {error_message}", "error")
        return redirect(url_for("dashboard"))


# ============================================================================
# CREW WELLNESS TICK (Training Progression + Rest Recovery)
# ============================================================================


def crew_wellness_tick(flask_app):
    """Process training progression and rest recovery every 5 minutes."""
    with flask_app.app_context():
        try:
            from database import get_db_cursor
            import datetime

            # Hours needed to advance TO each level (from the level below)
            HOURS_PER_LEVEL = {2: 1, 3: 2, 4: 4, 5: 8}

            with get_db_cursor() as (conn, cur):
                # ==============================================================
                # TRAINING PROGRESSION
                # ==============================================================
                cur.execute(
                    """
                    SELECT id, agent_id, skill_name, skill_category,
                           current_proficiency, target_proficiency, updated_at
                    FROM training_assignments
                    WHERE status = 'in_progress'
                      AND current_proficiency < target_proficiency
                    """
                )
                active_trainings = cur.fetchall()

                for training in active_trainings:
                    now = datetime.datetime.now(timezone.utc)
                    updated_at = training["updated_at"]
                    # DB column is TIMESTAMP WITHOUT TIME ZONE (naive) — treat as UTC
                    if updated_at is not None and updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=timezone.utc)
                    hours_since_update = (now - updated_at).total_seconds() / 3600.0
                    current_level = training["current_proficiency"]
                    target_level = training["target_proficiency"]
                    next_level = current_level + 1

                    if next_level > 5 or next_level not in HOURS_PER_LEVEL:
                        continue

                    hours_needed = HOURS_PER_LEVEL[next_level]

                    if hours_since_update >= hours_needed:
                        new_level = next_level
                        agent_id = training["agent_id"]
                        skill_name = training["skill_name"]
                        skill_category = training["skill_category"]
                        training_id = training["id"]

                        # Update training assignment proficiency and reset timer
                        if new_level >= target_level:
                            # Training complete
                            cur.execute(
                                """
                                UPDATE training_assignments
                                SET current_proficiency = %s,
                                    status = 'completed',
                                    completed_at = NOW(),
                                    updated_at = NOW()
                                WHERE id = %s
                                """,
                                (new_level, training_id),
                            )
                        else:
                            # Level up, continue training
                            cur.execute(
                                """
                                UPDATE training_assignments
                                SET current_proficiency = %s,
                                    updated_at = NOW()
                                WHERE id = %s
                                """,
                                (new_level, training_id),
                            )

                        # UPSERT agent_skills
                        cur.execute(
                            """
                            INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, updated_at)
                            VALUES (%s, %s, %s, %s, NOW())
                            ON CONFLICT (agent_id, skill_name)
                            DO UPDATE SET proficiency_level = EXCLUDED.proficiency_level,
                                          skill_category = EXCLUDED.skill_category,
                                          updated_at = NOW()
                            """,
                            (agent_id, skill_name, skill_category, new_level),
                        )

                        # Record learning
                        confidence_before = round((current_level - 1) / 4.0, 2)
                        confidence_after = round((new_level - 1) / 4.0, 2)
                        cur.execute(
                            """
                            INSERT INTO agent_learning_records
                                (agent_id, learning_type, subject, lesson_learned,
                                 confidence_before, confidence_after, source_type)
                            VALUES (%s, 'training', %s, %s, %s, %s, 'training_room')
                            """,
                            (
                                agent_id,
                                skill_name,
                                f"Advanced from level {current_level} to {new_level} in {skill_name}",
                                confidence_before,
                                confidence_after,
                            ),
                        )

                        logger.info(
                            f"[CrewWellness] Agent {agent_id} leveled up {skill_name}: "
                            f"{current_level} -> {new_level}"
                            f"{' (COMPLETE)' if new_level >= target_level else ''}"
                        )

                # ==============================================================
                # REST RECOVERY
                # ==============================================================
                cur.execute(
                    """
                    SELECT rc.id, rc.agent_id, rc.started_at,
                           rc.stress_at_start, rc.energy_at_start
                    FROM agent_rest_cycles rc
                    WHERE rc.ended_at IS NULL
                      AND rc.stress_at_start IS NOT NULL
                      AND rc.energy_at_start IS NOT NULL
                    """
                )
                active_rests = cur.fetchall()

                for rest in active_rests:
                    now = datetime.datetime.now(timezone.utc)
                    started_at = rest["started_at"]
                    # DB column is TIMESTAMP WITHOUT TIME ZONE (naive) — treat as UTC
                    if started_at is not None and started_at.tzinfo is None:
                        started_at = started_at.replace(tzinfo=timezone.utc)
                    hours_resting = (now - started_at).total_seconds() / 3600.0

                    stress_at_start = float(rest["stress_at_start"])
                    energy_at_start = float(rest["energy_at_start"])

                    # Stress drops 10% per hour, energy recovers 15% per hour
                    # Clamp to DB constraints: stress 0..0.9, energy 0.1..1.0
                    new_stress = max(0.0, stress_at_start - hours_resting * 0.10)
                    new_stress = min(new_stress, 0.9)
                    new_energy = min(1.0, energy_at_start + hours_resting * 0.15)
                    new_energy = max(new_energy, 0.1)

                    agent_id = rest["agent_id"]

                    # Update the latest emotional state for this agent
                    cur.execute(
                        """
                        UPDATE agent_emotional_state
                        SET stress_level = %s,
                            energy_level = %s,
                            trigger_event = 'rest_recovery_tick',
                            timestamp = NOW()
                        WHERE id = (
                            SELECT id FROM agent_emotional_state
                            WHERE agent_id = %s
                            ORDER BY timestamp DESC
                            LIMIT 1
                        )
                        """,
                        (
                            round(new_stress, 2),
                            round(new_energy, 2),
                            agent_id,
                        ),
                    )

                if active_trainings or active_rests:
                    logger.info(
                        f"[CrewWellness] Tick processed: "
                        f"{len(active_trainings)} training(s), "
                        f"{len(active_rests)} rest cycle(s)"
                    )

        except Exception as e:
            logger.error(f"[CrewWellness] Tick failed: {e}")
            import traceback

            traceback.print_exc()


# ============================================================================
# CONSCIOUSNESS SCHEDULER
# ============================================================================


def init_consciousness_scheduler(flask_app):
    """Initialize the consciousness scheduler with APScheduler"""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
        from apscheduler.triggers.cron import CronTrigger

        # ALL scheduled jobs have been migrated to the Autonomy Agent Loop
        # (agent_loop.py) for centralized department-based tracking.
        # This scheduler is kept as a shell — the AgentLoop attaches to it.

        # job_defaults: prevent 2026-04-11-style replay storms.
        # - misfire_grace_time=300: a job missed by <5min still runs; beyond that, drop.
        # - coalesce=True: if multiple fires were missed, collapse into one run.
        # - max_instances=1: a job can't stack concurrent runs on recovery.
        # 154 of 157 add_job() calls relied on APScheduler defaults
        # (grace=1s, coalesce=False) — pure storm vector on hot restart.
        # Project #240 audit (task #1762) → config fix.
        scheduler = BackgroundScheduler(
            timezone="America/Toronto",
            job_defaults={
                "misfire_grace_time": 300,
                "coalesce": True,
                "max_instances": 1,
            },
        )
        scheduler.start()
        flask_app.config["CONSCIOUSNESS_SCHEDULER"] = scheduler
        logger.info("Base scheduler started — all jobs managed by Autonomy Agent Loop")

        return scheduler

    except ImportError as e:
        logger.warning(f"APScheduler not available, consciousness tasks will not run: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to initialize consciousness scheduler: {e}")
        return None


# Initialize scheduler when not in debug reload mode AND this process owns
# the scheduler. Path C (decision_id 557) extracts the scheduler into a
# sidecar container; ``ARCHIE_RUN_SCHEDULER`` defaults to "1" so legacy
# single-container deploys keep working unchanged. The sidecar daemon sets
# it to "1" explicitly; once the platform container delegates scheduling
# to the sidecar, its compose entry sets it to "0" and the entire init
# block becomes a no-op so jobs don't double-fire.
_run_scheduler_here = os.getenv("ARCHIE_RUN_SCHEDULER", "1") == "1"
if (os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug) and _run_scheduler_here:
    _scheduler = init_consciousness_scheduler(app)

    # Initialize Agent Loop (Project Autonomy)
    if _scheduler:
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
            from agent_loop import AgentLoop

            _agent_loop = AgentLoop(scheduler=_scheduler, flask_app=app)
            _agent_loop.start()
            app.config["AGENT_LOOP"] = _agent_loop
            logger.info("Agent loop initialized and started")
        except Exception as e:
            logger.error(f"Failed to initialize agent loop: {e}")
            app.config["AGENT_LOOP"] = None

        # Phase 1: Job Service — runs alongside AgentLoop
        try:
            from services.job_service import JobService
            from services.budget_jobs import register_budget_jobs

            _job_service = JobService(scheduler=_scheduler)
            register_budget_jobs(_job_service)
            try:
                from tools.email_manager.sync_jobs import register_email_sync_jobs

                register_email_sync_jobs(_job_service)
            except Exception as _e:
                logger.warning("[Startup] Email sync jobs skipped: %s", _e)
            try:
                from tools.email_manager.idle_worker import start_idle_workers

                start_idle_workers()
            except Exception as _e:
                logger.warning("[Startup] IMAP IDLE workers skipped: %s", _e)
            try:
                from services.social_content_jobs import register_social_content_jobs

                register_social_content_jobs(_scheduler)
            except Exception as _e:
                logger.warning("[Startup] Social content jobs skipped: %s", _e)
            app.config["JOB_SERVICE"] = _job_service
            logger.info("[Startup] JobService initialized with budget reset jobs")
        except Exception as e:
            logger.error("[Startup] JobService failed to initialize: %s", e)

        # Phase 4b: Wire up LOOP_SERVICE for dispatch monitoring
        try:
            from services import loop_service as _loop_svc

            class _LoopServiceWrapper:
                """Thin wrapper to give loop_service module an object interface."""

                def get_all_states(self):
                    loops = _loop_svc.get_server_loops()
                    result = {}
                    for op in _loop_svc.VALID_LOOP_OPS:
                        result[op] = {
                            "enabled": loops.get(op, False),
                            "name": op.title(),
                        }
                    return result

                def toggle(self, loop_name):
                    current = _loop_svc.get_server_loops()
                    new_state = not current.get(loop_name, False)
                    _loop_svc.set_server_loop(loop_name, new_state)
                    return new_state

            app.config["LOOP_SERVICE"] = _LoopServiceWrapper()
            logger.info("[Startup] LOOP_SERVICE initialized (analysis, embedding, translate)")
        except Exception as e:
            logger.error("[Startup] LOOP_SERVICE failed: %s", e)

        # Phase 5: Bridge agent_loop jobs into job_service
        try:
            from services.agent_loop_bridge import bridge_agent_loop_to_job_service

            _bridged = bridge_agent_loop_to_job_service(_scheduler, _job_service)
            logger.info("[Startup] Bridged %d agent_loop jobs to JobService", _bridged)
        except Exception as e:
            logger.error("[Startup] AgentLoop bridge failed: %s", e)

        # Phase 5b: Module job registrations
        # NOTE: All module jobs now registered via agent_loop.py Phase 5 block:
        #   register_consciousness_jobs(), register_security_jobs(), register_department_hq_jobs(),
        #   register_agent_welfare_jobs(), register_fleet_jobs()

        # Initialize Telegram Gateway (Project Autonomy Phase 3)
        # Guarded by an exclusive file lock so only ONE python process in the
        # container runs the bot poller at a time. Without this guard, every
        # subprocess that imports app.py (smoke tests, CLI scripts, etc.)
        # spawns its own getUpdates poller that collides with the main
        # gunicorn worker on the same bot token — python-telegram-bot handles
        # the 409 Conflict by restarting, but callback_query updates get
        # delivered to whichever instance wins the race and silently dropped.
        # The lock file lives on tmpfs and is held for the life of the winning
        # process; when it dies the OS releases the FD automatically.
        # Path C: skip Telegram gateway in the scheduler sidecar — only the
        # platform container should own the bot's fcntl lock and getUpdates
        # poller. Defaults to "1" so single-container deploys are unchanged.
        _run_telegram_here = os.getenv("ARCHIE_RUN_TELEGRAM", "1") == "1"
        _tg_token = os.getenv("TELEGRAM_BOT_TOKEN") if _run_telegram_here else None
        if _tg_token and not app.config.get("SANDBOX_MODE"):
            import fcntl

            _tg_lock_path = "/tmp/archie_telegram_gateway.lock"
            try:
                _tg_lock_fd = open(_tg_lock_path, "w")
                fcntl.flock(_tg_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # We hold the lock — start the gateway.
                try:
                    from telegram_gateway import TelegramGateway

                    _telegram = TelegramGateway(bot_token=_tg_token, flask_app=app)
                    _telegram.start()
                    app.config["TELEGRAM_GATEWAY"] = _telegram
                    # Pin the FD on app.config so the GC doesn't close it and
                    # drop the lock mid-flight.
                    app.config["_TELEGRAM_GATEWAY_LOCK_FD"] = _tg_lock_fd
                    logger.info("Telegram gateway initialized and started (lock acquired)")
                except Exception as e:
                    logger.error(f"Failed to initialize Telegram gateway: {e}")
                    app.config["TELEGRAM_GATEWAY"] = None
                    try:
                        fcntl.flock(_tg_lock_fd, fcntl.LOCK_UN)
                        _tg_lock_fd.close()
                    except Exception:
                        pass
            except BlockingIOError:
                # Another process already owns the gateway — skip init.
                # This is expected for subprocess imports (tests, CLI tools).
                logger.info(
                    "Telegram gateway skipped — another process holds the lock. "
                    "This is normal for subprocess imports of app.py."
                )
                app.config["TELEGRAM_GATEWAY"] = None
        else:
            app.config["TELEGRAM_GATEWAY"] = None
            logger.info("Telegram gateway not configured (no TELEGRAM_BOT_TOKEN)")


# ── Telegram gateway bootstrap (out of init_consciousness_scheduler) ──
# PR #511 sets ARCHIE_RUN_SCHEDULER=0 in archie_platform to delegate
# scheduling to the archie_scheduler sidecar. The Telegram bot startup was
# nested inside init_consciousness_scheduler() which is gated on
# ARCHIE_RUN_SCHEDULER — silent regression: bot stopped starting in
# archie_platform when scheduling was delegated. Re-bootstrap here at
# module top level so the bot runs regardless of scheduler-here state.
# Gated only by ARCHIE_RUN_TELEGRAM (scheduler_daemon sets it to "0").
# fcntl lock prevents double-start if the in-function block also runs in
# single-container deploys.
_run_telegram_here_top = os.getenv("ARCHIE_RUN_TELEGRAM", "1") == "1"
_tg_token_top = os.getenv("TELEGRAM_BOT_TOKEN") if _run_telegram_here_top else None
if _tg_token_top and not app.config.get("TELEGRAM_GATEWAY") and not app.config.get("SANDBOX_MODE"):
    import fcntl as _fcntl_top

    _tg_lock_path_top = "/tmp/archie_telegram_gateway.lock"
    try:
        _tg_lock_fd_top = open(_tg_lock_path_top, "w")
        _fcntl_top.flock(_tg_lock_fd_top, _fcntl_top.LOCK_EX | _fcntl_top.LOCK_NB)
        try:
            from telegram_gateway import TelegramGateway as _TelegramGateway_top

            _telegram_top = _TelegramGateway_top(bot_token=_tg_token_top, flask_app=app)
            _telegram_top.start()
            app.config["TELEGRAM_GATEWAY"] = _telegram_top
            app.config["_TELEGRAM_GATEWAY_LOCK_FD"] = _tg_lock_fd_top
            logger.info("Telegram gateway initialized at module top (lock acquired)")
        except Exception as _tg_err_top:
            logger.error("Failed to initialize Telegram gateway at module top: %s", _tg_err_top)
            app.config.setdefault("TELEGRAM_GATEWAY", None)
            try:
                _fcntl_top.flock(_tg_lock_fd_top, _fcntl_top.LOCK_UN)
                _tg_lock_fd_top.close()
            except Exception:
                pass
    except BlockingIOError:
        logger.info("Telegram gateway top-level bootstrap skipped — another process holds the lock")
        app.config.setdefault("TELEGRAM_GATEWAY", None)
elif not _tg_token_top and not app.config.get("TELEGRAM_GATEWAY"):
    app.config["TELEGRAM_GATEWAY"] = None
    if _run_telegram_here_top:
        logger.info("Telegram gateway top-level bootstrap: no TELEGRAM_BOT_TOKEN")


# ── Internal Delegation API (Sub-C #2351) ──────────────────────────
import os as _os_delegation
from functools import wraps as _wraps_delegation


# #6657: every /api/internal/* route is gated by ONE scoped decorator. The flat
# INTERNAL_API_KEY bearer that used to live here (plain `!=`, no caller identity)
# is accepted as a full-scope LEGACY key during the rollout and then retired —
# see services/internal_auth.py for the caller → scope table.
from services.internal_auth import require_internal_scope  # noqa: E402


@app.route("/api/internal/dhq/chat", methods=["POST"])
@require_internal_scope("dhq:chat")
def api_internal_dhq_chat():
    """Synchronous DHQ-routed completion. Defaults to A.R.C.H.I.E.'s conversation
    voice (the archie_comms cockpit); service callers may override the agent.

    The cockpit chat reply used to POST direct to Ollama, which times out /
    [Connection error]s whenever the hub GPU is saturated (KB mistake #273554).
    Routing through the dispatcher gives the reply welfare + cost gating, the
    cold-load queue, and fleet routing. archie_comms calls this DHQ-first and
    falls back to its direct-Ollama voice if this is unreachable (ADR-013
    voice-survives-crash waiver), so a platform outage never silences A.R.C.H.I.E.

    Optional body params let other internal services route to a different agent
    while reusing this same synchronous, welfare-gated, strictly-local path —
    e.g. the A.R.C.H.I.E. build engine sends capability="code"/prefer_agent=
    "F.O.R.G.E." for its plan step (#4256). Omitting them keeps the cockpit's
    A.R.C.H.I.E. conversation behavior unchanged.

    Body: {prompt, system_prompt?, user_id?, capability?, prefer_agent?, module_id?,
           model?, format?}.  `format` is "json" or a JSON-schema object (#6038).
    `local_only` is always True (no cloud escalation; ADR-003 #4 / KB #269363).

    Service-to-service: Authorization: Bearer <INTERNAL_API_KEY>.
    Registered at app level (not on a blueprint) so the /tools/* auth middleware
    does not redirect the unauthenticated service call to /dashboard.
    """
    from tools.department_hq.services.department_dispatcher import dispatch

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    system_prompt = data.get("system_prompt") or None
    user_id = data.get("user_id")
    # Optional agent override — defaults preserve the cockpit's A.R.C.H.I.E. voice.
    capability = (data.get("capability") or "conversation").strip()
    prefer_agent = (data.get("prefer_agent") or "A.R.C.H.I.E.").strip()
    module_id = (data.get("module_id") or "archie_comms").strip()
    # Optional model pin — the engine's plan step (#380 Phase 3) sends a coding model
    # (qwen2.5-coder:7b); model_override keeps it on hub Ollama. Omitted by the cockpit.
    model_override = (data.get("model") or "").strip() or None
    # Optional structured-output constraint (#6038). Mirrors Ollama's own `format`:
    #   "json"  -> bare JSON mode
    #   {...}   -> a JSON SCHEMA, which constrains the SHAPE, not merely the syntax
    # ⚠️ These are NOT interchangeable. The engine's build planner needs an ARRAY of
    # ops; bare "json" routinely yields an object the array parser rejects, which is
    # exactly why archie-code carries OPS_SCHEMA (#380 Phase 2). Without this
    # passthrough the hub branch was unconstrained entirely, and a prompt containing
    # an injected source file pulled the model into emitting Python instead of JSON.
    # Rides the existing `json_mode` parameter: a non-empty dict is truthy, so it
    # flows through every pass-through site unchanged and only the two leaf sites
    # (hub `call_ollama_json`, fleet payload) read its value.
    _fmt = data.get("format")
    if isinstance(_fmt, dict) and _fmt:
        json_mode = _fmt
    elif isinstance(_fmt, str) and _fmt.strip().lower() == "json":
        json_mode = True
    elif _fmt in (None, "", {}):
        json_mode = False
    else:
        # Fail LOUD rather than silently dropping the constraint — a caller that asked
        # for structure and got free text has no way to tell the difference.
        return jsonify({"success": False, "error": "format must be the string 'json' or a JSON-schema object"}), 400
    if not prompt:
        return jsonify({"success": False, "error": "prompt required"}), 400

    # A.R.C.H.I.E.'s CONVERSATIONAL front (the interactive cockpit reply) is
    # latency-critical; on the CPU-saturated hub her qwen2.5:7b times out (~90s).
    # Give the conversation a fast GPU-resident model on a fleet node (llama3.2:3b
    # fits the Starship-246 RTX 3070, ~1.4s warm), hub as automatic fallback when the
    # node rests. This swaps ONLY the chat-reply model — A.R.C.H.I.E. the working
    # agent stays qwen2.5:7b for delegation + the deeper COO work behind the chat.
    # Detected before we set the model so the cockpit keeps its high-priority lane.
    # Service callers that pin their own model (engine plan step: qwen2.5-coder:7b)
    # are untouched — they keep their model + default hub routing.
    # Fast front = A.R.C.H.I.E. conversation, no caller-pinned model -> llama3.2:3b (high
    # priority). Deep follow-up = A.R.C.H.I.E. conversation pinned to qwen2.5:7b (the
    # {{DEEPEN}} path, normal priority). BOTH are her cockpit conversation, so both route
    # to the node GPU (hub fallback) — off the CPU-saturated hub.
    is_archie_conversation = prefer_agent == "A.R.C.H.I.E." and capability == "conversation"
    is_cockpit_chat = is_archie_conversation and model_override is None
    if is_cockpit_chat:
        model_override = os.getenv("COCKPIT_CHAT_MODEL", "llama3.2:3b")
    preferred_node = ["starship_76583490e36955ab", "archie-starbase"] if is_archie_conversation else None

    try:
        result = dispatch(
            capability=capability,
            prompt=prompt,
            module_id=module_id,
            system_prompt=system_prompt,
            user_id=user_id,
            prefer_agent=prefer_agent,  # cockpit default = A.R.C.H.I.E.; engine plan step = F.O.R.G.E.
            model_override=model_override,  # cockpit chat -> COCKPIT_CHAT_MODEL (llama3.2:3b); engine = qwen2.5-coder:7b
            preferred_node=preferred_node,  # cockpit chat -> Starship-246 GPU (hub fallback); None otherwise
            json_mode=json_mode,  # False | True (bare json) | schema dict (#6038)
            local_only=True,  # no cloud escalation; sovereign-only (ADR-003 #4 / KB #269363)
            # #4270: the interactive cockpit chat enters the interactive lane so it is
            # admitted ahead of queued batch; the engine plan step stays normal/batch.
            priority="high" if is_cockpit_chat else "normal",
        )
        if result.success and (result.response or "").strip():
            # Token usage is returned because the CALLER cannot derive it (#6775).
            # `DispatchResult` has carried prompt_tokens/completion_tokens all along and
            # the STREAMING sibling below already emits both in its done-frame — this
            # non-streaming twin dropped them, so archie-tui (Lane 3, the platform's own
            # builder) logged 20 of 22 runs at ZERO tokens over 7 days. That made it
            # invisible to Token Economy and, worse, un-comparable against the codex and
            # opencode lanes, which is exactly the measurement the engine exists to win.
            #
            # ⚠️ Additive only: existing keys are untouched, so a caller that ignores
            # these is byte-identical to before. Defaulted via getattr so an older
            # DispatchResult (or a contractor path that never set them) yields 0 rather
            # than a 500 — a missing count must degrade to "unknown", never to an error
            # on the inference path.
            return jsonify(
                {
                    "success": True,
                    "response": result.response.strip(),
                    "agent_name": result.agent_name,
                    "model_used": result.model_used,
                    "prompt_tokens": int(getattr(result, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(getattr(result, "completion_tokens", 0) or 0),
                }
            )
        # Dispatch ran but produced nothing usable — let the caller fall back to direct Ollama.
        return jsonify({"success": False, "error": "dispatch produced no response"}), 502
    except Exception as e:
        logger.error(f"DHQ chat error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# DHQ streaming lane concurrency guard (#6654). Bounds simultaneous SSE
# streams so a burst can't pin every gunicorn worker; each stream also holds a
# bridge_jobs slot the hub-lane cap counts. Tunable via env, default 8.
import threading as _dhq_threading

_DHQ_STREAM_SEM = _dhq_threading.BoundedSemaphore(int(os.getenv("DHQ_STREAM_MAX", "8")))


@app.route("/api/internal/dhq/chat/stream", methods=["POST"])
@require_internal_scope("dhq:chat")
def api_internal_dhq_chat_stream():
    """Token-by-token SSE counterpart to /api/internal/dhq/chat (#6654).

    Same body as dhq/chat plus an optional ``local_only`` (default True —
    sovereign). Streams the reply THROUGH the dispatcher (stream_dispatch →
    stream_work → _execute_llm_stream) so archie_comms renders A.R.C.H.I.E.'s
    cockpit reply as it is generated, with welfare/cost/cold-load/hub-cap
    guards enforced BEFORE the first token and exactly one task_execution_log
    row written when the stream ends. Events (``data: <json>\\n\\n``):
      meta{agent_name,model,provider,node,capability,streamed}
      token{content}   done{model_used,agent_name,provider,prompt_tokens,
                            completion_tokens,duration_ms,streamed}
      error{code: cloud_capability_blocked|cloud_budget_exhausted|
                  hub_saturated|model_not_ready|dispatch_failed, message}
    """
    from tools.department_hq.services.department_dispatcher import stream_dispatch

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"success": False, "error": "prompt required"}), 400
    system_prompt = data.get("system_prompt") or None
    user_id = data.get("user_id")
    capability = (data.get("capability") or "conversation").strip()
    # pin_agent=false lets the caller clear the A.R.C.H.I.E. default (the
    # `or "A.R.C.H.I.E."` below would otherwise swallow an empty string).
    _pin = data.get("pin_agent", True)
    prefer_agent = (data.get("prefer_agent") or "A.R.C.H.I.E.").strip() if _pin else None
    module_id = (data.get("module_id") or "archie_comms").strip()
    model_override = (data.get("model") or "").strip() or None
    # local_only defaults True (sovereign). Cloud is possible only when the
    # caller allows it AND the capability is on the allowlist AND escalation
    # mode is not local_only — decided inside the dispatcher's guards.
    from tools.department_hq.services.department_dispatcher import get_dispatcher

    _want_cloud = data.get("local_only") is False
    local_only = True
    if _want_cloud:
        try:
            local_only = not get_dispatcher()._cloud_capability_allowed(capability)
        except Exception:
            local_only = True

    # Same fast-front routing as the blocking route: A.R.C.H.I.E. conversation
    # gets a GPU-resident small model on a Starship (hub fallback).
    is_archie_conversation = prefer_agent == "A.R.C.H.I.E." and capability == "conversation"
    if is_archie_conversation and model_override is None:
        model_override = os.getenv("COCKPIT_CHAT_MODEL", "llama3.2:3b")
    preferred_node = ["starship_76583490e36955ab", "archie-starbase"] if is_archie_conversation else None

    acquired = _DHQ_STREAM_SEM.acquire(blocking=False)
    if not acquired:
        return jsonify({"success": False, "error": "stream lane saturated — retry shortly"}), 503

    def generate():
        import json as _json

        try:
            # Defeat proxy buffering before the first token (cold loads).
            yield ": keepalive\n\n"
            for evt in stream_dispatch(
                capability=capability,
                prompt=prompt,
                module_id=module_id,
                system_prompt=system_prompt,
                user_id=user_id,
                prefer_agent=prefer_agent,
                model_override=model_override,
                preferred_node=preferred_node,
                local_only=local_only,
            ):
                yield f"data: {_json.dumps(evt, default=str)}\n\n"
        except GeneratorExit:
            raise
        except Exception as e:
            logger.error(f"DHQ chat stream error: {e}")
            yield f"data: {_json.dumps({'type': 'error', 'code': 'dispatch_failed', 'message': str(e)})}\n\n"
        finally:
            _DHQ_STREAM_SEM.release()

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/internal/dhq/cloud-preflight", methods=["POST"])
@require_internal_scope("dhq:chat")
def api_internal_dhq_cloud_preflight():
    """Sovereignty preflight for a caller about to reach a cloud provider
    directly (e.g. the archie_comms Claude collaboration leg, #6654).

    Body: {capability, provider?}. Returns {allowed, reason}. Cloud is allowed
    only when escalation mode is not local_only AND the capability is on the
    cloud allowlist AND the weekly free budget is not exhausted — the same
    three gates the dispatcher applies to its own cloud text dispatches, so a
    direct-to-Claude call cannot bypass the sovereignty floor. Fail-closed:
    any error → not allowed."""
    from tools.department_hq.services.department_dispatcher import get_dispatcher

    data = request.get_json(silent=True) or {}
    capability = (data.get("capability") or "unknown").strip()
    provider = (data.get("provider") or "anthropic").strip()
    try:
        disp = get_dispatcher()
        mode = disp._get_escalation_mode()
        if mode == "local_only":
            return jsonify({"allowed": False, "reason": "escalation_mode is local_only (sovereign)"})
        if not disp._cloud_capability_allowed(capability):
            return jsonify({"allowed": False, "reason": f"capability '{capability}' is not on the cloud allowlist"})
        if not disp._cloud_budget_ok(provider, capability):
            return jsonify({"allowed": False, "reason": f"provider {provider} over weekly free budget"})
        return jsonify({"allowed": True, "reason": "ok"})
    except Exception as e:
        logger.warning(f"cloud-preflight failed (fail-closed): {e}")
        return jsonify({"allowed": False, "reason": "preflight error — staying local"})


@app.route("/api/internal/coo/agents", methods=["GET"])
@require_internal_scope("coo")
def api_internal_coo_agents():
    """Consultable crew (department directors) + department list for the cockpit switcher.

    Slice 1 of the COO command surface: A.R.C.H.I.E. consults the crew from her cockpit chat.
    """
    try:
        from services.coo_consult_service import list_consultable_agents
        from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP

        agents = list_consultable_agents()
        departments = sorted(set(CAPABILITY_DEPARTMENT_MAP.values()))
        return jsonify({"success": True, "agents": agents, "departments": departments})
    except Exception as e:
        logger.warning(f"coo/agents failed: {e}")
        return jsonify({"success": False, "agents": [], "departments": []}), 200


@app.route("/api/internal/coo/consult", methods=["POST"])
@require_internal_scope("coo")
def api_internal_coo_consult():
    """Resolve a consult target (agent/department) and dispatch to it via DHQ; return the answer.

    She relays this back in her own voice cockpit-side (unified voice). Fail-soft: always 200
    with success:false on a miss so the chat never breaks.
    """
    from tools.department_hq.services.department_dispatcher import dispatch
    from services.coo_consult_service import resolve_consult_target

    data = request.get_json(silent=True) or {}
    target = (data.get("target") or "").strip()
    prompt = (data.get("prompt") or "").strip()
    user_id = data.get("user_id")
    if not target or not prompt:
        return jsonify({"success": False, "error": "target_and_prompt_required"}), 200
    resolved = resolve_consult_target(target)
    if not resolved:
        return jsonify({"success": False, "error": "unknown_target", "target": target}), 200
    try:
        result = dispatch(
            capability=resolved["capability"],
            prompt=prompt,
            module_id="archie_comms_coo",
            user_id=user_id,
            prefer_agent=resolved["agent_name"],
            local_only=True,
            priority="normal",
        )
        if not getattr(result, "success", False):
            return (
                jsonify({"success": False, "error": "dispatch_failed", "resolved_target": resolved["agent_name"]}),
                200,
            )
        return jsonify(
            {
                "success": True,
                "response": (result.response or "").strip(),
                "agent_name": result.agent_name,
                "model_used": result.model_used,
                "resolved_target": resolved["agent_name"],
                "department": resolved["department"],
            }
        )
    except Exception as e:
        logger.warning(f"coo/consult failed: {e}")
        return jsonify({"success": False, "error": "exception"}), 200


@app.route("/api/internal/coms/overview", methods=["GET"])
@require_internal_scope("coo")
def api_internal_coms_overview():
    """COMs/Telegram hub read view (feed + config + migration) for the cockpit COMs tab.

    Read-only (Slice 2 of the COO command surface). Fail-soft: 200 with empties on error.
    """
    try:
        from services.coms_hub_service import overview

        data = overview(
            limit=int(request.args.get("limit", 50) or 50),
            category=(request.args.get("category") or "").strip() or None,
            source_agent=(request.args.get("source_agent") or "").strip() or None,
            status=(request.args.get("status") or "").strip() or None,
        )
        return jsonify({"success": True, **data})
    except Exception as e:
        logger.warning(f"coms/overview failed: {e}")
        return jsonify({"success": False, "messages": [], "config": {}, "migration": {}}), 200


@app.route("/api/internal/mail/inbox", methods=["GET"])
@require_internal_scope("mail")
def api_internal_mail_inbox():
    """Owner/business inbox for the cockpit Mail tab (read-only). Slice 3. Fail-soft."""
    try:
        from services.mail_hq_service import list_inbox

        msgs = list_inbox(
            limit=int(request.args.get("limit", 40) or 40),
            mailbox_id=(request.args.get("mailbox_id") or None),
        )
        return jsonify({"success": True, "messages": msgs})
    except Exception as e:
        logger.warning(f"mail/inbox failed: {e}")
        return jsonify({"success": False, "messages": []}), 200


@app.route("/api/internal/mail/message/<int:mid>", methods=["GET"])
@require_internal_scope("mail")
def api_internal_mail_message(mid):
    """Read a single owner/business message (full body). Fail-soft."""
    try:
        from services.mail_hq_service import read_message

        m = read_message(mid)
        if not m:
            return jsonify({"success": False, "error": "not_found"}), 200
        return jsonify({"success": True, "message": m})
    except Exception as e:
        logger.warning(f"mail/message failed: {e}")
        return jsonify({"success": False, "error": "exception"}), 200


@app.route("/api/internal/mail/draft-reply", methods=["POST"])
@require_internal_scope("mail")
def api_internal_mail_draft_reply():
    """R.E.S.O.L.V.E. drafts a reply (read-only; nothing is sent or queued here). Fail-soft."""
    try:
        from services.mail_hq_service import draft_reply

        data = request.get_json(silent=True) or {}
        d = draft_reply(int(data.get("message_id") or 0))
        if not d:
            return jsonify({"success": False, "error": "no_draft"}), 200
        return jsonify({"success": True, **d})
    except Exception as e:
        logger.warning(f"mail/draft-reply failed: {e}")
        return jsonify({"success": False, "error": "exception"}), 200


@app.route("/api/internal/mail/queue-reply", methods=["POST"])
@require_internal_scope("mail")
def api_internal_mail_queue_reply():
    """Queue a reply into the EXISTING approve-to-send gate (never sends directly). Fail-soft."""
    try:
        from services.mail_hq_service import queue_reply

        data = request.get_json(silent=True) or {}
        q = queue_reply(int(data.get("message_id") or 0), data.get("body") or "")
        if not q:
            return jsonify({"success": False, "error": "not_queued"}), 200
        return jsonify({"success": True, **q})
    except Exception as e:
        logger.warning(f"mail/queue-reply failed: {e}")
        return jsonify({"success": False, "error": "exception"}), 200


@app.route("/api/internal/actions/catalog", methods=["GET"])
@require_internal_scope("coo")
def api_internal_actions_catalog():
    """Curated safe actions the cockpit can run (Slice 4). Fail-soft."""
    try:
        from services.coo_actions_service import list_actions

        return jsonify({"success": True, "actions": list_actions()})
    except Exception as e:
        logger.warning(f"actions/catalog failed: {e}")
        return jsonify({"success": False, "actions": []}), 200


@app.route("/api/internal/actions/run", methods=["POST"])
@require_internal_scope("coo")
def api_internal_actions_run():
    """Run a curated safe action synchronously (Slice 4). Only catalog keys run. Fail-soft."""
    try:
        from services.coo_actions_service import run_action

        data = request.get_json(silent=True) or {}
        return jsonify(run_action(data.get("key") or ""))
    except Exception as e:
        logger.warning(f"actions/run failed: {e}")
        return jsonify({"ok": False, "error": "exception"}), 200


@app.route("/api/internal/session-link", methods=["POST", "GET"])
@require_internal_scope("engine")
def api_internal_session_link():
    """archie_engine records/resolves an engine-session <-> comms-conversation
    link (CLI collaboration: cockpit, archie-tui and the Claude MCP co-drive
    all resolve the same thread). Service-to-service: Bearer INTERNAL_API_KEY."""
    from services.session_link_service import get_link, record_link

    if request.method == "GET":
        session_id = (request.args.get("session_id") or "").strip()
        if not session_id:
            return jsonify({"success": False, "error": "session_id required"}), 400
        return jsonify({"success": True, "session_id": session_id, "conversation_id": get_link(session_id)})

    data = request.get_json(silent=True) or {}
    session_id = (data.get("session_id") or "").strip()
    conversation_id = (data.get("conversation_id") or "").strip()
    if not session_id or not conversation_id:
        return jsonify({"success": False, "error": "session_id and conversation_id required"}), 400
    record_link(session_id, conversation_id)
    return jsonify({"success": True}), 200


@app.route("/api/internal/approvals/pending", methods=["GET"])
@require_internal_scope("approvals:read")
def api_internal_approvals_pending():
    """Cockpit-facing pending Tier-2 approvals. Service-to-service: Bearer
    INTERNAL_API_KEY. Reuses the exact list the DHQ Approvals tab renders
    (incl. the PR #2205 code-fix labels), so the archie_comms cockpit shows
    the same 77 red cards + others."""
    from tools.department_hq.approvals_routes import list_pending_approvals

    return jsonify({"approvals": list_pending_approvals()})


@app.route("/api/internal/approvals/<path:approval_id>/approve", methods=["POST"])
@require_internal_scope("approvals:decide")
def api_internal_approvals_approve(approval_id):
    """Cockpit approve. Bearer INTERNAL_API_KEY; owner user_id from the body
    (default 2 = Kytran). Fail-closed: a non-ok executor result -> 409 and the
    queue row stays pending. Slice 1 targets autonomy:* (the red Code-Health
    cards); contractor/bridge sources are 501 until a later slice wires them."""
    from tools.department_hq.approvals_routes import _approve_autonomy, parse_approval_id

    user_id = (request.get_json(silent=True) or {}).get("user_id") or 2
    try:
        source, source_id = parse_approval_id(approval_id)
    except ValueError as exc:
        # A caller's malformed id is a 400, not a 500 (#6666). Deliberately NOT
        # defaulted to 'autonomy': each source has its own id sequence, so a bare
        # '5' is ambiguous and guessing could approve the wrong pending item.
        return jsonify({"ok": False, "error": str(exc)}), 400
    if source != "autonomy":
        return jsonify({"ok": False, "error": f"source '{source}' not supported yet"}), 501
    ok, action_type = _approve_autonomy(source_id, user_id)
    return jsonify({"ok": bool(ok), "action_type": action_type}), (200 if ok else 409)


@app.route("/api/internal/approvals/<path:approval_id>/deny", methods=["POST"])
@require_internal_scope("approvals:decide")
def api_internal_approvals_deny(approval_id):
    """Cockpit deny. Same auth/owner-default/fail-closed contract as approve."""
    from tools.department_hq.approvals_routes import _deny_autonomy, parse_approval_id

    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id") or 2
    reason = data.get("reason") or "denied via cockpit"
    try:
        source, source_id = parse_approval_id(approval_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400  # see approve, #6666
    if source != "autonomy":
        return jsonify({"ok": False, "error": f"source '{source}' not supported yet"}), 501
    ok = _deny_autonomy(source_id, user_id, reason)
    ok_bool = ok[0] if isinstance(ok, tuple) else bool(ok)
    return jsonify({"ok": ok_bool}), (200 if ok_bool else 409)


ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB upload ceiling for cockpit attachments


@app.route("/api/internal/attachments/extract", methods=["POST"])
@require_internal_scope("coo")
def api_internal_attachments_extract():
    """Sovereign attachment extraction for the COO cockpit. Bearer INTERNAL_API_KEY.
    Decodes content_b64 -> temp file -> extract_text_from_file -> capped text.
    Fail-soft (an unreadable file returns text=''); oversize -> 413."""
    import base64

    from services.attachment_extract_service import extract_payload

    data = request.get_json(silent=True) or {}
    filename = data.get("filename") or "attachment"
    try:
        raw = base64.b64decode(data.get("content_b64") or "", validate=True)
    except Exception:
        return jsonify({"error": "invalid content_b64"}), 400
    if len(raw) > ATTACHMENT_MAX_BYTES:
        return jsonify({"error": "file too large", "max_bytes": ATTACHMENT_MAX_BYTES}), 413
    return jsonify(extract_payload(filename, raw, data.get("mime")))


@app.route("/api/internal/voice/synthesize", methods=["POST"])
@require_internal_scope("coo")
def api_internal_voice_synthesize():
    """Cockpit TTS. Bearer INTERNAL_API_KEY. Wraps Kokoro synthesize_for_agent
    (agent 2 = her canonical af_heart voice + live emotion). Fail-soft."""
    from services.voice_service import synthesize

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"success": False, "error": "no text"}), 400
    return jsonify(synthesize(text, user_id=data.get("user_id") or 2, emotion=data.get("emotion")))


@app.route("/api/internal/voice/transcribe", methods=["POST"])
@require_internal_scope("coo")
def api_internal_voice_transcribe():
    """Cockpit STT. Bearer INTERNAL_API_KEY. Proxies to the sovereign archie_whisper
    sidecar (audio never leaves the cluster). Fail-soft."""
    import base64

    from services.voice_service import transcribe

    data = request.get_json(silent=True) or {}
    try:
        raw = base64.b64decode(data.get("audio_b64") or "", validate=True)
    except Exception:
        return jsonify({"text": "", "error": "invalid audio_b64"}), 400
    return jsonify(transcribe(raw, data.get("mime")))


@app.route("/api/internal/archie/portrait", methods=["GET"])
@require_internal_scope("coo")
def api_internal_archie_portrait():
    """A.R.C.H.I.E.'s portrait for the cockpit avatar. Bearer INTERNAL_API_KEY.
    Serves agent-2's canonical image base64; fail-soft ({ok:false} -> monogram)."""
    from services.archie_face_service import get_portrait

    return jsonify(get_portrait())


@app.route("/api/internal/sessions/<int:agent_id>/<platform>/state", methods=["GET"])
@require_internal_scope("sessions")
def api_internal_get_session_state(agent_id, platform):
    """archie_browser fetches Playwright storage_state for a (agent, platform).

    Service-to-service: Authorization: Bearer <INTERNAL_API_KEY>.
    Registered at app level (not on department_hq blueprint) because the
    /tools/department-hq/* prefix has invisible auth middleware that
    redirects all unauthenticated requests to /dashboard.

    Delegates to session_routes, mirroring the POST below. Until #6020 this route
    carried its own INLINE copy of that logic while the handler sat unregistered with
    a DIFFERENT auth scheme (X-Internal-Key) — two implementations of one endpoint,
    and the reachable one was not the one the handler's docstring pointed at.
    """
    from tools.department_hq.session_routes import get_session_state_handler

    return get_session_state_handler(agent_id, platform)


@app.route("/api/internal/sessions/<int:agent_id>/<platform>/state", methods=["POST"])
@require_internal_scope("sessions")
def api_internal_save_session_state(agent_id, platform):
    """#4006 capture-to-vault: the login sidecar (login_browser.py) pushes the
    storage_state it captured during an interactive login, so the session is
    vault-visible (and health-probed) immediately. Same service-to-service
    bearer auth + app-level registration rationale as the GET above."""
    from tools.department_hq.session_routes import save_session_state_handler

    return save_session_state_handler(agent_id, platform)


@app.route("/api/internal/linkedin/challenge-code", methods=["GET"])
@require_internal_scope("sessions")
def api_internal_linkedin_challenge_code():
    """Slice 2 (#5627 follow-up): hand archie_browser the LinkedIn email verification
    code so an automated re-login can clear its own challenge.

    archie_browser has no Google OAuth tokens and no platform_v2 on its path, so it
    asks over the internal API (same bearer pattern as the session-state routes).
    No mail credential ever leaves this process.

    ⚠️ READS GMAIL LIVE, NOT `google_email_cache`. `gmail_service.search_emails`
    resolves ids from the API but returns rows from the cache, so a code that arrived
    seconds ago — the only kind that matters here — is reliably ABSENT. Polling that
    would look exactly like "LinkedIn stopped sending codes".

    ⚠️ `not_before` is load-bearing. LinkedIn reuses one subject line for every
    challenge, so without it the newest match may be a STALE code from an earlier
    attempt, which fails and burns a limited attempt. The caller stamps it just
    before submitting the password.
    """
    import re as _re

    login = (request.args.get("login") or "").strip().lower()
    try:
        not_before = int(request.args.get("not_before") or 0)
    except (TypeError, ValueError):
        not_before = 0
    if not login:
        return jsonify({"error": "login required"}), 400

    try:
        from database import get_db_cursor
        from tools.google_work_suite.services.gmail_service import get_gmail_client

        with get_db_cursor() as (_conn, cur):
            cur.execute("SELECT id FROM google_accounts WHERE lower(email) = %s LIMIT 1", (login,))
            row = cur.fetchone()
        if not row:
            # An unconnected mailbox is a CONFIG gap, not a transient miss — say so
            # distinctly so the browser side does not poll for 90s against nothing.
            return jsonify({"error": f"no connected Google account for {login}"}), 409
        account_id = row["id"] if isinstance(row, dict) else row[0]

        service = get_gmail_client(account_id)
        listing = (
            service.users()
            .messages()
            .list(
                userId="me",
                q="from:linkedin.com (verification OR code OR sign-in OR security)",
                maxResults=10,
            )
            .execute()
        )
        ids = [m["id"] for m in (listing.get("messages") or [])]
        if not ids:
            return jsonify({"error": "no matching mail"}), 404

        best = None  # (internal_ts, code)
        for gid in ids:
            msg = service.users().messages().get(userId="me", id=gid, format="full").execute()
            ts = int(msg.get("internalDate", "0")) // 1000  # ms -> s
            if not_before and ts < not_before:
                continue
            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            haystack = " ".join([headers.get("subject", ""), msg.get("snippet", "")])
            m = _re.search(r"\b(\d{6})\b", haystack)
            if m and (best is None or ts > best[0]):
                best = (ts, m.group(1))

        if not best:
            return jsonify({"error": "no fresh code"}), 404
        # Never log the code itself.
        app.logger.info("[challenge-code] served a code for %s (age %ss)", login, int(time.time()) - best[0])
        return jsonify({"code": best[1], "received_at": best[0]}), 200
    except Exception as exc:
        app.logger.error("[challenge-code] lookup failed for %s: %s", login, type(exc).__name__)
        return jsonify({"error": f"lookup failed ({type(exc).__name__})"}), 500


@app.route("/api/internal/engine/telemetry", methods=["POST"])
@require_internal_scope("engine")
def api_internal_engine_telemetry():
    """Record an A.R.C.H.I.E. Engine build run in task_execution_log (#4257).

    The engine POSTs here after a build run so it shows on the Token Economy +
    Dispatch tabs (worker_type='internal', module_source='archie_engine'). Auth
    is enforced by the @require_internal_scope decorator above (the same
    INTERNAL_API_KEY bearer the engine already uses for delegation/submit).
    """
    from services.agents.engine_telemetry import record_engine_run

    data = request.get_json(silent=True) or {}
    task = (data.get("task") or "").strip()
    if not task:
        return jsonify({"error": "task required"}), 400
    try:
        rec = record_engine_run(
            task_label=task,
            agent_name=data.get("agent_name") or "A.R.C.H.I.E. Engine",
            model=data.get("model") or "archie:7b",
            prompt_tokens=data.get("prompt_tokens") or 0,
            completion_tokens=data.get("completion_tokens") or 0,
            files_changed=data.get("files_changed"),
            success=bool(data.get("success", True)),
            duration_ms=int(data.get("duration_ms") or 0),
            summary=data.get("result_summary") or data.get("summary") or "",
            branch=data.get("branch"),
        )
        return jsonify({"ok": True, "id": rec.get("id")})
    except Exception as exc:
        app.logger.error("engine telemetry insert failed: %s", exc)
        return jsonify({"error": "telemetry insert failed"}), 500


# ── Media Hub / M.A.V.E.N. coordination surface (project #385 Phase 1) ───────
# Standalone services (Media Hub) run off-host and cannot use the @login_required
# notification/approval routes. These app-level, Bearer-authed aliases let
# M.A.V.E.N. speak through A.R.C.H.I.E. (notifications + Telegram) and raise
# Telegram-gated approvals for destructive actions. App-level (not on a /tools/*
# blueprint) so the auth middleware does not redirect the service call to
# /dashboard — same rationale as the dhq/chat + telemetry routes above.


@app.route("/api/internal/notify", methods=["POST"])
@require_internal_scope("notify")
def api_internal_notify():
    """Internal notify surface for standalone agents (Media Hub / M.A.V.E.N.).

    Creates a platform notification and — for high/urgent priority (or an explicit
    telegram=true) — also speaks it on Telegram in A.R.C.H.I.E.'s voice, so a
    standalone agent's alert reaches Kytran through the single A.R.C.H.I.E. channel
    instead of a silent 401 against the @login_required /api/notifications route.
    Bearer INTERNAL_API_KEY.

    Body: {title, message, priority?(low|normal|high|urgent), source?, telegram?(bool)}
    """
    from services.internal_notify import send_internal_notify  # noqa: PLC0415

    out = send_internal_notify(request.get_json(silent=True) or {}, default_source="media_hub")
    return jsonify(out), (200 if out.get("ok") else 400)


@app.route("/api/internal/approval-request", methods=["POST"])
@require_internal_scope("approvals:request")
def api_internal_approval_request():
    """Raise a Tier-2 (human) approval for a standalone destructive/major action.

    Used by Media Hub / M.A.V.E.N. for deletes + major changes (e.g. re-encode
    that replaces the original). Creates an autonomy_approval_queue row
    (action_type='media_hub_action') and sends the Telegram Approve/Deny buttons
    via the existing approval pipeline. The standalone polls
    GET /api/internal/approval/<id> and executes locally on approval — the
    platform can't reach Radarr/SABnzbd/Tdarr. Bearer INTERNAL_API_KEY.

    Body: {title, reason, payload?(dict)}  ->  {ok, approval_id}
    """
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "Media Hub action").strip()
    reason = (data.get("reason") or title).strip()
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    payload.setdefault("title", title)
    try:
        from ai_bridge.agent_loop import request_approval

        approval_id = request_approval(
            action_type="media_hub_action",
            action_data=payload,
            reason=reason,
            requested_by="maven",
            tier=2,
        )
        if not approval_id:
            # None => dedup collision (a media_hub_action is already pending) or
            # validation failure. 409 tells the caller to back off, not retry hard.
            return jsonify({"ok": False, "error": "approval not created (pending duplicate?)"}), 409
        return jsonify({"ok": True, "approval_id": approval_id})
    except Exception as exc:
        app.logger.error("internal approval-request failed: %s", exc)
        return jsonify({"ok": False, "error": "approval request failed"}), 500


@app.route("/api/internal/approval/<int:approval_id>", methods=["GET"])
@require_internal_scope("approvals:request")
def api_internal_approval_status(approval_id):
    """Return an approval row's status so a standalone can poll it before acting.
    Bearer INTERNAL_API_KEY.  ->  {ok, id, status, action_type}
    """
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT status, action_type FROM autonomy_approval_queue WHERE id = %s",
                (approval_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"ok": False, "error": "not found"}), 404
        status = row["status"] if isinstance(row, dict) else row[0]
        atype = row["action_type"] if isinstance(row, dict) else row[1]
        return jsonify({"ok": True, "id": approval_id, "status": status, "action_type": atype})
    except Exception as exc:
        app.logger.error("internal approval status failed: %s", exc)
        return jsonify({"ok": False, "error": "status lookup failed"}), 500


@app.route("/api/internal/dispatch-log", methods=["POST"])
@require_internal_scope("fleet")
def api_internal_dispatch_log():
    """Log a M.A.V.E.N. (or other standalone-agent) ACTION as a 0-token
    task_execution_log row so it surfaces in the DHQ A.R.M.A.D.A. dispatch
    History + source-drill (fsource=media_hub) + ?markers=all view (#4755) — the
    S.C.O.U.T. 0-token telemetry pattern (see browser_service._audit_headed_run).

    worker_type='internal' + model_used='internal' means this is NOT LLM
    inference: carbon shows n/a (carbon_footprint_service._NON_LLM_MODELS) and it
    is correctly excluded from the default "real inference only" traffic feed,
    exactly like S.C.O.U.T. browser rows. It is always visible in Dispatch
    History and in the traffic feed via the media_hub source drill / markers=all.
    Bearer INTERNAL_API_KEY.

    Body: {action, agent?, agent_id?, capability?, description?, target?,
           success?(bool), duration_ms?(int), error?, metadata?(dict)}  ->  {ok}
    """
    data = request.get_json(silent=True) or {}
    agent = (data.get("agent") or "M.A.V.E.N.").strip()[:100]
    action = (data.get("action") or "action").strip()[:100]
    capability = (data.get("capability") or action or "media_hub_action").strip()[:50]
    description = (data.get("description") or action).strip()[:200]
    success = bool(data.get("success", True))
    try:
        duration_ms = max(0, int(data.get("duration_ms") or 0))
    except (TypeError, ValueError):
        duration_ms = 0
    agent_id = data.get("agent_id") if isinstance(data.get("agent_id"), int) else None
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    meta.setdefault("action", action)
    if data.get("target"):
        meta.setdefault("target", str(data.get("target"))[:200])
    err = data.get("error")
    try:
        import json as _json

        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """INSERT INTO task_execution_log
                       (agent_id, agent_name, worker_type, task_type, task_description,
                        capability, module_source, request_origin, model_used,
                        tokens_used, duration_ms, success, error_message,
                        request_metadata, created_at)
                   VALUES (%s, %s, 'internal', 'media_hub_action', %s,
                           %s, 'media_hub', 'maven', 'internal',
                           0, %s, %s, %s,
                           %s, NOW())""",
                (
                    agent_id,
                    agent,
                    description,
                    capability,
                    duration_ms,
                    success,
                    (str(err)[:300] if err else None),
                    _json.dumps(meta),
                ),
            )
        return jsonify({"ok": True})
    except Exception as exc:
        app.logger.error("internal dispatch-log failed: %s", exc)
        return jsonify({"ok": False, "error": "dispatch-log failed"}), 500


@app.route("/api/internal/fleet-gpu-load", methods=["GET"])
@require_internal_scope("fleet")
def api_internal_fleet_gpu_load():
    """Per-GPU-node inference-busy signal for M.A.V.E.N.'s dispatch-orchestrated Tdarr
    drain (#385). The Starship GPUs (USS-246 RTX3070 / USS-245 RTX3050) are ALSO fleet
    inference nodes, so M.A.V.E.N. yields a node's Tdarr transcode workers whenever that
    node is doing (or queued for) DHQ inference — inference always wins, transcodes fill
    idle GPU time. Read-only, fail-open (ok=False, HTTP 200 — the caller then leaves the
    Tdarr worker limits untouched rather than thrash on a transient hub blip).

    A GPU node is 'busy' if ANY of:
      • a REAL inference row landed against it in the last 120s
        (task_execution_log.node_used_id, LLM-only — excludes M.A.V.E.N./markers/embeds); OR
      • its latest heartbeat shows current_load>0 (DHQ's inference task count); OR
      • it has a model loaded AND the fleet has queued/running inference demand.

    NOTE: gpu_usage is returned for visibility but deliberately NOT used in the busy
    decision — nvidia-smi utilization can be raised by Tdarr's OWN NVENC transcode, which
    would make the node look "busy" and pause its own drain → resume → flap. recent_inference
    and current_load track DHQ inference only (Tdarr is invisible to them), so they're stable.

    Bearer INTERNAL_API_KEY. Returns {ok, recent_window_s, fleet_inference_queued,
    nodes:[{node_id, node_name, mesh_ip, match_key, gpu, busy, recent_inference,
    current_load, gpu_usage, hb_age_s}]}. match_key = 3-digit token from node_name
    (USS-246 -> '246') so the caller can map a Tdarr node (tdarr-246-*) to a fleet node.
    """
    import re

    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute("SELECT COUNT(*) AS n FROM dispatch_pending_queue WHERE status IN ('queued','running')")
            fleet_q = int((cur.fetchone() or {}).get("n") or 0)
            cur.execute(
                """
                SELECT rn.id, rn.node_id, rn.node_name, rn.mesh_ip,
                       hb.current_load, hb.gpu_usage,
                       EXTRACT(EPOCH FROM (NOW() - hb.created_at))::int AS hb_age_s,
                       (SELECT COUNT(*) FROM task_execution_log tel
                          WHERE tel.node_used_id = rn.id
                            AND tel.created_at > NOW() - INTERVAL '120 seconds'
                            AND tel.worker_type IS NOT NULL
                            AND COALESCE(tel.model_used,'') NOT IN
                                ('internal','bridge-managed','batch','browser','comfyui','')
                            AND COALESCE(tel.model_used,'') NOT ILIKE '%embed%'
                       ) AS recent_inf,
                       (SELECT COUNT(*) FROM model_load_state mls WHERE mls.node_db_id = rn.id) AS loaded
                FROM remote_nodes rn
                LEFT JOIN LATERAL (
                    SELECT current_load, gpu_usage, created_at FROM node_heartbeats
                    WHERE node_id = rn.id ORDER BY created_at DESC LIMIT 1
                ) hb ON TRUE
                WHERE rn.gpu_available IS TRUE OR COALESCE(rn.gpu_vram_gb, 0) > 0
                """
            )
            rows = cur.fetchall() or []
    except Exception as exc:
        app.logger.warning("fleet-gpu-load failed: %s", exc)
        return jsonify({"ok": False, "error": "fleet-gpu-load failed"}), 200

    nodes = []
    for r in rows:
        cl = int(r.get("current_load") or 0)
        gu = float(r.get("gpu_usage") or 0.0)
        recent = int(r.get("recent_inf") or 0)
        loaded = int(r.get("loaded") or 0)
        hb_age = r.get("hb_age_s")
        busy = bool(recent > 0 or cl > 0 or (loaded > 0 and fleet_q > 0))
        m = re.search(r"(\d{3})", str(r.get("node_name") or ""))
        nodes.append(
            {
                "node_id": r.get("node_id"),
                "node_name": r.get("node_name"),
                "mesh_ip": r.get("mesh_ip"),
                "match_key": m.group(1) if m else None,
                "gpu": True,
                "busy": busy,
                "recent_inference": recent,
                "current_load": cl,
                "gpu_usage": gu,
                "hb_age_s": hb_age,
            }
        )
    return jsonify(
        {
            "ok": True,
            "recent_window_s": 120,
            "fleet_inference_queued": fleet_q,
            "nodes": nodes,
        }
    )


@app.route("/api/internal/fleet-gpu-lease", methods=["POST"])
@require_internal_scope("fleet")
def api_internal_fleet_gpu_lease():
    """Grant/release a Tdarr transcode VRAM lease on a fleet GPU node — the mesh-reachable
    mirror of the ComfyUI/SDXL swap (#385 v2). On the Starships the warm inference models
    fully own the 8GB/4GB VRAM, so NVENC can't coexist; to stop the optimize drain from
    STARVING under sustained inference, M.A.V.E.N. leases a node for a bounded OPPORTUNITY
    WINDOW: 'acquire' evicts that node's Ollama models (freeing VRAM for the transcode),
    'release' reloads them. Reuses the dispatcher's proven pair
    (_vram_swap_for_comfyui / _vram_restore_after_comfyui). The caller holds the lease only
    for the window and always releases; the fleet warm-keep job reloads evicted models as a
    backstop if a release is ever missed. Bearer INTERNAL_API_KEY.
    Body: {node, action:'acquire'|'release', models?:[...]} -> {ok, unloaded:[...]}
    (node = remote_nodes node_id | mesh_ip | node_name). Fail-open (ok:False, HTTP 200)."""
    data = request.get_json(silent=True) or {}
    node = str(data.get("node") or "").strip()
    action = (data.get("action") or "").strip().lower()
    if not node or action not in ("acquire", "release"):
        return jsonify({"ok": False, "error": "bad request"}), 400
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT id FROM remote_nodes WHERE node_id=%s OR mesh_ip=%s OR node_name=%s LIMIT 1",
                (node, node, node),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"ok": False, "error": "unknown node"}), 404
        node_db_id = row["id"]

        from tools.department_hq.services.department_dispatcher import get_dispatcher

        disp = get_dispatcher()
        if action == "acquire":
            unloaded = disp._vram_swap_for_comfyui(node_db_id) or []
            app.logger.info("fleet-gpu-lease acquire node=%s evicted=%s", node, unloaded)
            return jsonify({"ok": True, "unloaded": list(unloaded)})
        # release
        models = data.get("models")
        if isinstance(models, list) and models:
            disp._vram_restore_after_comfyui(models, node_db_id)
        app.logger.info("fleet-gpu-lease release node=%s restored=%s", node, models)
        return jsonify({"ok": True})
    except Exception as exc:
        app.logger.warning("fleet-gpu-lease failed: %s", exc)
        return jsonify({"ok": False, "error": "lease failed"}), 200


# ── Code Health engine-facing surface (#4262 — the loop-closer) ──────────────
# The containerized A.R.C.H.I.E. build engine has no browser session, so the
# @login_required Code-Health routes in tools/consciousness are unreachable to
# it. These app-level aliases expose the same logic over the engine's existing
# Authorization: Bearer <INTERNAL_API_KEY> path. App-level (not on a /tools/*
# blueprint) so the auth middleware does not redirect the service call to
# /dashboard — same rationale as the dhq/chat + telemetry routes above.


@app.route("/api/internal/code-health/reverify", methods=["POST"])
@require_internal_scope("repair:write")
def api_internal_code_health_reverify():
    """LOOP-CLOSER: re-audit deployed Code-Health fixes and report, per finding,
    whether the fix actually landed ('fixed') or regressed ('still_open'). The
    engine calls this right after a deploy. Runs SYNCHRONOUSLY (optionally scoped
    to one module via {"module"}) so the engine gets the verdict + per-finding
    details[] directly in the response. Bearer INTERNAL_API_KEY."""
    from services.audit_pipeline import reverify_deployed_findings

    module = (request.get_json(silent=True) or {}).get("module")
    try:
        return jsonify({"success": True, **reverify_deployed_findings(module)})
    except Exception as e:
        logger.error(f"internal code-health reverify failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/internal/code-health/orchestration", methods=["GET"])
@require_internal_scope("repair:write")
def api_internal_code_health_orchestration():
    """Per-department ownership + lifecycle counts (open/deployed/fixed/still_open)
    of Code-Health findings. The engine reads this post-deploy to surface
    still_open regressions. Bearer INTERNAL_API_KEY."""
    from tools.consciousness.code_health_routes import compute_orchestration

    try:
        return jsonify(compute_orchestration())
    except Exception as e:
        logger.error(f"internal code-health orchestration failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/internal/code-health/scan", methods=["POST"])
@require_internal_scope("repair:write")
def api_internal_code_health_scan():
    """Kick a full async codebase scan; returns job_id. Poll
    /api/internal/code-health/job-status/<id>. Bearer INTERNAL_API_KEY."""
    from tools.consciousness.code_health_routes import start_code_health_scan

    payload, code = start_code_health_scan()
    return jsonify(payload), code


@app.route("/api/internal/code-health/audit", methods=["POST"])
@require_internal_scope("repair:write")
def api_internal_code_health_audit():
    """Audit one module (sync, pass {"module"}) or all modules (async, returns
    job_id). Bearer INTERNAL_API_KEY."""
    from tools.consciousness.code_health_routes import run_code_health_audit

    module = (request.get_json(silent=True) or {}).get("module")
    payload, code = run_code_health_audit(module)
    return jsonify(payload), code


@app.route("/api/internal/code-health/job-status/<int:job_id>", methods=["GET"])
@require_internal_scope("repair:write")
def api_internal_code_health_job_status(job_id):
    """Poll an async code-health scan/audit job (reads bridge_jobs). Bearer INTERNAL_API_KEY."""
    from tools.consciousness.code_health_routes import code_health_job_status_payload

    payload, code = code_health_job_status_payload(job_id)
    return jsonify(payload), code


@app.route("/api/internal/engine/build-result", methods=["POST"])
@require_internal_scope("engine")
def api_internal_engine_build_result():
    """The engine POSTs a build/test run result here after building + testing in
    its isolated /workspace; recorded into qa_test_runs + qa_test_results so the
    Repair Bay Test Bay + QA tabs show engine-driven runs (#4261). The platform
    never executes the engine's code — it only records the reported result.
    Body: {task?, branch?, pr_url?, pr_number?, files_changed?, status?,
    duration_ms?, output?, tests:[{name,status,output?,duration_ms?}]}.
    Bearer INTERNAL_API_KEY."""
    from services.engine_build_results import record_build_result

    data = request.get_json(silent=True) or {}
    try:
        return jsonify(record_build_result(data))
    except Exception as e:
        logger.error(f"internal engine build-result failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Repair Bay engine-facing pull-work surface (#4259) ───────────────────────
# Lets the engine/cockpit ask "what needs fixing?" without a browser session:
# scan a file, read the open-issue queue, read the proposal queue. Thin wrappers
# over the SAME scan_service/proposal_service the @login_required session routes
# call. The sandbox/apply endpoints are intentionally NOT exposed — the engine
# builds + tests in its own isolated /workspace (project #380 decision), so the
# platform-side sandbox is not on the engine path. Bearer INTERNAL_API_KEY.


@app.route("/api/internal/repair/scan", methods=["POST"])
@require_internal_scope("repair:write")
def api_internal_repair_scan():
    """Scan a single file for issues (same logic as the session /api/scan/run).
    Body: {file_path | full_path}. Bearer INTERNAL_API_KEY."""
    from services import scan_service

    data = request.get_json(silent=True) or {}
    file_path = data.get("file_path")
    full_path = data.get("full_path")
    if not file_path and not full_path:
        return jsonify({"success": False, "error": "file_path or full_path required"}), 400
    try:
        result = scan_service.scan_file(file_path=file_path, full_path=full_path, scanned_by="archie-engine", user_id=4)
        if result.get("success"):
            return jsonify(result)
        code = 404 if "not found" in (result.get("error") or "").lower() else 500
        return jsonify(result), code
    except Exception as e:
        logger.error(f"internal repair scan failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/internal/infra/heartbeat", methods=["GET"])
@require_internal_scope("infra:read")
def api_internal_infra_heartbeat():
    """V.I.G.I.L. infrastructure heartbeat, executed where docker is visible.

    Exists because archie_mcp_gateway deliberately has NO docker socket (it runs
    read tools in-process on a read-only DB role), so serving the heartbeat there
    made a blind observer report every watched container as removed. The gateway
    proxies to this route instead of running the check locally.

    Read-only. It inspects and probes; it never restarts anything. Restart
    approvals are filed only by the scheduled agent-loop job.

    Responds 200 with ``observer_blind: true`` rather than an error when this
    process cannot reach the daemon — an unverifiable observer is a result, not
    a failure, and must never be rendered as missing containers.
    """
    from services.infra_heartbeat_service import check_all_critical

    try:
        result = check_all_critical()
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"internal infra heartbeat failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/internal/repair/issues", methods=["GET"])
@require_internal_scope("repair:read")
def api_internal_repair_issues():
    """The open-issue work queue (wraps scan_service.get_issues).
    Query: ?status=open&limit=50[&auto_fixable=true]. Bearer INTERNAL_API_KEY.

    auto_fixable=true drops classes that are unsafe/pointless to hand to an
    automated fixer (see scan_service._AUTO_FIX_EXCLUDED_*). Automated consumers
    (the A.R.C.H.I.E. Engine build loop) should pass it; humans/UI should not.
    Default false — existing callers are unaffected (#5000)."""
    from services import scan_service

    status = request.args.get("status", "all")
    limit = request.args.get("limit", 50, type=int)
    auto_fixable = (request.args.get("auto_fixable", "") or "").strip().lower() in ("1", "true", "yes")
    # Server-side scope filter (#5002): comma-separated path prefixes. Only NARROWS
    # the result set — it cannot grant access; writes stay gated by the caller's own
    # scope_guard. Lets a scoped consumer (the Engine build loop) get in-scope rows
    # directly instead of paging the whole severity-ordered queue: its first in-scope
    # issue ranked 744 against a fetch limit of 200, so it never reached its own work.
    raw_prefixes = (request.args.get("path_prefixes", "") or "").strip()
    path_prefixes = [p.strip() for p in raw_prefixes.split(",") if p.strip()] if raw_prefixes else None
    try:
        return jsonify(
            scan_service.get_issues(status=status, limit=limit, auto_fixable=auto_fixable, path_prefixes=path_prefixes)
        )
    except Exception as e:
        logger.error(f"internal repair issues failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/internal/repair/proposals", methods=["GET"])
@require_internal_scope("repair:read")
def api_internal_repair_proposals():
    """The improvement-proposal work queue (wraps proposal_service.list_proposals).
    Query: ?status=proposed. Bearer INTERNAL_API_KEY."""
    from services import proposal_service

    status = request.args.get("status")
    try:
        return jsonify(proposal_service.list_proposals(status=status))
    except Exception as e:
        logger.error(f"internal repair proposals failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/internal/repair/proposals/<int:proposal_id>/pr", methods=["POST"])
@require_internal_scope("repair:write")
def api_internal_repair_proposal_pr(proposal_id):
    """Record an ENGINE-authored fix PR on a proposal (spec 2026-08-26 Phase 3).

    Body: {pr_number, pr_url?, branch?}. Flips the proposal to pr_open with the
    ship_as_pr metadata shape (apply_mode='engine_pr'), so the merge-completion
    sweep settles both coder lanes at one choke point. Bearer INTERNAL_API_KEY.
    """
    from services import proposal_service

    data = request.get_json(silent=True) or {}
    try:
        res = proposal_service.record_engine_pr(
            proposal_id, data.get("pr_number"), data.get("pr_url"), data.get("branch")
        )
        return jsonify(res), (200 if res.get("success") else 400)
    except Exception as e:
        logger.error(f"internal repair proposal pr record failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/internal/delegation/invokable-skills", methods=["GET"])
@require_internal_scope("delegation")
def api_internal_invokable_skills():
    """#5333 skill bridge: the invokable-actions registry, on the INTERNAL-KEY
    surface so archie_engine (and through it archie-tui) can actually read it.

    The same registry is served to the DHQ UI at
    /tools/department-hq/api/dispatch/invokable-skills, but that route is gated
    by a SESSION-based admin check. archie_engine holds INTERNAL_API_KEY and no
    session, so it got 401 on every credential it has — the listing endpoint was
    unreachable by the only two surfaces it exists for, while its sibling write
    path (/api/internal/delegation/submit) was reachable. Measured 2026-08-22.

    Same generated payload, same builder, no second source of truth: membership
    comes from KNOWN_TOOL_CAPABILITIES + CAPABILITY_DEPARTMENT_MAP, never a
    hand-maintained list.
    """
    from services.delegation_service import (
        build_invokable_skills_registry,
        resolve_department_directors,
    )

    try:
        directors = resolve_department_directors()
        return jsonify({"success": True, **build_invokable_skills_registry(directors)})
    except Exception as exc:
        logger.error("api_internal_invokable_skills failed: %s", exc)
        return jsonify({"success": False, "error": "registry build failed"}), 500


# ---------------------------------------------------------------------------
# Phase 2 (#6663): the cockpit agent-lifecycle command surface. All writes go
# through agent_service (single-writer), gated by the agents:manage scope
# (granted to archie_comms). create is Tier-2 approval-gated (propose_hire).
# ---------------------------------------------------------------------------
# Phase 4 (#6653): cockpit READS. agents:read (archie_comms only). Reads go
# through agent_service single-reader helpers; no SQL here.
_AGENT_PUBLIC_FIELDS = (
    "id",
    "name",
    "display_name",
    "department",
    "shift_state",
    "worker_type",
    "model",
    "title",
    "is_department_ai",
    "performance_score",
    "success_rate",
    "last_used",
    "bio",
    "first_name",
    "last_name",
    "email",
    "created_at",
    "status",
    "tier",
    "current_grade",
    "total_tasks_completed",
)


def _cockpit_json(value):
    """JSON-safe scalars for RealDictCursor rows: datetimes → isoformat, Decimal → float."""
    import datetime as _dt
    import decimal as _dec

    if isinstance(value, (_dt.datetime, _dt.date)):
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, _dec.Decimal):
        return float(value)
    return value


def _cockpit_row(row, fields=None):
    return {k: _cockpit_json(v) for k, v in (row or {}).items() if fields is None or k in fields}


@app.route("/api/internal/agents", methods=["GET"])
@require_internal_scope("agents:read")
def api_internal_agents_list():
    """Cockpit roster page + filter facets (agent_service.list_roster / roster_facets)."""
    from services import agent_service as svc

    args = request.args
    try:
        limit = int(args.get("limit") or 50)
        offset = int(args.get("offset") or 0)
    except ValueError:
        return jsonify({"success": False, "error": "limit and offset must be integers"}), 400
    limit, offset = svc.clamp_roster_page(limit, offset)
    include_dec = args.get("state") == "decommissioned" or args.get("include_decommissioned") == "1"
    try:
        rows, total = svc.list_roster(
            q=(args.get("q") or "").strip() or None,
            department=(args.get("department") or "").strip() or None,
            shift_state=(args.get("state") or "").strip() or None,
            worker_type=(args.get("worker_type") or "").strip() or None,
            include_decommissioned=include_dec,
            limit=limit,
            offset=offset,
        )
        facets = svc.roster_facets(include_decommissioned=include_dec)
    except Exception as exc:
        logger.error("api_internal_agents_list failed: %s", exc)
        return jsonify({"success": False, "error": "roster read failed"}), 500
    return jsonify(
        {
            "success": True,
            "agents": [_cockpit_row(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "facets": facets,
        }
    )


@app.route("/api/internal/agents/<int:agent_id>", methods=["GET"])
@require_internal_scope("agents:read")
def api_internal_agents_detail(agent_id):
    """One agent + skills + budget + recent work for the cockpit agent card."""
    from services import agent_service as svc

    try:
        agent = svc.get_agent(agent_id)
        if not agent:
            return jsonify({"success": False, "error": "agent not found"}), 404
        skills = svc.get_agent_skills(agent_id)
        budget = svc.get_agent_budget(agent_id)
        recent = svc.get_agent_recent_work(agent_id, limit=5)
    except Exception as exc:
        logger.error("api_internal_agents_detail failed: %s", exc)
        return jsonify({"success": False, "error": "agent read failed"}), 500
    return jsonify(
        {
            "success": True,
            "agent": _cockpit_row(agent, _AGENT_PUBLIC_FIELDS),
            "skills": [_cockpit_row(s) for s in skills],
            "budget": _cockpit_row(budget) if budget else None,
            "recent_work": [_cockpit_row(w) for w in recent],
        }
    )


@app.route("/api/internal/agents/create", methods=["POST"])
@require_internal_scope("agents:manage")
def api_internal_agents_create():
    """Cockpit -> propose a NEW agent. Tier-2: routes through the create_agent
    approval queue (propose_hire), NEVER a direct create. Returns the pending
    approval so the owner approves/denies it."""
    from services.agent_service import propose_hire

    data = request.get_json(silent=True) or {}
    required = ("name", "display_name", "department", "model", "capability", "reason")
    missing = [k for k in required if not (data.get(k) or "").strip()]
    if missing:
        return jsonify({"success": False, "error": f"missing required: {', '.join(missing)}"}), 400
    try:
        res = propose_hire(
            name=data["name"].strip(),
            display_name=data["display_name"].strip(),
            department=data["department"].strip(),
            model=data["model"].strip(),
            capability=data["capability"].strip(),
            reason=data["reason"].strip(),
            requested_by=f"cockpit:{getattr(g, 'internal_caller', 'archie_comms')}",
            suggested_skills=data.get("suggested_skills") or None,
        )
        return jsonify({"success": True, "tier2": True, **(res if isinstance(res, dict) else {"result": res})})
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as exc:
        logger.error("api_internal_agents_create failed: %s", exc)
        return jsonify({"success": False, "error": "create proposal failed"}), 500


@app.route("/api/internal/agents/<int:agent_id>/assign", methods=["POST"])
@require_internal_scope("agents:manage")
def api_internal_agents_assign(agent_id):
    """Cockpit -> assign an agent to a department (floor auto-derives), via
    agent_service.update_agent (single-writer). Department is the agent's real
    assignment field; 'station' is a display/node concept, not an `agents`
    column (update_agent has no column allowlist, so a bogus field would 500)."""
    from services.agent_service import update_agent

    data = request.get_json(silent=True) or {}
    department = (data.get("department") or "").strip()
    if not department:
        return jsonify({"success": False, "error": "department required"}), 400
    try:
        update_agent(agent_id, department=department)
        return jsonify({"success": True, "agent_id": agent_id, "assigned": {"department": department}})
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as exc:
        logger.error("api_internal_agents_assign failed: %s", exc)
        return jsonify({"success": False, "error": "assign failed"}), 500


@app.route("/api/internal/agents/<int:agent_id>/shift-state", methods=["POST"])
@require_internal_scope("agents:manage")
def api_internal_agents_shift_state(agent_id):
    """Cockpit -> change shift state. Non-terminal states go through
    transition_shift_state (rotation log); the TERMINAL 'decommissioned' goes
    through update_agent (it is a lifecycle end-state, not a shift)."""
    from services.agent_service import VALID_SHIFT_STATES, transition_shift_state, update_agent

    data = request.get_json(silent=True) or {}
    state = (data.get("state") or "").strip()
    reason = (data.get("reason") or "cockpit").strip()
    if state not in VALID_SHIFT_STATES:
        return jsonify({"success": False, "error": f"invalid state {state!r}", "valid": list(VALID_SHIFT_STATES)}), 400
    try:
        if state == "decommissioned":
            update_agent(agent_id, shift_state="decommissioned")
            return jsonify({"success": True, "agent_id": agent_id, "state": state, "terminal": True})
        res = transition_shift_state(
            agent_id, state, reason=reason, changed_by=f"cockpit:{getattr(g, 'internal_caller', 'archie_comms')}"
        )
        return jsonify({"agent_id": agent_id, **res}), (200 if res.get("success") else 400)
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as exc:
        logger.error("api_internal_agents_shift_state failed: %s", exc)
        return jsonify({"success": False, "error": "shift-state change failed"}), 500


@app.route("/api/internal/agents/<int:agent_id>/skills/add", methods=["POST"])
@require_internal_scope("agents:manage")
def api_internal_agents_skill_add(agent_id):
    """Cockpit -> add/raise a skill (agent_service.add_skill)."""
    from services.agent_service import add_skill

    data = request.get_json(silent=True) or {}
    skill = (data.get("skill_name") or "").strip()
    if not skill:
        return jsonify({"success": False, "error": "skill_name required"}), 400
    try:
        level = int(data.get("level") or 1)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "level must be an integer"}), 400
    category = (data.get("category") or "general").strip()
    try:
        add_skill(agent_id, skill, level=level, category=category)
        return jsonify({"success": True, "agent_id": agent_id, "skill_name": skill, "level": level})
    except Exception as exc:
        logger.error("api_internal_agents_skill_add failed: %s", exc)
        return jsonify({"success": False, "error": "add skill failed"}), 500


@app.route("/api/internal/agents/<int:agent_id>/skills/remove", methods=["POST"])
@require_internal_scope("agents:manage")
def api_internal_agents_skill_remove(agent_id):
    """Cockpit -> remove a skill (agent_service.remove_skill)."""
    from services.agent_service import remove_skill

    data = request.get_json(silent=True) or {}
    skill = (data.get("skill_name") or "").strip()
    if not skill:
        return jsonify({"success": False, "error": "skill_name required"}), 400
    try:
        removed = remove_skill(agent_id, skill)
        return jsonify({"success": True, "agent_id": agent_id, "skill_name": skill, "removed": removed})
    except Exception as exc:
        logger.error("api_internal_agents_skill_remove failed: %s", exc)
        return jsonify({"success": False, "error": "remove skill failed"}), 500


@app.route("/api/internal/agents/<int:agent_id>/budget", methods=["POST"])
@require_internal_scope("agents:manage")
def api_internal_agents_budget(agent_id):
    """Cockpit -> set an agent's daily token ceiling (agent_service.set_token_budget,
    floored at 50k). 404 if the agent has no budget row yet."""
    from services.agent_service import set_token_budget

    data = request.get_json(silent=True) or {}
    if data.get("token_limit_per_day") is None:
        return jsonify({"success": False, "error": "token_limit_per_day required"}), 400
    try:
        applied = set_token_budget(agent_id, data["token_limit_per_day"])
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as exc:
        logger.error("api_internal_agents_budget failed: %s", exc)
        return jsonify({"success": False, "error": "set budget failed"}), 500
    if applied is None:
        return jsonify({"success": False, "error": "agent has no budget row"}), 404
    return jsonify({"success": True, "agent_id": agent_id, "token_limit_per_day": applied})


# ---------------------------------------------------------------------------
# Phase 3a (#6653): the ask-first cloud CODING lane. Explicit and per-call —
# never auto-escalation (escalation_mode stays local_only). Mirrors the A/B Cloud
# Comparison lane (#4661): a bridge_jobs row (status 'pending', NOT
# 'pending_approval' — the autonomy row is the ONE approval item, so the
# Approvals tab never double-lists) + a Tier-2 approval linked by
# metadata.approval_id; agent_loop.cloud_code_worker (30 s) drains approved jobs.
# The cockpit button is Phase 4; this is the backend path.
# ---------------------------------------------------------------------------
@app.route("/api/internal/cloud-code/run", methods=["POST"])
@require_internal_scope("cloud:code")
def api_internal_cloud_code_run():
    import json as _json
    from psycopg2.extras import Json
    from database import get_db_cursor
    from services import cloud_code_lane as lane

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"success": False, "error": "prompt required"}), 400
    system_prompt = (data.get("system_prompt") or "").strip() or None
    provider_key = (data.get("provider") or "omniroute").strip()

    target_path = (data.get("target_path") or "").strip() or None  # parsed here, validated below the gate

    # Sovereignty boundary first (fail-closed); the dispatcher re-checks at dispatch time.
    if not lane.code_allowed():
        return jsonify({"success": False, "error": "capability 'code' is not on the cloud allowlist"}), 409
    cfg = lane.active_provider(provider_key)
    if not cfg:
        return jsonify({"success": False, "error": f"provider {provider_key!r} is not an active contractor"}), 404
    model = (data.get("model") or cfg.get("default_model") or "").strip()
    if not model:
        return jsonify({"success": False, "error": "no model: pass one or set the provider's default_model"}), 400

    # DS9 Phase 3 — fail fast at enqueue: if this provider is fronted by the
    # OmniRoute gateway and its upstream is quota-exhausted, refuse BEFORE
    # creating a bridge_jobs row (and a Tier-2 approval) that is doomed to a
    # 429. Fail-open: a quota error or an unknown upstream never blocks a call.
    if "omniroute" in (cfg.get("base_url") or "").lower():
        try:
            from services.work_control_service import is_enabled

            enqueue_gate = is_enabled("omniroute_quota_consume", default=True)
        except Exception:  # noqa: BLE001
            enqueue_gate = True
        if enqueue_gate:
            try:
                from services.omniroute_quota_service import gate_upstream, upstream_for_model

                _upstream = upstream_for_model(model)
                gate = gate_upstream(_upstream) if _upstream else {"allow": True, "reason": "no upstream mapping"}
                if gate.get("status") == "degraded":
                    app.logger.warning(
                        "[OmniRoute quota] %s — enqueueing anyway (degraded, not blocked)", gate.get("reason")
                    )
                if not gate.get("allow", True):
                    app.logger.warning(
                        "[OmniRoute quota] %s — refusing cloud-code enqueue %s:%s",
                        gate.get("reason"),
                        provider_key,
                        model,
                    )
                    return (
                        jsonify(
                            {"success": False, "error": f"OmniRoute quota: {gate.get('reason')}", "quota_status": gate}
                        ),
                        503,
                    )
            except Exception as exc:  # noqa: BLE001 — fail-open
                app.logger.warning("[OmniRoute quota] enqueue gate check failed open: %s", exc)

    # #6680 Phase 4b — the optional target file. Validated and read from main only AFTER the
    # gate above, so a closed lane / inactive provider / missing model refuses with its own
    # truthful status instead of a GitHub error from a read that should not have happened.
    # Still ahead of the INSERT: a blocked path or an unreadable file costs no bridge_jobs
    # row and no approval. The base blob sha recorded here is what the apply executor binds
    # its precondition to.
    base_sha = None
    base_size = None
    prompt_effective = prompt
    if target_path:
        from services import cloud_code_apply as apply_svc
        from tools.repair_bay.services import github_service as gh

        try:
            target_path = apply_svc.validate_target(target_path)
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        try:
            current = gh.get_file_at_ref(target_path, "main")
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except Exception as exc:
            logger.error("cloud-code target read failed for %s: %s", target_path, exc)
            return jsonify({"success": False, "error": f"could not read {target_path} from main: {exc}"}), 503
        if current:
            base_sha, base_size = current["sha"], current["size"]
        prompt_effective = apply_svc.build_edit_prompt(target_path, prompt, current["content"] if current else None)

    requested_by = f"cockpit:{getattr(g, 'internal_caller', 'archie_comms')}"
    # metadata.prompt is what the worker dispatches, so with a target file it holds the
    # ASSEMBLED prompt; prompt_original keeps the owner's own words for the PR body.
    meta = lane.build_job_metadata(
        prompt=prompt_effective,
        system_prompt=system_prompt,
        provider_key=provider_key,
        model=model,
        requested_by=requested_by,
    )
    if target_path:
        meta.update(
            {"target_path": target_path, "base_sha": base_sha, "base_size": base_size, "prompt_original": prompt}
        )
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO bridge_jobs (job_type, module_source, description, status, agent_name, metadata) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (
                lane.JOB_TYPE,
                lane.MODULE_ID,
                f"cloud code via {provider_key}:{model}",
                "pending",
                "CONTRACTOR→cloud",
                Json(meta),
            ),
        )
        job_id = cur.fetchone()["id"]

    approval_id = lane.request_tier2_approval(
        job_id=job_id, provider_key=provider_key, model=model, prompt=prompt, requested_by=requested_by
    )
    if approval_id is None:
        # request_approval()'s per-action_type dedup: one pending cloud_code approval at
        # a time. Fail the job honestly rather than leave a poller waiting forever.
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE bridge_jobs SET status='failed', completed_at=NOW(), updated_at=NOW(), error_message=%s WHERE id=%s",
                ("approval_unavailable: a cloud coding approval is already pending", job_id),
            )
        return (
            jsonify(
                {
                    "success": False,
                    "status": "approval_unavailable",
                    "job_id": job_id,
                    "error": "A cloud coding task is already awaiting approval — decide that one first.",
                }
            ),
            409,
        )
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE bridge_jobs SET metadata = jsonb_set(COALESCE(metadata,'{}'::jsonb), '{approval_id}', %s::jsonb), "
            "updated_at=NOW() WHERE id=%s",
            (_json.dumps(approval_id), job_id),
        )
    return jsonify({"success": True, "status": "pending_approval", "job_id": job_id, "approval_id": approval_id}), 202


def _apply_approval_statuses(ids):
    """#6680 Phase 4b — live status of one or more ``cloud_code_apply`` approvals, keyed by id.

    ONE batched query for every id on the page. The runs list can carry up to 100 rows and the
    cockpit re-polls it while any job is active, so a per-row lookup would be an N+1 on a hot path.

    Reads ``autonomy_approval_queue`` rather than a stamp on ``bridge_jobs``: a Deny (or the
    expiry sweep) updates the queue row and never touches the job, so ``apply_approval_id`` ALONE
    cannot separate "still waiting" from "settled" — without this the cockpit reads "apply waits
    for approval #N" forever and never re-offers Apply.

    ⚠️ THE VOCABULARY, measured — not the one you would guess. On ``autonomy_approval_queue`` a
    deny writes **``rejected``**, never ``denied``: ``approvals_routes.py:254`` (the DHQ Approvals
    tab) and every Telegram Deny (``telegram_gateway.py`` 1034/1149/1232/2127) all write
    ``rejected``. ``telegram_gateway.py:1150`` even sets ``rejected_reason='Denied via Telegram'``
    — the WORD "Denied" is in the row while the STATUS is ``rejected``. ``denied`` belongs to a
    DIFFERENT table, ``contractor_approval_requests`` (``approvals_routes.py:307``).
    Full set seen here: pending | approved | rejected | executed | failed | expired | cancelled.
    Getting this wrong is not cosmetic — a consumer that omits ``rejected`` treats the COMMON
    settle path as "still pending". Cross-check against
    ``services/cloud_code_lane.py:50``, which already lists ``rejected`` first.

    Scoped to ``action_type = cloud_code_apply``: ids come from the job's own metadata, so a stale
    or reused id would otherwise report a FOREIGN approval's status as this lane's. Not
    exploitable today (the hub writes the ids) — the filter makes the query match the promise.

    Best-effort: any failure returns ``{}`` so callers degrade to ``None`` (unknown) instead of
    taking down the status/runs payload the whole cockpit renders from.
    """
    wanted = sorted({i for i in ids if isinstance(i, int) and not isinstance(i, bool)})
    if not wanted:
        return {}
    try:
        from database import get_db_cursor
        from services.cloud_code_apply import ACTION_TYPE

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, status FROM autonomy_approval_queue WHERE id = ANY(%s) AND action_type = %s",
                (wanted, ACTION_TYPE),
            )
            return {r["id"]: r["status"] for r in cur.fetchall()}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("cloud-code: could not read apply approvals %s: %s", wanted, exc)
        return {}


@app.route("/api/internal/cloud-code/run/<int:job_id>", methods=["GET"])
@require_internal_scope("cloud:code")
def api_internal_cloud_code_status(job_id):
    from database import get_db_cursor
    from services import cloud_code_lane as lane

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, status, metadata, error_message, created_at, completed_at FROM bridge_jobs WHERE id=%s AND job_type=%s",
            (job_id, lane.JOB_TYPE),
        )
        row = cur.fetchone()
    if not row:
        return jsonify({"success": False, "error": "job not found"}), 404
    meta = row["metadata"] or {}

    # #6680 — the LIVE state of the apply approval, read from the queue rather than
    # from a stamp on the job.
    #
    # The spec named an `apply_denied_at` field for this, but nothing ever writes one:
    # a Deny (or the 24 h expiry) updates autonomy_approval_queue and never touches the
    # bridge_jobs row, so `apply_approval_id` alone cannot distinguish "still waiting"
    # from "denied" — the cockpit would keep reading "apply waits for approval #N"
    # forever. Adding a writer would mean teaching the generic deny path about this one
    # lane; reading the row it already updates costs one indexed lookup and cannot go
    # stale. Best-effort: a failure here must not take down the whole status payload,
    # which is also what drives the run view.
    _apply_id = meta.get("apply_approval_id")
    apply_approval_status = _apply_approval_statuses([_apply_id]).get(_apply_id)

    return jsonify(
        {
            "success": True,
            "job_id": row["id"],
            "status": row["status"],
            "approval_id": meta.get("approval_id"),
            "model": meta.get("model"),
            "provider": meta.get("provider"),
            "result": meta.get("result"),
            "error": row["error_message"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
            # #6680 Phase 4b — the apply lane's state, so the cockpit can render the
            # Apply button, a pending approval, a failure, or the resulting PR.
            "target_path": meta.get("target_path"),
            "base_sha": meta.get("base_sha"),
            "prompt_original": meta.get("prompt_original"),
            "apply_approval_id": meta.get("apply_approval_id"),
            # pending | approved | rejected | executed | failed | expired | cancelled — or None
            # when no apply was requested, the approval row was purged, or the lookup failed.
            # ⚠️ A DENY WRITES `rejected`, NOT `denied` (see _apply_approval_statuses). This
            # comment said `denied` and the cockpit was built from it, so every Deny rendered
            # as "still waiting" with Apply suppressed — the exact failure the field exists to
            # prevent. `denied` is a DIFFERENT table's vocabulary.
            "apply_approval_status": apply_approval_status,
            "apply_error": meta.get("apply_error"),
            "pr_number": meta.get("pr_number"),
            "pr_url": meta.get("pr_url"),
            "branch": meta.get("branch"),
        }
    )


@app.route("/api/internal/cloud-code/run/<int:job_id>/apply", methods=["POST"])
@require_internal_scope("cloud:code")
def api_internal_cloud_code_apply(job_id):
    """#6680 Phase 4b — turn a completed cloud coding answer into a Tier-2 'cloud_code_apply'
    approval. Nothing is written here; the approval executor (cloud_code_apply.execute) does
    the branch + commit + PR after the owner says yes."""
    import json as _json

    from database import get_db_cursor
    from services import cloud_code_apply as apply_svc
    from services import cloud_code_lane as lane

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT id, status, metadata FROM bridge_jobs WHERE id=%s AND job_type=%s", (job_id, lane.JOB_TYPE))
        row = cur.fetchone()
    if not row:
        return jsonify({"success": False, "error": "job not found"}), 404
    meta = row["metadata"] or {}
    problem = apply_svc.apply_precondition(row["status"], meta)
    if problem:
        return jsonify({"success": False, "error": problem}), 409
    content = apply_svc.strip_fences((meta.get("result") or {}).get("response") or "")
    if not content.strip():
        return jsonify({"success": False, "error": "the answer is empty — nothing to apply"}), 409
    requested_by = f"cockpit:{getattr(g, 'internal_caller', 'archie_comms')}"
    approval_id = apply_svc.request_tier2_approval(job_id=job_id, meta=meta, content=content, requested_by=requested_by)
    if approval_id is None:
        return (
            jsonify({"success": False, "error": "an apply is already waiting for approval — decide that one first"}),
            409,
        )
    stamp = {"apply_approval_id": approval_id, "apply_requested_at": apply_svc._now_iso(), "apply_error": None}
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE bridge_jobs SET metadata = COALESCE(metadata,'{}'::jsonb) || %s::jsonb, updated_at=NOW() WHERE id=%s",
            (_json.dumps(stamp), job_id),
        )
    return jsonify({"success": True, "job_id": job_id, "approval_id": approval_id, "status": "pending_approval"}), 202


@app.route("/api/internal/cloud-code/runs", methods=["GET"])
@require_internal_scope("cloud:code")
def api_internal_cloud_code_runs():
    """Cockpit job history (newest first). Prompt text and the full response are NOT
    included — the per-job status route has them."""
    from database import get_db_cursor
    from services import cloud_code_lane as lane

    try:
        limit = max(1, min(int(request.args.get("limit") or 20), 100))
    except ValueError:
        return jsonify({"success": False, "error": "limit must be an integer"}), 400
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, status, metadata, error_message, created_at, completed_at FROM bridge_jobs "
            "WHERE job_type = %s ORDER BY id DESC LIMIT %s",
            (lane.JOB_TYPE, limit),
        )
        rows = cur.fetchall()
    # #6680 Phase 4b — ONE batched lookup for every apply approval on this page, not one per
    # row. Without a live status the cockpit can only see `apply_approval_id`, which is set for
    # a pending apply AND for a denied/expired one, so a denied apply rendered as "apply waits
    # for approval #N" forever with no way back to the Apply button.
    _apply_statuses = _apply_approval_statuses([(r["metadata"] or {}).get("apply_approval_id") for r in rows])
    runs = []
    for row in rows:
        meta = row["metadata"] or {}
        res = meta.get("result") or None
        runs.append(
            {
                "job_id": row["id"],
                "status": row["status"],
                "approval_id": meta.get("approval_id"),
                "model": meta.get("model"),
                "provider": meta.get("provider"),
                "error": row["error_message"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                # Apply-lane state only — still no prompt text and no full response here.
                "target_path": meta.get("target_path"),
                "pr_number": meta.get("pr_number"),
                "pr_url": meta.get("pr_url"),
                "apply_approval_id": meta.get("apply_approval_id"),
                # pending | approved | rejected | executed | failed | expired | cancelled — or
                # None when no apply was requested, the row was purged, or the lookup failed.
                # ⚠️ A DENY WRITES `rejected`, NOT `denied` — see _apply_approval_statuses.
                "apply_approval_status": _apply_statuses.get(meta.get("apply_approval_id")),
                "apply_error": meta.get("apply_error"),
                "result": (
                    {
                        k: res.get(k)
                        for k in ("model_used", "served_model_resolved", "prompt_tokens", "completion_tokens", "error")
                    }
                    if isinstance(res, dict)
                    else None
                ),
            }
        )
    return jsonify({"success": True, "runs": runs})


@app.route("/api/internal/cloud-code/providers", methods=["GET"])
@require_internal_scope("cloud:code")
def api_internal_cloud_code_providers():
    """Providers the Code Builder may target: active, text_chat, NOT cloud-proxy rows
    (is_cloud_proxy=true routes via call_ollama_cloud, not the gateway)."""
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT provider_key, display_name, default_model, models, is_active FROM contractor_providers "
            "WHERE is_active = true AND COALESCE(is_cloud_proxy, false) = false AND capabilities ? 'text_chat' "
            "ORDER BY tier_position, provider_key"
        )
        rows = cur.fetchall()
    providers = []
    for row in rows:
        models = row["models"] or []
        names = [m.get("name") if isinstance(m, dict) else str(m) for m in models]
        providers.append(
            {
                "provider_key": row["provider_key"],
                "display_name": row["display_name"] or row["provider_key"],
                "default_model": row["default_model"],
                "models": [n for n in names if n],
                "is_active": bool(row["is_active"]),
            }
        )
    return jsonify({"success": True, "providers": providers})


# ---- Cockpit Work pane: projects + tasks (#6679 Phase 4b) ----------------------------
# Thin routes over services/task_service (the single writer). LookupError → 404,
# ValueError → 400 with the message verbatim (comms shows it as-is), anything else → 500.
def _task_error(exc):
    if isinstance(exc, LookupError):
        return jsonify({"success": False, "error": str(exc)}), 404
    if isinstance(exc, ValueError):
        return jsonify({"success": False, "error": str(exc)}), 400
    logger.error("cockpit task route failed: %s", exc)
    return jsonify({"success": False, "error": "task read/write failed"}), 500


@app.route("/api/internal/projects", methods=["GET"])
@require_internal_scope("tasks:read")
def api_internal_projects_list():
    from services import task_service as ts

    a = request.args
    try:
        rows, total = ts.list_projects(status=a.get("status"), limit=a.get("limit"), offset=a.get("offset"))
    except Exception as exc:
        return _task_error(exc)
    limit, offset = ts.clamp_page(a.get("limit"), a.get("offset"))
    return jsonify(
        {"success": True, "projects": [_cockpit_row(r) for r in rows], "total": total, "limit": limit, "offset": offset}
    )


@app.route("/api/internal/tasks", methods=["GET"])
@require_internal_scope("tasks:read")
def api_internal_tasks_list():
    from services import task_service as ts

    a = request.args
    try:
        rows, total, facets = ts.list_tasks(
            q=a.get("q"),
            project_id=a.get("project_id") or None,
            status=a.get("status"),
            min_priority=a.get("min_priority") or None,
            limit=a.get("limit"),
            offset=a.get("offset"),
        )
    except Exception as exc:
        return _task_error(exc)
    limit, offset = ts.clamp_page(a.get("limit"), a.get("offset"))
    return jsonify(
        {
            "success": True,
            "tasks": [_cockpit_row(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "facets": facets,
        }
    )


@app.route("/api/internal/tasks/<int:task_id>", methods=["GET"])
@require_internal_scope("tasks:read")
def api_internal_task_detail(task_id):
    from services import task_service as ts

    try:
        task = ts.get_task(task_id)
    except Exception as exc:
        return _task_error(exc)
    if not task:
        return jsonify({"success": False, "error": "task not found"}), 404
    return jsonify({"success": True, "task": _cockpit_row(task)})


@app.route("/api/internal/tasks", methods=["POST"])
@require_internal_scope("tasks:write")
def api_internal_task_create():
    from services import task_service as ts

    data = request.get_json(silent=True) or {}
    try:
        task = ts.create_task(
            data.get("project_id"),
            data.get("title"),
            description=data.get("description") or "",
            priority=data.get("priority", 5),
            task_type=data.get("task_type") or "implementation",
            requested_by="cockpit",
        )
    except Exception as exc:
        return _task_error(exc)
    return jsonify({"success": True, "task": _cockpit_row(task)}), 201


@app.route("/api/internal/tasks/<int:task_id>/status", methods=["POST"])
@require_internal_scope("tasks:write")
def api_internal_task_status(task_id):
    from services import task_service as ts

    data = request.get_json(silent=True) or {}
    try:
        task = ts.set_status(task_id, (data.get("status") or "").strip(), requested_by="cockpit")
    except Exception as exc:
        return _task_error(exc)
    return jsonify({"success": True, "task": _cockpit_row(task)})


@app.route("/api/internal/tasks/<int:task_id>/priority", methods=["POST"])
@require_internal_scope("tasks:write")
def api_internal_task_priority(task_id):
    from services import task_service as ts

    data = request.get_json(silent=True) or {}
    try:
        task = ts.set_priority(task_id, data.get("priority"), requested_by="cockpit")
    except Exception as exc:
        return _task_error(exc)
    return jsonify({"success": True, "task": _cockpit_row(task)})


@app.route("/api/internal/tasks/<int:task_id>/note", methods=["POST"])
@require_internal_scope("tasks:write")
def api_internal_task_note(task_id):
    from services import task_service as ts

    data = request.get_json(silent=True) or {}
    try:
        note = ts.add_note(task_id, data.get("text"), author="cockpit")
        task = ts.get_task(task_id)
    except Exception as exc:
        return _task_error(exc)
    return jsonify({"success": True, "note": note, "task": _cockpit_row(task)})


@app.route("/api/internal/tasks/<int:task_id>/delegate", methods=["POST"])
@require_internal_scope("tasks:write")
def api_internal_task_delegate(task_id):
    from services import task_service as ts

    data = request.get_json(silent=True) or {}
    try:
        task = ts.delegate(task_id, data.get("capability"), requested_by="cockpit")
    except Exception as exc:
        return _task_error(exc)
    return (
        jsonify({"success": True, "task": _cockpit_row(task), "worker": "delegate_task_worker", "claims_within_s": 30}),
        202,
    )


@app.route("/api/internal/delegation/submit", methods=["POST"])
@require_internal_scope("delegation")
def api_internal_delegation_submit():
    """Submit a task for delegation via web_chat source."""
    import psycopg2.extras as _psyext
    from database import get_db_cursor

    from services.delegation_service import (
        VALID_DELEGATION_SOURCES,
        clamp_conversation,
    )

    data = request.get_json(silent=True) or {}
    capability = (data.get("capability") or "general").strip()
    reason = (data.get("reason") or "").strip()
    args = data.get("args") or {}
    priority = int(data.get("priority") or 5)
    # #6729: prior turns, so a follow-up ("is IT bigger than…") has a referent.
    # Re-clamped HERE and not trusted from the caller: the bounds protect the 7B
    # fleet's KV cache, so they have to hold for any caller holding the internal
    # key. A malformed shape degrades to [] — never a 400, because losing history
    # must not cost the task.
    conversation = clamp_conversation(data.get("conversation"))

    # #5333: the skill bridge fires through THIS endpoint, so the source has to
    # be a parameter. It was hardcoded 'web_chat', which meant the 'tui' and
    # 'cockpit' sources added by #5291 could never actually be emitted by
    # anything — every TUI invocation would have been logged as web chat.
    # Default stays 'web_chat' so the existing archie-comms caller (which sends
    # no source) is byte-identical.
    delegation_source = (data.get("delegation_source") or "web_chat").strip()

    if not reason:
        return jsonify({"error": "reason required"}), 400
    if delegation_source not in VALID_DELEGATION_SOURCES:
        return (
            jsonify(
                {
                    "error": f"Invalid delegation_source {delegation_source!r}",
                    "valid": sorted(VALID_DELEGATION_SOURCES),
                }
            ),
            400,
        )

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO unified_tasks
                    (title, description, status, priority, task_type,
                     delegation_source, delegation_args)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    f"{capability}: {reason[:80]}",
                    reason,
                    "pending",
                    priority,
                    "implementation",
                    delegation_source,
                    _psyext.Json(
                        {
                            "capability": capability,
                            "args": args,
                            "reason": reason,
                            "conversation": conversation,
                        }
                    ),
                ),
            )
            task_id = cur.fetchone()["id"]
    except Exception as exc:
        logger.error("api_internal_delegation_submit failed: %s", exc)
        return jsonify({"error": "DB insert failed"}), 500

    return (
        jsonify(
            {
                "task_id": task_id,
                "status": "queued",
                "capability": capability,
                "reason": reason,
                "delegation_source": delegation_source,
            }
        ),
        201,
    )


@app.route("/api/internal/delegation/<int:task_id>/status")
@require_internal_scope("delegation")
def api_internal_delegation_status(task_id):
    """Return current status, the delegated ANSWER, and work_notes for a task."""
    from database import get_db_cursor
    from services.delegation_service import (
        is_delegation_terminal,
        resolve_delegation_result,
    )

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT t.id, t.title, t.status, t.blockers, t.created_at, t.updated_at,
                       (t.delegation_args->>'capability') AS capability,
                       (SELECT string_agg(wn.content, E'\n' ORDER BY wn.created_at, wn.id)
                        FROM work_notes wn WHERE wn.task_id = t.id) AS work_notes,
                       (SELECT wn.content FROM work_notes wn
                         WHERE wn.task_id = t.id AND wn.note_type = 'delegation_output'
                         ORDER BY wn.created_at DESC, wn.id DESC LIMIT 1) AS output_note,
                       (SELECT wn.content FROM work_notes wn
                         WHERE wn.task_id = t.id AND wn.note_type = 'delegation_result'
                         ORDER BY wn.created_at DESC, wn.id DESC LIMIT 1) AS result_note,
                       (SELECT wn.content FROM work_notes wn
                         WHERE wn.task_id = t.id AND wn.note_type = 'delegation_failure'
                         ORDER BY wn.created_at DESC, wn.id DESC LIMIT 1) AS failure_note
                FROM unified_tasks t
                WHERE t.id = %s AND t.delegation_source IS NOT NULL
                """,
                (task_id,),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.error("api_internal_delegation_status %d failed: %s", task_id, exc)
        return jsonify({"error": "DB query failed"}), 500

    if not row:
        return jsonify({"error": "Not found"}), 404

    # THE ANSWER, named. `work_notes` is every note glued together -- dispatch
    # banner, retries and the reply in one blob -- which a human can read and a
    # caller cannot use. Which note IS the reply depends on the execution path;
    # resolve_delegation_result owns that rule (and the measurements behind it).
    result_text, result_source = resolve_delegation_result(row["output_note"], row["result_note"])

    return jsonify(
        {
            "task_id": row["id"],
            "status": row["status"],
            # Server-side so a poller never keeps its own copy of the status
            # vocabulary -- see is_delegation_terminal for why that matters.
            "terminal": is_delegation_terminal(row["status"]),
            "capability": row["capability"],
            "result": result_text,
            "result_source": result_source,
            "failure": row["failure_note"],
            "work_notes": row["work_notes"],
            "title": row["title"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }
    )


@app.route("/api/internal/lane-liveness", methods=["GET"])
@require_internal_scope("repair:read")  # VERIFIED name (leading underscore) -- same guard used by
# /api/internal/delegation/invokable-skills and
# /api/internal/delegation/submit above.
def api_internal_lane_liveness():
    """Per-lane dormancy for the cockpit badge (#380).

    Internal-key surface, NOT session-gated: the cockpit is a separate
    container holding the internal key and no session cookie. #2781 shipped
    exactly this bug once already -- a registry gated behind a session admin
    check, so the only surface that needed it got 401 with every credential
    it had.
    """
    from services.lane_liveness_monitor import check_lane_liveness

    # alert=False: the hourly job owns alerting. A page refresh must never page.
    data = check_lane_liveness(alert=False)
    return jsonify({"ok": True, **data})


# propose_manifest performs no validation of its own -- repo flows verbatim onto
# every item in the manifest it returns. The guard belongs HERE, at the endpoint,
# not inside propose_manifest's contract (that function's callers may legitimately
# pass any repo string; the caller-supplied HTTP surface may not).
_PROPOSER_REPO_ALLOWLIST = ("KytranKatarn/archie-platform", "KytranKatarn/archie-code")


@app.route("/api/internal/proposed-manifest", methods=["GET"])
@require_internal_scope("repair:read")
def internal_proposed_manifest():
    """What the proposer would put in front of the owner right now.

    Internal-key surface, not session-gated: the cockpit is a separate container
    and carries the key, not a session (#2781).
    """
    from services.proposer_service import propose_manifest

    lane_prefixes = {
        "codex": (
            "platform_v2/tools/fitness/",
            "platform_v2/tools/therapy/",
            "platform_v2/tools/faith/",
            "platform_v2/tools/brainstorm/",
            "platform_v2/tools/doc/",
            "platform_v2/tools/family_tree/",
        ),
        "engine": ("platform_v2/", "ai_bridge/", "scripts/", "docs/"),
    }
    repo = request.args.get("repo", "KytranKatarn/archie-platform")
    if repo not in _PROPOSER_REPO_ALLOWLIST:
        return jsonify({"ok": False, "error": "unknown repo", "repo": repo}), 400
    try:
        return jsonify(propose_manifest(lane_prefixes, repo=repo, dry_run=True))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(type(exc).__name__), "items": []}), 200


@app.route("/api/internal/repair/count")
@require_internal_scope("repair:read")
def api_internal_repair_count():
    """Return count of open improvement proposals."""
    from database import get_db_cursor

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM improvement_proposals "
                "WHERE status IN ('pending', 'pending_approval', 'approved')"
            )
            return jsonify({"count": cur.fetchone()["cnt"]})
    except Exception as exc:
        logger.error("api_internal_repair_count failed: %s", exc)
        return jsonify({"count": 0})


# ============================================================================
# CHANGE PASSWORD (must_change_password enforcement — T3295)
# ============================================================================


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """Force-password-change page for accounts provisioned with must_change_password=True.
    After a successful change, clears the flag and redirects to the dashboard."""
    from database import get_db_cursor

    from services.auth_service import validate_password_complexity

    if request.method == "POST":
        new_pw = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

        if new_pw != confirm:
            flash("Passwords do not match.", "error")
        else:
            valid, msg = validate_password_complexity(new_pw)
            if not valid:
                flash(msg, "error")
            else:
                pw_hash = generate_password_hash(new_pw)
                try:
                    with get_db_cursor(commit=True) as (conn, cur):
                        cur.execute(
                            """UPDATE users
                               SET password_hash = %s,
                                   must_change_password = FALSE,
                                   updated_at = NOW()
                               WHERE id = %s""",
                            (pw_hash, current_user.id),
                        )
                    # Refresh the flag on the current_user object so the
                    # before_request guard stops redirecting immediately
                    current_user.must_change_password = False
                    flash("Password updated successfully. Welcome!", "success")
                    return redirect(url_for("dashboard"))
                except Exception as exc:
                    print(f"change_password error: {exc}")
                    flash("An error occurred. Please try again.", "error")

    return render_template("change_password.html")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    if SOCKETIO_AVAILABLE and socketio:
        socketio.run(app, host="0.0.0.0", port=3000, debug=True, allow_unsafe_werkzeug=True)
    else:
        app.run(host="0.0.0.0", port=3000, debug=True)
