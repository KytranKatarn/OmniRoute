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
        if (
            host.startswith("192.168.")
            or host.startswith("127.")
            or host.startswith("localhost")
        ):
            kytran_auth.client_id = os.getenv(
                "KYTRAN_CLIENT_ID_LAN", "media-hub-viewer-lan"
            )
            kytran_auth.client_secret = os.getenv("KYTRAN_CLIENT_SECRET_LAN", "")
            kytran_auth.redirect_uri = os.getenv(
                "KYTRAN_REDIRECT_URI_LAN",
                "http://192.168.1.200:8105/auth/kytran/callback",
            )
            # LAN: use hub internal address — CDN/openresty blocks public OAuth
            kytran_auth.auth_url = os.getenv(
                "KYTRAN_AUTH_URL_LAN", "http://192.168.1.200:3000"
            )
            # internal_url = same as auth_url for LAN (already direct)
            kytran_auth.internal_url = kytran_auth.auth_url
        else:
            kytran_auth.client_id = os.getenv("KYTRAN_CLIENT_ID", "media-hub-viewer")
            kytran_auth.client_secret = os.getenv("KYTRAN_CLIENT_SECRET", "")
            kytran_auth.redirect_uri = os.getenv(
                "KYTRAN_REDIRECT_URI",
                "https://media.kytranempowerment.com/auth/kytran/callback",
            )
            kytran_auth.auth_url = os.getenv(
                "KYTRAN_AUTH_URL", "https://platform.kytranempowerment.com"
            )
            # internal_url: server-to-server token exchange + userinfo bypass CDN (60s cap)
            kytran_auth.internal_url = os.getenv(
                "KYTRAN_AUTH_INTERNAL_URL", "http://192.168.1.200:3000"
            )

    @app.before_request
    def _refresh_sso_tokens_if_needed():
        """Silently refresh Kytran OAuth tokens before each request when close to expiry."""
        from flask_login import current_user

        if current_user.is_authenticated and current_user.is_sso:
            try:
                kytran_auth._refresh_if_needed()
            except Exception:
                pass  # Never block a request over a refresh failure

    def _sync_user_tier(user_data: dict) -> None:
        """Persist the Media Hub subscription tier on every SSO login.

        Reads product_tiers["media_hub"] from the SSO payload. Tier is NEVER
        downgraded — only update if the incoming tier rank exceeds the stored one.
        Owner / admin accounts are always pinned to the highest tier.
        """
        email = (user_data.get("email") or "").strip().lower()
        if not email:
            return

        _product_tiers = user_data.get("product_tiers") or {}
        incoming_tier = (
            _product_tiers.get("media_hub")
            or user_data.get("subscription_tier")
            or "free"
        ).lower()

        # Only canonical platform roles pin to the top tier. Non-standard strings
        # like "owner"/"kytran" and the is_owner/is_admin booleans are omitted —
        # they are not issued by the platform IdP and would be spoofable.
        _ADMIN_ROLES = frozenset({"admin", "super_admin"})
        if (user_data.get("role") or "").lower() in _ADMIN_ROLES:
            incoming_tier = "admin"

        try:
            from database import get_db_cursor

            with get_db_cursor(cursor_factory=None, commit=True) as (_conn, cur):
                cur.execute(
                    """
                    UPDATE media_hub_users
                    SET role = CASE
                        WHEN (CASE role
                                  WHEN 'kytran'     THEN 99
                                  WHEN 'owner'      THEN 99
                                  WHEN 'admin'      THEN 99
                                  WHEN 'super_admin' THEN 99
                                  WHEN 'pro'        THEN 60
                                  WHEN 'agency'     THEN 50
                                  WHEN 'team'       THEN 40
                                  WHEN 'solo'       THEN 30
                                  WHEN 'starter'    THEN 10
                                  ELSE 0 END)
                             > (CASE %s
                                  WHEN 'kytran'     THEN 99
                                  WHEN 'owner'      THEN 99
                                  WHEN 'admin'      THEN 99
                                  WHEN 'super_admin' THEN 99
                                  WHEN 'pro'        THEN 60
                                  WHEN 'agency'     THEN 50
                                  WHEN 'team'       THEN 40
                                  WHEN 'solo'       THEN 30
                                  WHEN 'starter'    THEN 10
                                  ELSE 0 END)
                        THEN role
                        ELSE %s
                    END
                    WHERE email = %s AND sso_sub IS NOT NULL
                    """,
                    (incoming_tier, incoming_tier, email),
                )
        except Exception as exc:
            log.warning("_sync_user_tier: failed for %s — %s", email, exc)

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
            _sync_user_tier(user_data)
            login_user(user)
            log.info(
                "SSO login: %s (sso_sub=%s, admin=%s)",
                user.username,
                user.sso_sub,
                user.is_admin,
            )
        else:
            log.warning(
                "SSO login rejected (upsert failed or user inactive): %s",
                user_data.get("sub"),
            )

    from user_routes import user_mgmt_bp  # noqa: E402

    app.register_blueprint(auth_bp)
    app.register_blueprint(user_mgmt_bp)
    app.register_blueprint(media_hub_bp)

    # M.A.V.E.N. skills — mounted at /maven/*. troubleshoot + upgrades are
    # admin-only (enforced per-route); discover is available to any
    # authenticated user. Project #279 tasks #2239/#2240/#2241.
    from maven import maven_bp  # noqa: E402

    app.register_blueprint(maven_bp)

    from watchlist_routes import watchlist_bp  # noqa: E402
    from preferences_routes import preferences_bp  # noqa: E402

    app.register_blueprint(watchlist_bp)
    app.register_blueprint(preferences_bp)

    @app.context_processor
    def _inject_standalone_flag():
        return {"standalone": True}

    @app.context_processor
    def _inject_current_lang():
        lang = "en"
        if current_user.is_authenticated:
            try:
                from database import get_db_cursor

                with get_db_cursor(commit=False) as (conn, cur):
                    cur.execute(
                        "SELECT value FROM user_preferences WHERE user_id=%s AND key='language'",
                        (current_user.id,),
                    )
                    row = cur.fetchone()
                    if row:
                        lang = row["value"]
            except Exception:
                pass
        return {"current_lang": lang}

    # Scheduled health observers (project #279 tasks #2243, #2244). APScheduler
    # runs in-process alongside gunicorn. Opt-out: MEDIA_HUB_DISABLE_OBSERVERS=1.
    # Catches the "row says healthy 2 days ago but service actually died" trap
    # that let Prowlarr go blind against NZBgeek for 7 days.
    if os.environ.get("MEDIA_HUB_DISABLE_OBSERVERS", "").lower() not in ("1", "true"):
        try:
            from health_observer import start_scheduler  # noqa: E402

            start_scheduler()
        except Exception as e:
            log.warning("health observer scheduler failed to start: %s", e)

    # Gate /login after registration. Flask stores the dispatch target in
    # app.view_functions — decorating with limiter.limit returns a new fn,
    # so we have to reassign it back or the limit never fires.
    app.view_functions["auth.login"] = limiter.limit("10 per minute; 30 per hour")(
        app.view_functions["auth.login"]
    )

    # M.A.V.E.N. skill rate limits (task #2248). Applied per-endpoint because
    # each has a different cost profile: chat pins a GPU, troubleshoot +
    # upgrades fan out to *arr apps, discover hits a single Overseerr page.
    # Keyed on remote IP (single gunicorn worker → memory store is fine).
    _maven_limits = {
        "maven.api_chat": "20 per minute; 400 per day",
        "maven.chat_page": "30 per minute",
        "maven.api_troubleshoot": "10 per minute; 120 per hour",
        "maven.troubleshoot_page": "10 per minute",
        "maven.api_upgrades": "10 per minute; 120 per hour",
        "maven.upgrades_page": "10 per minute",
        "maven.api_duplicates": "6 per minute; 60 per hour",
        "maven.duplicates_page": "6 per minute",
        "maven.api_discover": "30 per minute; 500 per day",
        "maven.discover_page": "30 per minute",
        "user_mgmt.admin_users": "30 per minute",
        "user_mgmt.profile": "30 per minute",
        "maven.api_quality_report": "10 per minute; 60 per hour",
        "maven.api_upgrade_oversized": "5 per minute; 20 per hour",
        "watchlist.list_watchlist": "60 per minute",
        "watchlist.add_to_watchlist": "30 per minute",
        "watchlist.remove_from_watchlist": "30 per minute",
        "preferences.get_preferences": "60 per minute",
        "preferences.set_preference": "20 per minute",
    }
    for view_name, rate in _maven_limits.items():
        if view_name in app.view_functions:
            app.view_functions[view_name] = limiter.limit(rate)(
                app.view_functions[view_name]
            )

    # Friendly error pages. Shared template at templates/error.html renders
    # a severity pill + remediation hint. Rendered HTML for browser traffic;
    # /api/ and /maven/api/ paths get JSON so fetch() callers can parse.
    def _render_error(code: int, title: str, message: str, fix: str = ""):
        path = request.path or ""
        if path.startswith("/api/") or "/api/" in path:
            return (
                jsonify(
                    {
                        "error": title,
                        "message": message,
                        "fix": fix,
                        "code": code,
                    }
                ),
                code,
            )
        return (
            render_template(
                "error.html",
                code=code,
                title=title,
                message=message,
                fix=fix,
            ),
            code,
        )

    @app.errorhandler(403)
    def _err_403(e):
        return _render_error(
            403,
            "Not allowed",
            "This page is admin-only.",
            "Sign in with an admin account, or ask Kytran to promote yours.",
        )

    @app.errorhandler(404)
    def _err_404(e):
        return _render_error(
            404,
            "Not found",
            "That URL isn't part of Media Hub.",
            "Head back to the home page or try /maven/discover to browse.",
        )

    @app.errorhandler(429)
    def _err_429(e):
        # flask-limiter passes the retry-after window on e.description when
        # available; fall back to a generic message otherwise.
        msg = getattr(e, "description", "") or str(e)
        return _render_error(
            429,
            "Slow down",
            f"You're hitting that endpoint too fast. {msg}",
            "Wait a few seconds and retry. This limit exists to keep the "
            "LLM + download-client APIs responsive for everyone at home.",
        )

    @app.errorhandler(500)
    def _err_500(e):
        log.exception("500 handler fired: %s", e)
        return _render_error(
            500,
            "Something broke",
            "An internal error was logged.",
            "If this repeats, run /maven/troubleshoot (admin) to see which "
            "service is degraded, or check docker logs mediahub_app.",
        )

    @app.errorhandler(502)
    def _err_502(e):
        return _render_error(
            502,
            "Upstream not responding",
            "A service Media Hub depends on (Plex / Jellyfin / Sonarr / "
            "Radarr / Prowlarr / SABnzbd / Overseerr) isn't replying.",
            "Visit /maven/troubleshoot (admin) — it tells you which one "
            "and, if DNS is the cause, how to fix it.",
        )

    @app.errorhandler(503)
    def _err_503(e):
        return _render_error(
            503,
            "Temporarily unavailable",
            "Media Hub or one of its backends is offline.",
            "Check docker ps; the offender is usually visible on "
            "/maven/troubleshoot (admin).",
        )

    @app.errorhandler(504)
    def _err_504(e):
        return _render_error(
            504,
            "Backend timed out",
            "A backend took too long to reply.",
            "Ollama cold-load can take ~60s on first M.A.V.E.N. chat after "
            "idle; retry once. If it repeats, /maven/troubleshoot.",
        )

    # Create admin from MEDIA_HUB_ADMIN_PASSWORD if users table is empty.
    with app.app_context():
        try:
            bootstrap_admin_if_empty()
        except Exception as e:
            log.warning("bootstrap_admin skipped: %s", e)

    @app.route("/")
    def root():
        # Anonymous visitors see the public landing. Authenticated users go to
        # Discover — a standalone-native route protected by kytran_auth.
        # Avoids redirect to /tools/media-hub/ which uses platform install_auth
        # and can fail in standalone context.
        if current_user.is_authenticated:
            return redirect("/maven/discover")
        return render_template("landing.html")

    @app.route("/agent")
    def agent_info():
        """M.A.V.E.N. agent metadata. The hub record (agents.id=27) has been
        live since before this standalone shipped; what was new in PR #261
        was the first real skill surface (/maven/troubleshoot + /upgrades +
        /discover) and — in the PR that added this route update — a direct
        chat endpoint at /maven/chat. Full Bridge dispatch from the
        standalone is still phase 2 (task #2237 phase 2)."""
        return (
            jsonify(
                {
                    "status": "live",
                    "agent_id": 27,
                    "name": "M.A.V.E.N.",
                    "display_name": "Camille Dubois (M.A.V.E.N.)",
                    "expansion": "Media Archive & Viewing Experience Navigator",
                    "archetype": "Same pattern as F.O.R.G.E., V.I.G.I.L., P.R.O.B.E.",
                    "department": "News & Media",
                    "model": os.environ.get("MAVEN_CHAT_MODEL", "llama3.2:3b"),
                    "skill_routes": [
                        "/maven/chat",
                        "/maven/troubleshoot",
                        "/maven/upgrades",
                        "/maven/discover",
                    ],
                    "phase": "phase 1 (direct Ollama dispatch; bridge dispatch phase 2)",
                }
            ),
            200,
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

    @app.route("/version")
    def version():
        """Build provenance — the git commit baked into THIS image + when it was
        built. Stamped by scripts/deploy_with_sha.sh at build time. Lets
        scripts/deploy_drift_check.py compare the running image against
        origin/main and catch deploy-from-feature-branch drift (KB #279350)."""
        return {
            "product": "media_hub",
            "git_sha": os.environ.get("MEDIA_HUB_GIT_SHA", "unknown"),
            "build_time": os.environ.get("MEDIA_HUB_BUILD_TIME", "unknown"),
        }, 200

    # Digital Asset Links — Fire TV / Android TV TWA trust binding.
    # ANDROID_APK_PACKAGE defaults to the Bubblewrap package id; SHA-256
    # fingerprints come from the signing keystore (see bubblewrap/README).
    # Comma-separate multiple fingerprints for keystore rotation.
    @app.route("/.well-known/assetlinks.json")
    def assetlinks():
        fps = os.environ.get("ANDROID_APK_FINGERPRINTS", "").strip()
        pkg = os.environ.get("ANDROID_APK_PACKAGE", "com.kytranempowerment.mediahub")
        if not fps:
            # Empty array is valid JSON — means no TWA apps trusted yet. Allows
            # us to publish this route before the first APK ships.
            return jsonify([]), 200
        return (
            jsonify(
                [
                    {
                        "relation": ["delegate_permission/common.handle_all_urls"],
                        "target": {
                            "namespace": "android_app",
                            "package_name": pkg,
                            "sha256_cert_fingerprints": [
                                fp.strip() for fp in fps.split(",") if fp.strip()
                            ],
                        },
                    }
                ]
            ),
            200,
        )

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
