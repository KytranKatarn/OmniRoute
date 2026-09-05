import os

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from .routes import bp
from .auth import auth_bp


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    # Trust X-Forwarded-Proto and X-Forwarded-Host from Caddy so that
    # request.url_root is https:// not http:// behind the reverse proxy.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    # FLASK_SECRET_KEY signs the session cookie that the cross-watch auth gate
    # (#5747) now depends on. A silent "dev" fallback would make every session
    # forgeable, so refuse to boot instead — fail closed, matching admin_gate().
    # Production sets this; the escape hatch is for local dev only.
    _secret = os.environ.get("FLASK_SECRET_KEY", "")
    if not _secret:
        if os.environ.get("WTF_ALLOW_INSECURE_SECRET") == "1":
            _secret = "dev-insecure-local-only"
        else:
            raise RuntimeError(
                "FLASK_SECRET_KEY is not set. Sessions would be forgeable. "
                "Set it, or export WTF_ALLOW_INSECURE_SECRET=1 for local dev."
            )
    app.secret_key = _secret
    # LOAD-BEARING for the OAuth state check in auth.py. The callback arrives as
    # a top-level GET navigation from platform.kytranempowerment.com, i.e.
    # cross-site: "Lax" still sends the cookie (so the minted state is readable
    # back), "Strict" would NOT and every real login would fail the check.
    # This was previously unset and worked only on the browser default; stating
    # it makes the dependency explicit and immune to a default change.
    # NOT setdefault(): Flask PRE-POPULATES both keys (SAMESITE=None,
    # HTTPONLY=True), so the key already exists and setdefault is a silent
    # no-op — measured live, the Set-Cookie header still carried no SameSite.
    # Direct assignment is the only thing that takes effect here.
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    from .billing import billing_bp
    from .db import init_billing_table
    init_billing_table()
    app.register_blueprint(billing_bp)
    app.register_blueprint(bp)
    app.register_blueprint(auth_bp)
    # Cross-Watch proxy — server-side relay to hub (Task #3023)
    from .cross_watch import cross_watch_bp
    app.register_blueprint(cross_watch_bp)
    # Election Claim Tracker admin CRUD (#3013)
    from .claim_admin_routes import claim_admin_bp
    app.register_blueprint(claim_admin_bp)
    # Topic micro-subscriptions — $2/mo per beat (#3015)
    from .beats import beats_bp
    app.register_blueprint(beats_bp)
    # Entity search & accountability API — MP search now, journalists in Milestone B (#4078)
    from .entities import entities_bp
    app.register_blueprint(entities_bp)
    # Shared Entity Graph INGEST — single-writer endpoint, adapters POST here over the mesh (T-ING-1)
    from .entity_graph_routes import entity_graph_bp
    app.register_blueprint(entity_graph_bp)
    # 8-link Accountability-Chain query API — public, read-only, bounded + cached (#3793)
    from .chain_routes import chain_bp
    app.register_blueprint(chain_bp)
    # Dedup review UI — ADMIN-only (fail-closed X-Admin-Key), resolves merge_review_queue (#3792)
    from .dedup_admin_routes import dedup_admin_bp
    app.register_blueprint(dedup_admin_bp)
    # "What Parliament Costs Canadians" cost API — public, read-only, cached (Phase 1: MPs, #348)
    from .cost_routes import cost_bp
    app.register_blueprint(cost_bp)
    # Admin Mail Dashboard — Citadel-resident IMAP/SMTP reader for the 5 business
    # mailboxes, so mail keeps working through a Hub outage. HTTP Basic-gated
    # (see admin_mail.py) — deliberately independent of the Hub login / OAuth.
    from .admin_mail import admin_mail_bp
    app.register_blueprint(admin_mail_bp)

    @app.route("/version")
    def version():
        """GET /version — deploy-provenance (#4776): the git commit this image was built
        from, so the fleet drift monitor can compare it against the repo head. Public."""
        return {
            "product": "wtf_consumer",
            "git_sha": os.environ.get("WTF_GIT_SHA", "unknown"),
            "build_time": os.environ.get("WTF_BUILD_TIME", "unknown"),
        }

    return app
