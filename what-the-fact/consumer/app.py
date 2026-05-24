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
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev")
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
    return app
