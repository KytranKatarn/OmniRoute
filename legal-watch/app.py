"""Kytran Legal Watch — Canadian Legal Intelligence Dashboard.
Powered by G.A.V.E.L. (Legal & Regulatory AI Director).
"""
import os
import threading

from flask import Flask, redirect, render_template, send_from_directory, session

from db import init_db
from kytran_auth import KytranAuth

app = Flask(__name__, static_folder="static", static_url_path="", template_folder="templates")

# Session security
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# KytranAuth SDK
kytran_auth = KytranAuth()
kytran_auth.init_app(app)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/")
def serve_landing():
    return render_template("landing.html")


@app.route("/dashboard")
@kytran_auth.login_required
def serve_dashboard():
    return send_from_directory(app.static_folder, "index.html")


def create_app():
    init_db()
    from auth import auth_bp
    from routes.health import health_bp
    from routes.events import events_bp
    from routes.regulations import regulations_bp
    from routes.canlii import canlii_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(regulations_bp)
    app.register_blueprint(canlii_bp)
    return app


def _background_ingest():
    import time

    time.sleep(5)
    try:
        from ingest.gazette import run_gazette_ingest

        run_gazette_ingest()
        time.sleep(3)
        from ingest.legal_news import run_legal_news_ingest

        run_legal_news_ingest()
    except Exception as e:
        print(f"[G.A.V.E.L.] Startup ingest failed: {e}")


if __name__ == "__main__":
    create_app()
    t = threading.Thread(target=_background_ingest, daemon=True)
    t.start()
    print("Kytran Legal Watch API running on :8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
