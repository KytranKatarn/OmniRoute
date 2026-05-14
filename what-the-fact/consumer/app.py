from flask import Flask
from .routes import bp
from .auth import auth_bp


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    import os
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev")
    from .billing import billing_bp
    from .db import init_billing_table
    init_billing_table()
    app.register_blueprint(billing_bp)
    app.register_blueprint(bp)
    app.register_blueprint(auth_bp)
    return app
