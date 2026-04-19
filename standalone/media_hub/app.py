"""
Media Hub Standalone Entrypoint
===============================
30-line Flask app that mounts tools.media_hub as the entire product.
When the ARCHIE platform runs Media Hub, it mounts the same blueprint
alongside 27 others. This app exists so the same code runs as its own
Docker container (Project #273).
"""

import logging
import os

from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user
from werkzeug.middleware.proxy_fix import ProxyFix

# tools.media_hub imports `from database import get_db_cursor`. Our standalone
# /app/database.py (DATABASE_URL-backed) sits on sys.path first — see Dockerfile.
from tools.media_hub import media_hub_bp  # noqa: E402

from auth_routes import auth_bp  # noqa: E402
from users import bootstrap_admin_if_empty, load_user  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("media_hub.standalone")


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.config["SECRET_KEY"] = os.environ["MEDIA_HUB_SECRET_KEY"]

    # NPM terminates TLS one hop in front of us — trust its X-Forwarded-* so
    # get_remote_address() returns the real client IP for rate limiting,
    # auth_events, and anything else that keys on IP.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Rate limiter — default bucket is disabled; we apply limits per-endpoint.
    # Storage is in-process memory (fine for a single gunicorn worker stack;
    # if we scale out, swap to redis:// via MEDIA_HUB_RATELIMIT_URI).
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=[],
        storage_uri=os.getenv("MEDIA_HUB_RATELIMIT_URI", "memory://"),
        strategy="fixed-window",
    )

    lm = LoginManager()
    lm.login_view = "auth.login"
    lm.init_app(app)
    lm.user_loader(load_user)

    from user_routes import user_mgmt_bp  # noqa: E402

    app.register_blueprint(auth_bp)
    app.register_blueprint(user_mgmt_bp)
    app.register_blueprint(media_hub_bp)

    # Gate /login after registration. Flask stores the dispatch target in
    # app.view_functions — decorating with limiter.limit returns a new fn,
    # so we have to reassign it back or the limit never fires.
    app.view_functions["auth.login"] = limiter.limit("10 per minute; 30 per hour")(
        app.view_functions["auth.login"]
    )

    # Create admin from MEDIA_HUB_ADMIN_PASSWORD if users table is empty.
    with app.app_context():
        try:
            bootstrap_admin_if_empty()
        except Exception as e:
            log.warning("bootstrap_admin skipped: %s", e)

    @app.route("/")
    def root():
        # Anonymous visitors see the public landing. Authenticated users skip
        # straight to the library — standard PWA home-screen launch behaviour.
        if current_user.is_authenticated:
            return redirect(url_for("media_hub.index"))
        return render_template("landing.html")

    @app.route("/agent")
    def agent_stub():
        """Placeholder for M.A.V.E.N. — Media Archive & Viewing Experience
        Navigator. Repurposed from the retired Maven librarian role in the
        A.R.C.H.I.E. roster (platform agents table id=27, active News & Media
        / CREATIVE). Wiring to inference is Tier 2."""
        return (
            jsonify(
                {
                    "status": "not_implemented",
                    "name": "M.A.V.E.N.",
                    "expansion": "Media Archive & Viewing Experience Navigator",
                    "archetype": "Same pattern as F.O.R.G.E., V.I.G.I.L., P.R.O.B.E.",
                    "capabilities": [
                        "conversational_search",
                        "recommendation",
                        "library_curation",
                        "upgrade_scanning",
                        "collection_generation",
                        "duplicate_triage",
                        "family_profiles",
                    ],
                    "tracking": "Project #273 Tier 2",
                }
            ),
            501,
        )

    @app.after_request
    def _no_store(resp):
        # While the standalone is brand-new, stale negative caches from the
        # pre-#169 period (when /static/css/media-hub.css 404'd) can persist
        # in user browsers for hours. Force revalidation until Media Hub is
        # stable enough to switch to sensible long-cache-with-hash URLs.
        path = request.path or ""
        if path.startswith("/static/") or path.startswith("/tools/media-hub/"):
            resp.headers["Cache-Control"] = "no-cache, must-revalidate, max-age=0"
            resp.headers["Pragma"] = "no-cache"
        return resp

    @app.route("/health")
    def health():
        return {"status": "ok", "mode": "standalone", "product": "media_hub"}, 200

    # Platform-only API stubs — media-hub.js probes these on every page load.
    # Returning empty JSON (200) is cleaner than letting the JS fetch land a 404
    # in the console for family members who open devtools.
    @app.route("/api/alerts/unified")
    def _stub_alerts_unified():
        return {"alerts": [], "count": 0}, 200

    @app.route("/tools/department-hq/api/dispatch/ops-summary")
    def _stub_dispatch_ops_summary():
        return {"status": "standalone", "dispatches": []}, 200

    log.info("Media Hub standalone app ready on blueprint %s", media_hub_bp.url_prefix)
    return app


app = create_app()
