"""W.A.T.C.H. — Watchdog for Accountability, Transparency, Civic Health."""
import threading
from flask import Flask
from db import init_db
from routes.health import health_bp
from routes.events import events_bp
from routes.contracts import contracts_bp
from routes.parliament import parliament_bp
from routes.spending import spending_bp

app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def create_app():
    init_db()
    app.register_blueprint(health_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(parliament_bp)
    app.register_blueprint(spending_bp)
    return app


def _background_ingest():
    """Run initial data ingestion in background thread on startup."""
    import time
    time.sleep(5)
    try:
        from ingest.federal import run_federal_ingest
        run_federal_ingest()
    except Exception as e:
        print(f"[W.A.T.C.H.] Startup ingest failed: {e}")


if __name__ == "__main__":
    create_app()
    t = threading.Thread(target=_background_ingest, daemon=True)
    t.start()
    print("W.A.T.C.H. API running on :8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
