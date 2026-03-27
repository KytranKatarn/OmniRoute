"""Kytran Market Watch — M.A.R.K.E.T. Autonomous Trading Dashboard."""

import os
import time
import threading
import logging
from flask import Flask, send_from_directory

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def create_app():
    app = Flask(
        __name__,
        static_folder="static",
        static_url_path="/static",
    )

    from db import init_db
    init_db()

    from routes.health import health_bp
    app.register_blueprint(health_bp)

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

    @app.after_request
    def add_cors(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH"
        return response

    @app.route("/")
    def index():
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


if __name__ == "__main__":
    app = create_app()
    ingest_thread = threading.Thread(target=_background_ingest, args=(app,), daemon=True)
    ingest_thread.start()
    app.run(host="0.0.0.0", port=8080, debug=False)
