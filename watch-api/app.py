"""W.A.T.C.H. — Watchdog for Accountability, Transparency, Civic Health.

Lightweight Flask API serving Canadian civic data (contracts, parliament, spending).
"""
from flask import Flask
from db import init_db
from routes.health import health_bp

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
    return app


if __name__ == "__main__":
    create_app()
    print("W.A.T.C.H. API running on :8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
