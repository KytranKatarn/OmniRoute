"""Create the What The Fact tech service with session signing, SSO and API routes."""

from shared.session_security import session_signing_key
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
    app.secret_key = session_signing_key()
    # Allow what-the-fact.com consumer to fetch map-data + agent-activity
    CORS(
        app,
        resources={
            r"/api/v1/*": {
                "origins": [
                    "https://what-the-fact.com",
                    "http://what-the-fact.com",
                    "http://localhost:8103",
                ]
            }
        },
    )
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
