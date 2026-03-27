"""Kytran Legal Watch — Canadian Legal Intelligence Dashboard.
Powered by G.A.V.E.L. (Legal & Regulatory AI Director).
"""
import threading
from flask import Flask
from db import init_db

app = Flask(__name__, static_folder='static', static_url_path='')


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route('/')
def serve_dashboard():
    return app.send_static_file('index.html')


def create_app():
    init_db()
    from routes.health import health_bp
    from routes.events import events_bp
    from routes.regulations import regulations_bp
    app.register_blueprint(health_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(regulations_bp)
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
