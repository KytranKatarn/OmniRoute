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

from flask import Flask, redirect, url_for
from flask_login import LoginManager

# tools.media_hub imports `from database import get_db_cursor`. Our standalone
# /app/database.py (DATABASE_URL-backed) sits on sys.path first — see Dockerfile.
from tools.media_hub import media_hub_bp  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("media_hub.standalone")


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ["MEDIA_HUB_SECRET_KEY"]

    # Auth — task #2150 pt.2 will add a real user model. Until then, every
    # session is anonymous, so the blueprint gate redirects to /auth/sso
    # which returns 501 "not wired yet" — that's the expected UX.
    lm = LoginManager()
    lm.login_view = "media_hub.sso_stub"
    lm.init_app(app)

    @lm.user_loader
    def load_user(_user_id):
        return None  # no users until #2150 pt.2

    app.register_blueprint(media_hub_bp)

    @app.route("/")
    def root():
        return redirect(url_for("media_hub.sso_stub"))

    @app.route("/health")
    def health():
        return {"status": "ok", "mode": "standalone", "product": "media_hub"}, 200

    log.info("Media Hub standalone app ready on blueprint %s", media_hub_bp.url_prefix)
    return app


app = create_app()
