from flask import Flask
from .routes import bp


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    import os
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev")
    app.register_blueprint(bp)
    return app
