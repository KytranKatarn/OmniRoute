from flask import Flask
from shared.kytran_auth import KytranAuth
from .routes import bp


def create_app():
    import os
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev")
    KytranAuth(app)
    app.register_blueprint(bp)
    from .api import api
    app.register_blueprint(api)
    return app
