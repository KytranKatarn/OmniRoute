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
    """Redirect root to chat."""
    from flask import redirect
    return redirect("/chat")


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
