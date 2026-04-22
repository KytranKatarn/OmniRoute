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
from flask_login import LoginManager, current_user, login_user
from werkzeug.middleware.proxy_fix import ProxyFix

# tools.media_hub imports `from database import get_db_cursor`. Our standalone
# /app/database.py (DATABASE_URL-backed) sits on sys.path first — see Dockerfile.
from tools.media_hub import media_hub_bp  # noqa: E402

from auth_routes import auth_bp  # noqa: E402
from kytran_auth import KytranAuth  # noqa: E402
from users import bootstrap_admin_if_empty, load_user, upsert_sso_user  # noqa: E402

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

    # Kytran SSO — registers /auth/kytran/login + /auth/kytran/callback.
    # Entitlement enforcement disabled by default for Media Hub (family access);
    # access policy lives in the on_login callback below.
    kytran_auth = KytranAuth()
    kytran_auth.init_app(app)

    # Dynamic OAuth client per hostname. Same pattern as archie-comms and KSO:
    # browser session cookies don't cross host boundaries, so the redirect_uri
    # must match the host the user actually started on — otherwise the
    # oauth_state stored in the session on host A disappears when the hub
    # redirects the browser back to host B, and the callback sees
    # "Invalid state parameter". Public HTTPS and LAN HTTP are separate
    # oauth_clients rows on the hub IdP.
    @app.before_request
    def _select_oauth_client_by_host():
        host = (request.host or "").lower()
        if host.startswith("192.168.") or host.startswith("127.") or host.startswith("localhost"):
            kytran_auth.client_id = os.getenv(
                "KYTRAN_CLIENT_ID_LAN", "media-hub-viewer-lan"
            )
            kytran_auth.client_secret = os.getenv(
                "KYTRAN_CLIENT_SECRET_LAN", ""
            )
            kytran_auth.redirect_uri = os.getenv(
                "KYTRAN_REDIRECT_URI_LAN",
                "http://192.168.1.200:8105/auth/kytran/callback",
            )
        else:
            kytran_auth.client_id = os.getenv(
                "KYTRAN_CLIENT_ID", "media-hub-viewer"
            )
            kytran_auth.client_secret = os.getenv(
                "KYTRAN_CLIENT_SECRET", ""
            )
            kytran_auth.redirect_uri = os.getenv(
                "KYTRAN_REDIRECT_URI",
                "https://media.kytranempowerment.com/auth/kytran/callback",
            )

    @kytran_auth.on_login
    def _on_sso_login(user_data):
        """Bridge Kytran SSO → flask_login session.

        Upsert a media_hub_users row keyed on sso_sub, then log the resulting
        User in so the existing @login_required decorators, session['_user_id'],
        and `current_user` all work identically to a local-password login.
        Admin role flows through (see users.upsert_sso_user) — everyone else
        gets a regular viewer account.
        """
        user = upsert_sso_user(user_data)
        if user and user.is_active:
            login_user(user)
            log.info("SSO login: %s (sso_sub=%s, admin=%s)",
                     user.username, user.sso_sub, user.is_admin)
        else:
            log.warning("SSO login rejected (upsert failed or user inactive): %s",
                        user_data.get("sub"))

    from user_routes import user_mgmt_bp  # noqa: E402

    app.register_blueprint(auth_bp)
    app.register_blueprint(user_mgmt_bp)
    app.register_blueprint(media_hub_bp)

    # Jinja flag so shared templates (platform_v2/templates/tools/media_hub.html)
    # can distinguish standalone deployment from platform-embedded mode and
    # swap out cross-module UI that doesn't make sense here (other-app
    # shortcuts in the LCARS strip, etc.).
    @app.context_processor
    def _inject_standalone_flag():
        return {"standalone": True}

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
