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
from datetime import datetime, timedelta
import os
import time
import json
import secrets
from config import Config
from services import nav_service


# Custom JSON encoder for datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            # Append 'Z' for naive (UTC) datetimes so browsers parse correctly
            iso = obj.isoformat()
            if obj.tzinfo is None:
                iso += "Z"
            return iso
        return super().default(obj)


# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB upload limit
app.config["PREFERRED_URL_SCHEME"] = "https"  # Behind NPM SSL proxy

# Tell Flask it's behind a reverse proxy (NPM) so url_for generates https://
from werkzeug.middleware.proxy_fix import ProxyFix

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.json_encoder = DateTimeEncoder

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
        cur.execute(
            """INSERT INTO active_sessions
               (user_id, session_token, ip_address, user_agent,
                created_at, last_activity, expires_at)
               VALUES (%s, %s, %s, %s, NOW(), NOW(),
                NOW() + INTERVAL '24 hours')""",
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
                )
                login_user(user, remember=True)
                create_user_session(user_data["id"])

                log_auth_event(user_data["id"], "login_success", ip, ua)
                reset_failed_login_count(user_data["id"])

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
    """User signup page with admin approval"""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # Validation
        if not username or not email or not password:
            flash("All fields are required", "error")
            return render_template("signup.html")

        if password != confirm_password:
            flash("Passwords do not match", "error")
            return render_template("signup.html")

        from services.auth_service import validate_password_complexity

        pw_valid, pw_error = validate_password_complexity(password)
        if not pw_valid:
            flash(pw_error, "error")
            return render_template("signup.html")

        # Validate username (alphanumeric only)
        if not username.replace("_", "").isalnum():
            flash("Username must be alphanumeric (underscores allowed)", "error")
            return render_template("signup.html")

        try:
            from services.auth_service import (
                check_username_exists,
                check_email_exists,
                create_inactive_user,
                log_signup_audit,
            )

            if check_username_exists(username):
                flash("Username already exists", "error")
                return render_template("signup.html")

            if check_email_exists(email):
                flash("Email already registered", "error")
                return render_template("signup.html")

            password_hash = generate_password_hash(password)
            user_id = create_inactive_user(username, email, password_hash)
            log_signup_audit(username, request.remote_addr)

            # Auto-activate Explorer accounts (free tier, instant access)
            if user_id:
                try:
                    from database import get_db_cursor

                    with get_db_cursor() as (conn, cur):
                        cur.execute(
                            """UPDATE users
                               SET is_active = TRUE,
                                   subscription_tier = 'explorer'
                               WHERE id = %s""",
                            (user_id,),
                        )
                except Exception:
                    logger.warning("Auto-activate failed for user %s", user_id)

            flash(
                "Welcome to A.R.C.H.I.E.! Your Explorer account is ready — log in to get started.",
                "success",
            )
            return redirect(url_for("login"))

        except Exception as e:
            print(f"Signup error: {e}")
            flash("An error occurred. Please try again.", "error")

    return render_template("signup.html")


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
            SELECT a.name AS agent_name, a.model, bs.station_code, a.status
            FROM bridge_stations bs
            JOIN station_assignments sa ON bs.id = sa.station_id AND sa.is_active = TRUE
            JOIN agents a ON sa.agent_id = a.id AND a.status = 'active'
            WHERE bs.is_active = TRUE AND %s = ANY(bs.modules)
            ORDER BY sa.priority
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
            "updated_at": datetime.utcnow().isoformat() + "Z",
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

# OAuth authentication (Phase 6.5 - User Management & Subscription System)
from oauth_routes import oauth_bp, init_oauth  # noqa: E402
from services.git_commit_poller import start_poller  # noqa: E402
from conversation_triage.routes import triage_bp  # noqa: E402

# Initialize OAuth (Phase 6.5)
init_oauth(app)
logger.info("OAuth initialized with Google provider")

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

