"""Kytran Market Watch — M.A.R.K.E.T. Autonomous Trading Dashboard."""

import os
import time
import threading
import logging

from flask import Flask, send_from_directory, render_template, request, redirect, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def create_app():
    app = Flask(
        __name__,
        static_folder="static",
        static_url_path="/static",
        template_folder="templates",
    )

    # --- Session & Security Config ---
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if os.environ.get("FLASK_ENV") == "production":
        app.config["SESSION_COOKIE_SECURE"] = True

    # --- Rate Limiter ---
    limiter = Limiter(
        get_remote_address,
        app=app,
        storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
        default_limits=[],
    )
    app.limiter = limiter

    # --- Database ---
    from db import init_db
    init_db()

    # --- KytranAuth SDK ---
    from kytran_auth import KytranAuth
    from auth import auth_bp, upsert_local_user

    kytran_auth = KytranAuth()
    app.config["KYTRAN_CLIENT_ID"] = os.environ.get("KYTRAN_CLIENT_ID", "market-watch-viewer")
    kytran_auth.init_app(app)

    @kytran_auth.on_login
    def on_login(user_data):
        """Cache user locally and resolve tier on every login."""
        upsert_local_user(user_data)
        logger.info("User logged in: %s", user_data.get("username"))

    # --- Auth + Public Blueprints ---
    app.register_blueprint(auth_bp)
    limiter.limit("10/minute")(auth_bp)

    from routes.public import public_bp
    app.register_blueprint(public_bp)
    limiter.limit("30/minute")(public_bp)

    from routes.news import news_bp
    app.register_blueprint(news_bp)

    from routes.health import health_bp
    app.register_blueprint(health_bp)

    # --- Protected Route Blueprints ---
    from routes.stocks import stocks_bp
    from routes.watchlist import watchlist_bp
    from routes.charts import charts_bp
    app.register_blueprint(stocks_bp)
    app.register_blueprint(watchlist_bp)
    app.register_blueprint(charts_bp)

    from routes.portfolio import portfolio_bp
    app.register_blueprint(portfolio_bp)

    from routes.trading import trading_bp
    app.register_blueprint(trading_bp)

    from routes.alerts import alerts_bp
    app.register_blueprint(alerts_bp)

    from routes.backtest import backtest_bp
    app.register_blueprint(backtest_bp)

    from routes.analysis import analysis_bp
    app.register_blueprint(analysis_bp)

    from routes.strategy_routes import bp as strategy_bp
    app.register_blueprint(strategy_bp)

    # --- CORS (locked down) ---
    allowed_origins = os.environ.get(
        "CORS_ORIGINS",
        "https://market.kytranempowerment.com,http://192.168.1.200:8080"
    ).split(",")

    @app.after_request
    def add_cors(response):
        origin = request.headers.get("Origin", "")
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH"
            response.headers["Access-Control-Allow-Credentials"] = "true"
        return response

    # --- Landing Page (public) ---
    @app.route("/")
    def landing():
        return render_template("landing.html")

    # --- Dashboard (authenticated) ---
    @app.route("/dashboard")
    def dashboard():
        if "kytran_user" not in session:
            return redirect("/auth/kytran/login?next=/dashboard")
        return send_from_directory("static", "index.html")

    return app


def _background_ingest(app):
    """Background thread for market data ingestion."""
    time.sleep(10)
    with app.app_context():
        logger.info("Background ingest thread started")
        while True:
            try:
                from ingest.price_ingest import run_price_ingest
                run_price_ingest()
            except Exception as e:
                logger.error("Price ingest failed: %s", e)
            time.sleep(300)  # 5 minutes


def _background_news_ingest(app):
    """Background thread for news ingestion."""
    time.sleep(20)  # Wait for app + price ingest to settle
    with app.app_context():
        logger.info("Background news ingest thread started")
        while True:
            try:
                from ingest.news_ingest import run_news_ingest, NEWS_INGEST_INTERVAL
                run_news_ingest()
                time.sleep(NEWS_INGEST_INTERVAL)
            except Exception as e:
                logger.error("News ingest failed: %s", e)
                time.sleep(60)  # Retry after 1 min on error


def _background_position_monitor(app):
    """Background thread for real-time position exit monitoring."""
    time.sleep(30)  # Wait for app to settle
    with app.app_context():
        logger.info(
            "Background position monitor started (every %ds)",
            int(os.environ.get("MW_POSITION_CHECK_INTERVAL", 60)),
        )
        while True:
            try:
                from ingest.position_monitor import run_position_check, POSITION_CHECK_INTERVAL
                run_position_check()
                time.sleep(POSITION_CHECK_INTERVAL)
            except Exception as e:
                logger.error("Position monitor failed: %s", e)
                time.sleep(10)


if __name__ == "__main__":
    app = create_app()
    ingest_thread = threading.Thread(target=_background_ingest, args=(app,), daemon=True)
    ingest_thread.start()
    news_thread = threading.Thread(target=_background_news_ingest, args=(app,), daemon=True)
    news_thread.start()
    position_thread = threading.Thread(target=_background_position_monitor, args=(app,), daemon=True)
    position_thread.start()
    app.run(host="0.0.0.0", port=8080, debug=False)
