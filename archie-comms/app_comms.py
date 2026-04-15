"""A.R.C.H.I.E. Comms — Independent Communication Layer.

Runs as archie_comms container on :3001. Provides:
- Chat UI and API
- Telegram send/receive with personality voice
- Platform health watchdog
- Outbound message queue processor
- Collaboration engine (Claude bridge)
"""

import logging
import os

from flask import Flask, request, jsonify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("archie_comms")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", os.urandom(32).hex())


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "service": "archie_comms", "version": "1.0.0"})


@app.route("/api/send", methods=["POST"])
def api_send():
    """Platform calls this to send a message through A.R.C.H.I.E.'s voice."""
    from services.telegram_service import send

    data = request.get_json() or {}
    result = send(
        category=data.get("category", "info"),
        title=data.get("title", ""),
        message=data.get("message", ""),
        source_agent=data.get("source_agent"),
        source_department=data.get("source_department"),
        source_module=data.get("source_module"),
        force=data.get("force", False),
    )
    return jsonify(result)


@app.route("/")
def index():
    """A.R.C.H.I.E. Comms landing page."""
    return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>A.R.C.H.I.E. Comms</title>
<style>
body{background:#0a0a1a;color:#e0e0e0;font-family:system-ui,sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}
.card{background:#0f0f24;border:2px solid #f060f0;border-radius:16px;padding:40px;text-align:center;max-width:500px}
h1{color:#f060f0;font-size:24px;letter-spacing:2px;margin:0 0 8px}
.status{color:#60dd60;font-size:14px;margin:12px 0}
.dot{display:inline-block;width:8px;height:8px;background:#60dd60;border-radius:50%;margin-right:6px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
p{color:#888;font-size:13px;line-height:1.6;margin:16px 0 0}
a{color:#00d4ff;text-decoration:none}
</style></head><body>
<div class="card">
<h1>A.R.C.H.I.E.</h1>
<div>Autonomous Resource & Cognitive Hyperintelligence Engine</div>
<div class="status"><span class="dot"></span>Online — Independent Comms Layer</div>
<p>I'm running independently from the platform.<br>
Watchdog active. Telegram connected. Voice ready.</p>
<p style="margin-top:24px"><a href="/api/health">Health API</a> &middot;
<a href="https://platform.kytranempowerment.com">Platform Dashboard</a></p>
</div></body></html>"""


def start_background_services():
    from services.watchdog_service import PlatformWatchdog
    from services.queue_service import QueueProcessor

    watchdog = PlatformWatchdog()
    watchdog.start()

    queue = QueueProcessor()
    queue.start()

    logger.info("Background services started (watchdog + queue)")


start_background_services()

if __name__ == "__main__":
    port = int(os.getenv("COMMS_PORT", "3001"))
    app.run(host="0.0.0.0", port=port, debug=False)