# Register additional blueprints
# Note: app_builder_bp, archie_chat_bp, consciousness_bp, backup_manager_bp, repair_bay_bp loaded via module_registry
# app.register_blueprint(github_bp)  # Disabled — Task #1986
app.register_blueprint(sandbox_bp)  # Sandbox environment for testing proposals
app.register_blueprint(cursor_bp)  # Cursor IDE integration API
app.register_blueprint(triage_bp)  # Phase 42: Conversation triage pipeline
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
            from ai_bridge.voice_synthesis import KokoroEngine

            if KokoroEngine.check_available():
                engine = KokoroEngine()
                engine._get_pipeline("af_heart")  # Load American English pipeline
                logger.info("Kokoro TTS pipeline warmed up successfully")
            else:
                logger.info("Kokoro TTS not available, skipping warmup")
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

    # Build load list: infrastructure first, then agent models by dispatch priority
    models_to_load = []
    for m in infra_models:
        endpoint = "embed" if "embed" in m else "generate"
        models_to_load.append((m, endpoint))
    for m in agent_models_ordered:
        if m not in infra_models:
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
            # MAX_LOADED_MODELS=3 bounds GPU pressure.
            if endpoint == "embed":
                for attempt in range(3):
                    try:
                        data = {"model": model_name, "input": "warmup", "keep_alive": "5m"}
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

                # Check AI Bridge
                try:
                    from ai_bridge.archie_bridge import archie_bridge as _ab

                    status = "online" if _ab else "unknown"
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
# SANDBOX MODE CONTEXT PROCESSOR
# ============================================================================


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
        g._nav_shortcuts_cached = shortcuts
        return {"header_shortcuts": shortcuts}
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
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"Unified alerts error: {e}")
        return jsonify(
            {
                "success": True,
                "critical": [],
                "categories": {},
                "counts": {"total": 0, "unread": 0, "critical": 0},
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

    now = datetime.utcnow()
    stardate = f"{now.year}.{now.strftime('%j')}"
    return render_template("competitors.html", stardate=stardate)


@app.route("/products/system-operations")
def product_system_operations():
    """Public product page for Kytran System Operations."""
    return render_template("products/system_operations.html")


@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors — also catches blocked domain requests from AdGuard DNS."""
    host = request.host.split(":")[0] if request.host else ""
    if host and host != "192.168.1.200" and host != "localhost" and not host.endswith("kytranempowerment.com"):
        return render_template("block_page.html", domain=host), 200
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
                    now = datetime.datetime.utcnow()
                    updated_at = training["updated_at"]
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
                    now = datetime.datetime.utcnow()
                    hours_resting = (now - rest["started_at"]).total_seconds() / 3600.0

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
        if _tg_token:
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


# ── Internal Delegation API (Sub-C #2351) ──────────────────────────
import os as _os_delegation
from functools import wraps as _wraps_delegation


def _require_internal_key(f):
    """Protect internal endpoints with INTERNAL_API_KEY bearer token."""

    @_wraps_delegation(f)
    def decorated(*args, **kwargs):
        _key = _os_delegation.getenv("INTERNAL_API_KEY", "")
        _auth = request.headers.get("Authorization", "")
        if not _key or _auth != f"Bearer {_key}":
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)

    return decorated


@app.route("/api/internal/delegation/submit", methods=["POST"])
@_require_internal_key
def api_internal_delegation_submit():
    """Submit a task for delegation via web_chat source."""
    import psycopg2.extras as _psyext
    from database import get_db_cursor

    data = request.get_json(silent=True) or {}
    capability = (data.get("capability") or "general").strip()
    reason = (data.get("reason") or "").strip()
    args = data.get("args") or {}
    priority = int(data.get("priority") or 5)

    if not reason:
        return jsonify({"error": "reason required"}), 400

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
                    "web_chat",
                    _psyext.Json({"capability": capability, "args": args}),
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
            }
        ),
        201,
    )


@app.route("/api/internal/delegation/<int:task_id>/status")
@_require_internal_key
def api_internal_delegation_status(task_id):
    """Return current status and work_notes for a delegated task."""
    from database import get_db_cursor

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT t.id, t.title, t.status, t.blockers, t.created_at, t.updated_at,
                       (t.delegation_args->>'capability') AS capability,
                       (SELECT string_agg(wn.content, E'\n' ORDER BY wn.created_at)
                        FROM work_notes wn WHERE wn.task_id = t.id) AS work_notes
                FROM unified_tasks t
                WHERE t.id = %s AND t.delegation_source = 'web_chat'
                """,
                (task_id,),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.error("api_internal_delegation_status %d failed: %s", task_id, exc)
        return jsonify({"error": "DB query failed"}), 500

    if not row:
        return jsonify({"error": "Not found"}), 404

    return jsonify(
        {
            "task_id": row["id"],
            "status": row["status"],
            "capability": row["capability"],
            "work_notes": row["work_notes"],
            "title": row["title"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }
    )


@app.route("/api/internal/repair/count")
@_require_internal_key
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
# MAIN
# ============================================================================

if __name__ == "__main__":
    if SOCKETIO_AVAILABLE and socketio:
        socketio.run(app, host="0.0.0.0", port=3000, debug=True, allow_unsafe_werkzeug=True)
    else:
        app.run(host="0.0.0.0", port=3000, debug=True)
