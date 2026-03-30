"""Kytran Mail — Flask app factory."""

from flask import Flask, redirect, url_for

from .config import Config


def create_app(config=None):
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(Config)
    if config:
        app.config.update(config)

    from .routes import register_routes

    register_routes(app)

    @app.route("/")
    def index():
        return redirect(url_for("dashboard"))

    return app
