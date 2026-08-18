from flask import Flask
from flask_cors import CORS
from shared.kytran_auth import KytranAuth
from .routes import bp


def create_app():
    import os
    app = Flask(__name__, template_folder="templates", static_folder="static")
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
    # Allow what-the-fact.com consumer to fetch map-data + agent-activity
    CORS(app, resources={r"/api/v1/*": {"origins": [
        "https://what-the-fact.com",
        "http://what-the-fact.com",
        "http://localhost:8103",
    ]}})
    KytranAuth(app)
    app.register_blueprint(bp)
    from .api import api
    app.register_blueprint(api)

    @app.route("/version")
    def version():
        """GET /version — deploy-provenance (#4776): the git commit this image was built
        from, so the fleet drift monitor can compare it against the repo head. Public."""
        return {
            "product": "wtf_tech",
            "git_sha": os.environ.get("WTF_GIT_SHA", "unknown"),
            "build_time": os.environ.get("WTF_BUILD_TIME", "unknown"),
        }

    return app
