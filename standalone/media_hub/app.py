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

from auth_routes import auth_bp  # noqa: E402
from users import bootstrap_admin_if_empty, load_user  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("media_hub.standalone")


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.config["SECRET_KEY"] = os.environ["MEDIA_HUB_SECRET_KEY"]

    lm = LoginManager()
    lm.login_view = "auth.login"
    lm.init_app(app)
    lm.user_loader(load_user)

    app.register_blueprint(auth_bp)
    app.register_blueprint(media_hub_bp)

    # Create admin from MEDIA_HUB_ADMIN_PASSWORD if users table is empty.
    with app.app_context():
        try:
            bootstrap_admin_if_empty()
        except Exception as e:
            log.warning("bootstrap_admin skipped: %s", e)

    @app.route("/")
    def root():
        return redirect(url_for("media_hub.index"))

    @app.route("/health")
    def health():
        return {"status": "ok", "mode": "standalone", "product": "media_hub"}, 200

    log.info("Media Hub standalone app ready on blueprint %s", media_hub_bp.url_prefix)
    return app


app = create_app()
