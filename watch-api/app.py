"""W.A.T.C.H. — Watchdog for Accountability, Transparency, Civic Health."""
import os
import threading
from flask import Flask, session, redirect, render_template, send_from_directory
from db import init_db
from routes.health import health_bp
from routes.events import events_bp
from routes.contracts import contracts_bp
from routes.parliament import parliament_bp
from routes.spending import spending_bp
from kytran_auth import KytranAuth
from auth import auth_bp

app = Flask(__name__, static_folder='static', static_url_path='', template_folder='templates')

# Session security
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# KytranAuth SDK
kytran_auth = KytranAuth(app)

_FEATURES = [
    {"title": "Parliament Tracker", "description": "Follow bills, votes, and committee activity in real time across federal and provincial legislatures."},
    {"title": "Contract Monitor", "description": "Search and track government procurement contracts and tender awards across Canada."},
    {"title": "Spending Analysis", "description": "Visualize public expenditure trends, department budgets, and fiscal accountability data."},
    {"title": "Public Accountability", "description": "Cross-reference officials, contracts, and spending in one unified civic intelligence dashboard."},
]


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route('/')
def serve_landing():
    return render_template(
        "landing.html",
        product_name="Kytran Civic Watch",
        product_short="C.W.",
        product_name_html='KYTRAN <span>CIVIC WATCH</span>',
        product_description="Real-time monitoring of government contracts, parliamentary activity, and public spending across Canada.",
        accent_color="#22d3ee",
        features=_FEATURES,
    )


@app.route('/dashboard')
@kytran_auth.login_required
def serve_dashboard():
    return app.send_static_file('index.html')


def create_app():
    init_db()
    app.register_blueprint(auth_bp)
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
        time.sleep(5)
        from ingest.provincial import run_provincial_ingest
        run_provincial_ingest()
        time.sleep(5)
        from ingest.municipal import run_municipal_ingest
        run_municipal_ingest()
        time.sleep(5)
        from ingest.spending import run_spending_ingest
        run_spending_ingest()
    except Exception as e:
        print(f"[W.A.T.C.H.] Startup ingest failed: {e}")


if __name__ == "__main__":
    create_app()
    t = threading.Thread(target=_background_ingest, daemon=True)
    t.start()
    print("W.A.T.C.H. API running on :8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
